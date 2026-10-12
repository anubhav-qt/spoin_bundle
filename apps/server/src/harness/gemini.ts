import type { StreamFn } from "@spoin/pi-agent";
import {
  type Api,
  type AssistantMessage,
  createAssistantMessageEventStream,
  type Model,
  type SimpleStreamOptions,
  type TranscriptContext,
} from "@spoin/pi-ai";
import { log } from "../log.ts";
import { backoffS, jitter, sleep } from "../models/balancer.ts";
import { endWith, failedMessage, type RecordCall, runCall } from "../models/calls.ts";

/*
 * How a harness run calls Gemini (task 0045, "A harness run waits Gemini out on Flash"): breader's
 * harness (`ai/tools/harness.ts` on origin/dev), on Flash alone. The run stays open through a
 * failure; Flash cools, the wait doubling with each failure in a row, with jitter, and the same call
 * is made again. When every Antigravity account is out of its 5-hour or weekly limit, the call waits
 * for the first to fill. While the proxy is down, it looks again every minute. What waiting can't
 * fix (Gemini turning the call away, a request it refuses) ends the run.
 *
 * Each call is buffered until it ends, so a failed one is made again before the chat sees it.
 * Every try is a `model_call` row.
 */

/** First cooldown and cap, in seconds, for each kind of failure that waits (breader's). */
const COOL = { rate: [60, 1800], busy: [30, 600] } as const;
/** The longest wait before looking again, and how often a proxy that's down is looked for. */
const LOOK_AGAIN_MS = 60_000;

interface Cooling {
  strikes: number;
  until: number;
}

/** Each model's cooldown, shared by every run in the process: they all call the same accounts. */
const COOLING = new Map<string, Cooling>();

export interface PatientGeminiOptions {
  /** Writes each try's `model_call` row. */
  record: RecordCall;
  /** When an account will have Gemini again (`geminiOpensAt`), or null when that can't be told. */
  opensAt: () => Promise<number | null>;
  /** Whether the proxy answers at all. */
  proxyAnswers: () => Promise<boolean>;
  /** Tests make the waits instant. */
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
}

/** pi's stream function for a harness run on Gemini. */
export function patientGemini(options: PatientGeminiOptions): StreamFn {
  return (model, context, streamOptions) => {
    const stream = createAssistantMessageEventStream();
    void callUntilAnswered(model, context, streamOptions ?? {}, options).then(
      (message) => endWith(stream, message),
      (error: unknown) => {
        log.error({ err: error, model: model.id }, "a harness call failed outside pi");
        endWith(stream, failedMessage(model, "The call failed before the model answered."));
      },
    );
    return stream;
  };
}

async function callUntilAnswered(
  model: Model<Api>,
  context: TranscriptContext,
  streamOptions: SimpleStreamOptions,
  options: PatientGeminiOptions,
): Promise<AssistantMessage> {
  const wait = options.sleep ?? sleep;
  const signal = streamOptions.signal;
  for (;;) {
    await whileCooling(model.id, wait, signal);
    if (signal?.aborted) return stopped(model);
    // CLIProxyAPI retries across the accounts itself.
    const outcome = await runCall(model, context, { ...streamOptions, maxRetries: 0 });
    options.record(model, outcome);
    const message = outcome.message;
    if (message.stopReason === "aborted") return message;
    if (message.stopReason !== "error") {
      COOLING.delete(model.id);
      return message;
    }
    const reason = outcome.reason ?? message.errorMessage ?? "no reason given";
    if (outcome.failure === "gone") {
      return {
        ...message,
        errorMessage: `Gemini turned the call away (${reason}). Check the sign-ins on the admin page's model accounts, and the proxy's key in infra/.env.`,
      };
    }
    if (outcome.failure === "bad") return message;
    if (outcome.failure === "rate") {
      if (await waitForLimits(options.opensAt, wait, signal)) continue;
      cool(model.id, "rate");
      continue;
    }
    if (!(await options.proxyAnswers())) {
      await waitForProxy(options.proxyAnswers, wait, signal);
      continue;
    }
    cool(model.id, "busy");
  }
}

/** A model hit a limit or found the server busy: it cools, longer with each failure in a row. */
function cool(id: string, kind: keyof typeof COOL): void {
  const cooling = COOLING.get(id) ?? { strikes: 0, until: 0 };
  cooling.strikes++;
  const [base, cap] = COOL[kind];
  cooling.until = Date.now() + backoffS(cooling.strikes, base, cap) * 1000;
  COOLING.set(id, cooling);
  log.warn({ model: id, kind, strikes: cooling.strikes, until: new Date(cooling.until) }, "Gemini cools");
}

async function whileCooling(id: string, wait: PatientWait, signal: AbortSignal | undefined): Promise<void> {
  for (;;) {
    const left = (COOLING.get(id)?.until ?? 0) - Date.now();
    if (left <= 0 || signal?.aborted) return;
    await wait(jitter(Math.min(left, LOOK_AGAIN_MS)), signal);
  }
}

/** Waits for an Antigravity account with Gemini left, when none has any. True if it waited. */
async function waitForLimits(
  opensAt: () => Promise<number | null>,
  wait: PatientWait,
  signal: AbortSignal | undefined,
): Promise<boolean> {
  let at: number | null;
  try {
    at = await opensAt();
  } catch {
    return false;
  }
  if (at === null) return false;
  const left = at - Date.now();
  if (left <= 0) return false;
  log.warn(
    { until: new Date(at) },
    "every Antigravity account is out of Gemini: waiting for the first to fill",
  );
  // A minute or so past the reset, so the accounts are surely open again.
  await wait(left + jitter(60_000), signal);
  return true;
}

async function waitForProxy(
  proxyAnswers: () => Promise<boolean>,
  wait: PatientWait,
  signal: AbortSignal | undefined,
): Promise<void> {
  log.warn("CLIProxyAPI isn't answering: looking again every minute");
  do {
    await wait(jitter(LOOK_AGAIN_MS), signal);
  } while (!signal?.aborted && !(await proxyAnswers()));
}

type PatientWait = (ms: number, signal?: AbortSignal) => Promise<void>;

function stopped(model: Model<Api>): AssistantMessage {
  return { ...failedMessage(model, "The run was stopped."), stopReason: "aborted" };
}
