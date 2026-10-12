import {
  type Api,
  type AssistantMessage,
  type AssistantMessageEvent,
  type AssistantMessageEventStream,
  createAssistantMessageEventStream,
  type Model,
  type SimpleStreamOptions,
  streamSimple,
  type TranscriptContext,
} from "@spoin/pi-ai";
import type { ModelCallFailure } from "@spoin/shared/enums";
import type { Db } from "../db/client.ts";
import { modelCall } from "../db/schema.ts";
import { log } from "../log.ts";

/**
 * One model call, timed and sorted into breader's failure kinds (task 0045), and its
 * `model_call` row. Every call goes through here, through the NIM balancer or straight to
 * CLIProxyAPI.
 */

/** Longest wait for the first token, and longest silence once the answer has started (breader's). */
const FIRST_TOKEN_S = 600;
const IDLE_S = 240;

/** What one call came to. `failure` is null for an answer the caller can use. */
export interface CallOutcome {
  message: AssistantMessage;
  startedAt: Date;
  firstTokenMs: number | null;
  totalMs: number;
  failure: ModelCallFailure | null;
  /** Why it failed, for the log and the next try. */
  reason: string | null;
  /** The provider's Retry-After, in seconds. */
  retryAfterS?: number;
  /** For a call refused for asking too much: the most it may ask for. */
  room?: number;
  /** The caller gave up on it: neither an answer nor the model's failure, so it isn't recorded. */
  abandoned: boolean;
}

/**
 * Kimi K3 counts the prompt and the answer together against its limit, and says so when a call
 * asks for more: "This model configuration accepts at most 1048576 combined input and output
 * tokens. However, your request has 129334 input tokens and asks for ..." (breader's nim.ts).
 */
const SHARED_LIMIT =
  /at most (\d+) combined input and output tokens\. However, your request has (\d+) input tokens/;

/**
 * NVIDIA caps max_tokens itself too, and moves the cap without a word: Kimi K3 took 1,048,576 on
 * 2026-10-10 and turned it down the next day with "Max tokens must not exceed 131072".
 */
const CAP = /Max tokens must not exceed (\d+)/i;

/** The most an error says a call may ask for, or undefined when the error isn't about that. */
export function roomLeft(text: string): number | undefined {
  const shared = text.match(SHARED_LIMIT);
  if (shared) return Number(shared[1]) - Number(shared[2]);
  const cap = text.match(CAP);
  if (cap) return Number(cap[1]);
  return undefined;
}

/**
 * A limit or a quota is a rate failure however it's worded and whatever status it comes with
 * (breader's harness `failureOf`): Google says RESOURCE_EXHAUSTED, or "Server requested 30s retry
 * delay", and an account out of its limit isn't a sign-in turned away.
 */
const QUOTA = /RESOURCE_EXHAUSTED|quota|Server requested \d+s retry delay/i;

export function kindOf(status: number): ModelCallFailure {
  if (status === 429) return "rate";
  if (status === 401 || status === 403 || status === 404) return "gone";
  if (status === 504 || status === 408) return "slow";
  if (status >= 500) return "busy";
  return "bad";
}

/**
 * The HTTP status an error message carries, for APIs whose SDK gives no way to watch the
 * response (Gemini's): the first 4xx or 5xx in its opening words.
 */
function statusIn(message: string): number | undefined {
  const match = message.slice(0, 300).match(/\b([45]\d\d)\b/);
  return match ? Number(match[1]) : undefined;
}

/** A failure that arrived inside a stream that had started fine. */
function streamFailure(message: string): ModelCallFailure {
  if (/overload|unavailable|capacity/i.test(message)) return "busy";
  if (/rate|too many/i.test(message)) return "rate";
  return "slow";
}

const usable = (message: AssistantMessage) =>
  message.content.some(
    (block) => block.type === "toolCall" || (block.type === "text" && block.text.trim() !== ""),
  );

/**
 * Runs one call to its end. `forward` gets every event as it comes, for a caller streaming the
 * answer on; without it the caller gets only the outcome.
 */
export async function runCall(
  model: Model<Api>,
  context: TranscriptContext,
  options: SimpleStreamOptions,
  forward?: (event: AssistantMessageEvent) => void,
): Promise<CallOutcome> {
  const startedAt = new Date();
  const t0 = performance.now();
  const timeout = new AbortController();
  let why = "";
  let timer: NodeJS.Timeout | undefined;
  const arm = (seconds: number, what: string) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      why = what;
      timeout.abort();
    }, seconds * 1000);
  };
  // Seen by the OpenAI SDK's fetch: the status and Retry-After of a refused call. Gemini's adapter
  // takes no custom fetch, so a Gemini failure's status comes from its message.
  let status: number | undefined;
  let retryAfter: string | null = null;
  const watching: typeof fetch = async (input, init) => {
    const response = await fetch(input, init);
    status = response.status;
    retryAfter = response.headers.get("retry-after");
    return response;
  };
  const signal = options.signal ? AbortSignal.any([options.signal, timeout.signal]) : timeout.signal;

  arm(FIRST_TOKEN_S, "no first token");
  let firstTokenMs: number | null = null;
  const watched = model.api === "openai-completions" ? { fetch: watching } : {};
  const stream = streamSimple(model, context, { ...options, signal, ...watched });
  try {
    for await (const event of stream) {
      if (event.type.endsWith("_delta")) {
        firstTokenMs ??= Math.round(performance.now() - t0);
        arm(IDLE_S, "the answer stalled");
      }
      forward?.(event);
    }
  } finally {
    clearTimeout(timer);
  }
  const message = await stream.result();
  const outcome: CallOutcome = {
    message,
    startedAt,
    firstTokenMs,
    totalMs: Math.round(performance.now() - t0),
    failure: null,
    reason: null,
    abandoned: false,
  };

  const text = message.errorMessage ?? "";
  if (message.stopReason === "aborted") {
    if (!why) return { ...outcome, abandoned: true };
    return { ...outcome, failure: "slow", reason: why };
  }
  if (message.stopReason === "error") {
    const refused = status !== undefined && status >= 400 ? status : statusIn(text);
    const seconds = Number(retryAfter);
    let failure: ModelCallFailure = refused !== undefined ? kindOf(refused) : streamFailure(text);
    if (QUOTA.test(text)) failure = "rate";
    return {
      ...outcome,
      failure,
      reason: text.replace(/\s+/g, " ").slice(0, 300),
      retryAfterS: seconds > 0 ? seconds : undefined,
      room: roomLeft(text),
    };
  }
  if (message.stopReason === "length") {
    return {
      ...outcome,
      failure: "cut",
      reason: `the answer hit max_tokens (${options.maxTokens ?? model.maxTokens})`,
    };
  }
  if (!usable(message)) {
    return { ...outcome, failure: "empty", reason: `an empty answer (stop ${message.stopReason})` };
  }
  return outcome;
}

/** Writes a call's row. Logging never stops a call, so a failed insert is only logged. */
export type RecordCall = (model: Model<Api>, outcome: CallOutcome) => void;

/** `runId`: the harness run the calls are for, if they are. */
export function recordTo(db: Db, runId: string | null = null): RecordCall {
  return (model, outcome) => {
    if (outcome.abandoned) return;
    const usage = outcome.message.usage;
    db.insert(modelCall)
      .values({
        runId,
        startedAt: outcome.startedAt,
        provider: model.provider,
        model: model.id,
        ok: outcome.failure === null,
        failure: outcome.failure,
        reason: outcome.reason,
        firstTokenMs: outcome.firstTokenMs,
        totalMs: outcome.totalMs,
        promptTokens: usage.input || null,
        outputTokens: usage.output || null,
      })
      .catch((error: unknown) => log.warn({ err: error, model: model.id }, "model_call row not written"));
  };
}

/** An answer that never came, for a stream that has to end with an error. */
export function failedMessage(model: Model<Api>, errorMessage: string): AssistantMessage {
  return {
    role: "assistant",
    content: [],
    api: model.api,
    provider: model.provider,
    model: model.id,
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason: "error",
    errorMessage,
    timestamp: Date.now(),
  };
}

/** A stream that plays back a call that has already ended. */
export function replay(message: AssistantMessage): AssistantMessageEventStream {
  const stream = createAssistantMessageEventStream();
  endWith(stream, message);
  return stream;
}

/** Ends a stream with a call that has already ended. */
export function endWith(stream: AssistantMessageEventStream, message: AssistantMessage): void {
  if (message.stopReason === "error" || message.stopReason === "aborted") {
    stream.push({ type: "error", reason: message.stopReason, error: message });
  } else {
    stream.push({ type: "done", reason: message.stopReason as "stop" | "length" | "toolUse", message });
  }
  stream.end();
}

/**
 * pi's stream function for a model called straight, Gemini through CLIProxyAPI: the answer
 * streams on as it comes, and the call is recorded when it ends.
 */
export function recordedStreamFn(record: RecordCall) {
  return (model: Model<Api>, context: TranscriptContext, options?: SimpleStreamOptions) => {
    const stream = createAssistantMessageEventStream();
    void runCall(model, context, options ?? {}, (event) => stream.push(event)).then(
      (outcome) => {
        record(model, outcome);
        stream.end(outcome.message);
      },
      (error: unknown) => {
        log.error({ err: error, model: model.id }, "model call failed outside pi");
        stream.end(failedMessage(model, "The call failed before the model answered."));
      },
    );
    return stream;
  };
}
