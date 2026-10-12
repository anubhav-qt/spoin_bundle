import type { StreamFn } from "@spoin/pi-agent";
import {
  type Api,
  type AssistantMessage,
  type AssistantMessageEventStream,
  createAssistantMessageEventStream,
  type Message,
  type Model,
  type StopReason,
} from "@spoin/pi-ai";

/** A stand-in for a harness chat's model (Trotter's `scripted-model.ts`), so tests never touch the network. */

export const TEST_MODEL: Model<Api> = {
  id: "test-model",
  name: "Test model",
  api: "openai-completions",
  provider: "test",
  baseUrl: "http://127.0.0.1:1",
  input: ["text"],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  reasoning: false,
  contextWindow: 1_000_000,
  maxTokens: 10_000,
};

export function reply(
  content: AssistantMessage["content"],
  stopReason: StopReason = "stop",
  errorMessage?: string,
): AssistantMessage {
  return {
    role: "assistant",
    content,
    api: TEST_MODEL.api,
    provider: TEST_MODEL.provider,
    model: TEST_MODEL.id,
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason,
    ...(errorMessage === undefined ? {} : { errorMessage }),
    timestamp: Date.now(),
  };
}

/** An answer the provider counted at `totalTokens`: the chat's context as of that answer. */
export function counted(message: AssistantMessage, totalTokens: number): AssistantMessage {
  return { ...message, usage: { ...message.usage, totalTokens } };
}

export function streamOf(message: AssistantMessage): AssistantMessageEventStream {
  const stream = createAssistantMessageEventStream();
  stream.push({ type: "start", partial: message });
  const reason = message.stopReason;
  if (reason === "pending") throw new Error("A scripted reply has to be finished, not pending.");
  if (reason === "error" || reason === "aborted") {
    stream.push({ type: "error", reason, error: message });
  } else {
    stream.push({ type: "done", reason, message });
  }
  return stream;
}

/** Answers each request with the next reply in the script, and keeps the messages each request was sent. */
export function scriptedModel(replies: AssistantMessage[]): { streamFn: StreamFn; requests: Message[][] } {
  const requests: Message[][] = [];
  const streamFn: StreamFn = (_model, context) => {
    requests.push([...context.messages]);
    const next = replies[requests.length - 1] ?? reply([], "error", "The script has no more replies.");
    // A provider's answer is dated when it comes back; pi trusts its token count only for what came before.
    return streamOf({ ...next, timestamp: Date.now() });
  };
  return { streamFn, requests };
}
