import type { StreamFn } from "@spoin/pi-agent";
import { type Api, createAssistantMessageEventStream, type Model } from "@spoin/pi-ai";
import { log } from "../log.ts";
import type { Balancer } from "./balancer.ts";
import { endWith, failedMessage } from "./calls.ts";

/*
 * pi's stream function for a writer (task 0045, "NIM writes, Gemini orchestrates and verifies"):
 * every call goes to NIM through the balancer, and only when NIM gives up on it (its tries spent,
 * no model left to ask, or none free within its patience on a bad day) does the same call go to
 * Gemini. The balancer buffers each call until it ends, so nothing of NIM's failure reached the
 * chat, and Gemini answers it whole.
 */

export interface NimThenGeminiOptions {
  nim: Balancer;
  /** Gemini, loaded only when a call falls back to it. */
  geminiModel: () => Promise<Model<Api>>;
  /** Gemini's stream function, which waits out Gemini's limits and records its calls. */
  gemini: StreamFn;
  /** The proxy's key: the chat's own key is NIM's. */
  geminiApiKey: string;
}

export function nimThenGemini({ nim, geminiModel, gemini, geminiApiKey }: NimThenGeminiOptions): StreamFn {
  return (model, context, options = {}) => {
    const stream = createAssistantMessageEventStream();
    const call = async () => {
      const answered = await (await nim.stream(context, options)).result();
      // A call stopped by its run (a worker stop, say) isn't NIM failing: it isn't asked again.
      if (answered.stopReason !== "error") return answered;
      log.warn({ reason: answered.errorMessage }, "NIM gave up on a call, so Gemini answers");
      const fallback = await geminiModel();
      return (await gemini(fallback, context, { ...options, apiKey: geminiApiKey })).result();
    };
    void call().then(
      (message) => endWith(stream, message),
      (error: unknown) => {
        log.error({ err: error, model: model.id }, "a writer's call failed outside pi");
        endWith(stream, failedMessage(model, "The call failed before a model answered."));
      },
    );
    return stream;
  };
}
