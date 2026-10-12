import type { StreamFn } from "@spoin/pi-agent";
import { type AssistantMessageEvent, createAssistantMessageEventStream } from "@spoin/pi-ai";
import { log } from "../log.ts";
import type { Balancer } from "./balancer.ts";
import { endWith, failedMessage, type RecordCall, runCall } from "./calls.ts";

/*
 * pi's stream function for a chat a reader waits on, AskAI's (task 0045, "Grading and AskAI run on
 * Gemini, then NIM"): Gemini through CLIProxyAPI, streamed on as it comes, and when Gemini fails
 * before it has started its answer, the same call on NIM through the balancer. Its thinking is held
 * back until the answer starts, since the reader never sees it. A call that fails once its answer
 * has started ends in its error: what the reader has seen can't be taken back.
 */

export interface GeminiThenNimOptions {
  /** Null when this process has no proxy key: every call goes to NIM. */
  gemini: { apiKey: string } | null;
  /** Null when this process has no NIM key. */
  nim: Balancer | null;
  /** Writes each Gemini call's `model_call` row; the balancer writes NIM's. */
  record: RecordCall;
}

/** The events of the answer itself, as against its start and its thinking. */
const ANSWERING = /^(text|toolcall)_/;

export function geminiThenNim({ gemini, nim, record }: GeminiThenNimOptions): StreamFn {
  return (model, context, options = {}) => {
    const stream = createAssistantMessageEventStream();
    const call = async () => {
      if (gemini) {
        const held: AssistantMessageEvent[] = [];
        let answering = false;
        const outcome = await runCall(
          model,
          context,
          // CLIProxyAPI retries across the accounts itself.
          { ...options, apiKey: gemini.apiKey, maxRetries: 0 },
          (event) => {
            if (event.type === "done" || event.type === "error") return;
            if (!answering && ANSWERING.test(event.type)) {
              answering = true;
              for (const waiting of held.splice(0)) stream.push(waiting);
            }
            if (answering) stream.push(event);
            else held.push(event);
          },
        );
        record(model, outcome);
        if (!outcome.failure || answering || !nim) return outcome.message;
        log.warn(
          { model: model.id, failure: outcome.failure, reason: outcome.reason },
          "Gemini failed, so NIM answers",
        );
      }
      if (!nim) return failedMessage(model, "No model is set up to answer.");
      return (await nim.stream(context, options)).result();
    };
    void call().then(
      (message) => endWith(stream, message),
      (error: unknown) => {
        log.error({ err: error, model: model.id }, "a reader's call failed outside pi");
        endWith(stream, failedMessage(model, "The call failed before the model answered."));
      },
    );
    return stream;
  };
}
