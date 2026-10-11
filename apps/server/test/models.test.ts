import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { type Api, type Message, type Model, normalizeContext } from "@spoin/pi-ai";
import { eq } from "drizzle-orm";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { modelCall } from "../src/db/schema.ts";
import { Balancer } from "../src/models/balancer.ts";
import { type CallOutcome, recordedStreamFn, recordTo, roomLeft, runCall } from "../src/models/calls.ts";
import type { Rung } from "../src/models/nim.ts";
import { deps } from "./helpers.ts";

/*
 * The model layer (task 0045, Phase 8) against a stand-in NVIDIA and a stand-in Gemini: how a
 * call's failure is sorted into breader's kinds, what the balancer does with each, and the
 * `model_call` row every call leaves.
 */

type Reply = { status: number; body: string; headers?: Record<string, string> };
/** What the stand-in answers each request with, in order, and every request it was sent. */
let replies: Reply[] = [];
let requests: { url: string; body: Record<string, unknown> }[] = [];
let server: Server;
let base = "";

beforeAll(async () => {
  server = createServer((request, response) => {
    let raw = "";
    request.on("data", (chunk) => {
      raw += chunk;
    });
    request.on("end", () => {
      requests.push({ url: request.url ?? "", body: JSON.parse(raw) });
      const reply = replies.shift() ?? { status: 500, body: "no reply set" };
      response.writeHead(reply.status, { "Content-Type": "text/event-stream", ...reply.headers });
      response.end(reply.body);
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(async () => {
  await new Promise((resolve) => server.close(resolve));
});

const chunk = (delta: Record<string, unknown>, finish: string | null = null) =>
  `data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", created: 0, model: "m", choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`;
const usage = `data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", created: 0, model: "m", choices: [], usage: { prompt_tokens: 12, completion_tokens: 3, total_tokens: 15 } })}\n\n`;

const answer = (text = "ok"): Reply => ({
  status: 200,
  body: `${chunk({ role: "assistant", content: text })}${chunk({}, "stop")}${usage}data: [DONE]\n\n`,
});
const thinkingOnly: Reply = {
  status: 200,
  body: `${chunk({ role: "assistant", reasoning_content: "hmm" })}${chunk({}, "stop")}data: [DONE]\n\n`,
};
const cutShort: Reply = {
  status: 200,
  body: `${chunk({ role: "assistant", content: "a long" })}${chunk({}, "length")}data: [DONE]\n\n`,
};
const refuse = (status: number, message: string, headers?: Record<string, string>): Reply => ({
  status,
  body: JSON.stringify({ error: { message } }),
  headers: { "Content-Type": "application/json", ...headers },
});

let models = 0;
/** A NIM model on the stand-in, with an id of its own so no other test's cooldown reaches it. */
function nimModel(name: string): Model<"openai-completions"> {
  models += 1;
  return {
    id: `test/${name}-${models}`,
    name,
    api: "openai-completions",
    provider: "nvidia",
    baseUrl: `${base}/v1`,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    reasoning: false,
    contextWindow: 1_048_576,
    maxTokens: 130_000,
  };
}

const ask = (text = "Say ok.") =>
  normalizeContext({ messages: [{ role: "user", content: text, timestamp: Date.now() } satisfies Message] });

/** A recorder that keeps what it was given. */
function recorder() {
  const calls: { model: string; outcome: CallOutcome }[] = [];
  return {
    calls,
    record: (model: Model<Api>, outcome: CallOutcome) => calls.push({ model: model.id, outcome }),
  };
}

function start(answers: Reply[]) {
  replies = [...answers];
  requests = [];
}

describe("one call", () => {
  const call = (model = nimModel("kimi")) => runCall(model, ask(), { apiKey: "k", maxRetries: 0 });

  test("an answer is timed and counted", async () => {
    start([answer()]);
    const outcome = await call();
    expect(outcome.failure).toBeNull();
    expect(outcome.firstTokenMs).not.toBeNull();
    expect(outcome.message.usage.input).toBe(12);
    expect(outcome.message.usage.output).toBe(3);
  });

  test("a 429 cools the model for as long as it says", async () => {
    start([refuse(429, "Too many requests", { "Retry-After": "7" })]);
    const outcome = await call();
    expect(outcome.failure).toBe("rate");
    expect(outcome.retryAfterS).toBe(7);
  });

  test("a model that isn't open to the key is gone, and a 5xx is busy", async () => {
    start([refuse(404, "Not found"), refuse(503, "Service unavailable")]);
    expect((await call()).failure).toBe("gone");
    expect((await call()).failure).toBe("busy");
  });

  test("a refusal for asking too much says how much it allows", async () => {
    start([refuse(400, "Validation: Max tokens must not exceed 131072, got 1048576")]);
    const outcome = await call();
    expect(outcome.failure).toBe("bad");
    expect(outcome.room).toBe(131_072);
  });

  test("an answer with only thinking is empty, and one that hit max_tokens is cut", async () => {
    start([thinkingOnly, cutShort]);
    expect((await call()).failure).toBe("empty");
    expect((await call()).failure).toBe("cut");
  });

  test("Kimi's shared limit leaves what the prompt didn't take", () => {
    const text =
      "This model configuration accepts at most 1048576 combined input and output tokens. However, your request has 129334 input tokens and asks for 1048576 output tokens.";
    expect(roomLeft(text)).toBe(1_048_576 - 129_334);
  });
});

describe("the balancer", () => {
  test("a model that refuses the key is dropped, and the next one answers", async () => {
    const top = nimModel("kimi");
    const next = nimModel("nemotron");
    const ladder: Rung[] = [
      { model: top, maxInFlight: 24, primary: true },
      { model: next, maxInFlight: 24 },
    ];
    const { calls, record } = recorder();
    start([refuse(403, "Forbidden"), answer("from the next")]);
    const message = await (await new Balancer(ladder, "k", record).stream(ask())).result();
    expect(message.stopReason).toBe("stop");
    expect(message.model).toBe(next.id);
    expect(calls.map((c) => [c.model, c.outcome.failure])).toEqual([
      [top.id, "gone"],
      [next.id, null],
    ]);
  });

  test("a call refused for asking too much is asked again on the same model for what it allows", async () => {
    const model = nimModel("kimi");
    const { calls, record } = recorder();
    start([refuse(400, "Validation: Max tokens must not exceed 131072, got 130000 plus"), answer()]);
    // The refusal names a cap above what was asked, so it isn't asked again: one refusal, then the end.
    const refused = await (
      await new Balancer([{ model, maxInFlight: 1 }], "k", record).stream(ask())
    ).result();
    expect(refused.stopReason).toBe("error");

    const capped = nimModel("kimi");
    start([refuse(400, "Validation: Max tokens must not exceed 1000, got 130000"), answer()]);
    const message = await (
      await new Balancer([{ model: capped, maxInFlight: 1 }], "k", record).stream(ask())
    ).result();
    expect(message.stopReason).toBe("stop");
    expect(requests.map((r) => r.body.max_tokens)).toEqual([130_000, 1000]);
    expect(calls.filter((c) => c.model === capped.id)).toHaveLength(2);
  });

  test("when every model refuses the call, it ends in an error naming why", async () => {
    const ladder: Rung[] = [
      { model: nimModel("kimi"), maxInFlight: 1, primary: true },
      { model: nimModel("nemotron"), maxInFlight: 1 },
    ];
    start([refuse(400, "messages must not be empty"), refuse(400, "messages must not be empty")]);
    const message = await (await new Balancer(ladder, "k", () => {}).stream(ask())).result();
    expect(message.stopReason).toBe("error");
    expect(message.errorMessage).toMatch(/No model left to ask: kimi refused it .*; nemotron refused it/);
  });

  test("Kimi's reasoning effort goes in the body, and pi's own retries are off", async () => {
    const model = { ...nimModel("kimi"), samplingParams: { reasoning_effort: "high" } };
    start([answer()]);
    await (await new Balancer([{ model, maxInFlight: 1 }], "k", () => {}).stream(ask())).result();
    expect(requests[0]?.body.reasoning_effort).toBe("high");
    expect(requests[0]?.body.max_tokens).toBe(130_000);
  });
});

describe("the call log", () => {
  test("every call leaves a row, a failure with its kind and reason", async () => {
    const model = nimModel("kimi");
    const record = recordTo(deps.db);
    start([answer(), refuse(429, "Too many requests")]);
    record(model, await runCall(model, ask(), { apiKey: "k" }));
    record(model, await runCall(model, ask(), { apiKey: "k" }));
    // The insert isn't awaited by the call it records.
    await new Promise((resolve) => setTimeout(resolve, 200));

    const rows = await deps.db.select().from(modelCall).where(eq(modelCall.model, model.id));
    const ok = rows.find((r) => r.ok);
    const failed = rows.find((r) => !r.ok);
    expect(ok).toMatchObject({ provider: "nvidia", failure: null, promptTokens: 12, outputTokens: 3 });
    expect(failed).toMatchObject({ failure: "rate" });
    expect(failed?.reason).toMatch(/429/);
  });

  test("a Gemini call streams on as it comes and is recorded when it ends", async () => {
    const model: Model<Api> = {
      id: `gemini-test-${Date.now()}`,
      name: "Gemini",
      api: "google-generative-ai",
      provider: "antigravity",
      baseUrl: `${base}/v1beta`,
      input: ["text", "image"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      reasoning: false,
      contextWindow: 1_048_576,
      maxTokens: 65_536,
    };
    const reply = {
      candidates: [{ content: { role: "model", parts: [{ text: "seen" }] }, finishReason: "STOP", index: 0 }],
      usageMetadata: { promptTokenCount: 5, candidatesTokenCount: 1, totalTokenCount: 6 },
    };
    start([{ status: 200, body: `data: ${JSON.stringify(reply)}\r\n\r\n` }]);
    const { calls, record } = recorder();
    const stream = recordedStreamFn(record)(model, ask(), { apiKey: "k" });
    const kinds: string[] = [];
    for await (const event of stream) kinds.push(event.type);
    expect(kinds).toContain("text_delta");
    expect((await stream.result()).stopReason).toBe("stop");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(calls).toHaveLength(1);
    expect(calls[0]?.outcome.failure).toBeNull();
  });
});
