import { type Api, type AssistantMessage, type Model, normalizeContext } from "@spoin/pi-ai";
import { and, eq } from "drizzle-orm";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { modelCall } from "../src/db/schema.ts";
import { openChat, startRun } from "../src/harness/chats.ts";
import { type PatientGeminiOptions, patientGemini } from "../src/harness/gemini.ts";
import { type CallOutcome, recordTo } from "../src/models/calls.ts";
import { geminiOpensAt, geminiWindows, opensAt } from "../src/models/limits.ts";
import { deps } from "./helpers.ts";
import { modelStandIn, type Reply } from "./model-stand-in.ts";

/*
 * How a harness run waits Gemini out on Flash (task 0045, Phase 9), against a stand-in Gemini:
 * breader's cooldowns, the wait for an account's limit to fill, the proxy looked for every minute,
 * and the failures waiting can't fix. Waits are instant: the clock jumps by each one.
 */

const standIn = modelStandIn();
beforeAll(standIn.listen);
afterAll(standIn.close);
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
});
afterEach(() => {
  vi.useRealTimers();
});

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
let models = 0;

/** A Gemini of its own for each test, so no other test's cooldown reaches it. */
function gemini(): Model<Api> {
  models += 1;
  return {
    id: `gemini-patient-${models}`,
    name: "Gemini",
    api: "google-generative-ai",
    provider: "antigravity",
    baseUrl: `${standIn.base}/v1beta`,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    reasoning: false,
    contextWindow: 1_048_576,
    maxTokens: 65_536,
  };
}

const says = (text: string): Reply => {
  const reply = {
    candidates: [{ content: { role: "model", parts: [{ text }] }, finishReason: "STOP", index: 0 }],
    usageMetadata: { promptTokenCount: 5, candidatesTokenCount: 1, totalTokenCount: 6 },
  };
  return { status: 200, body: `data: ${JSON.stringify(reply)}\r\n\r\n` };
};

/** A refusal as Google words it: the status is in the body, which is all the SDK passes on. */
const refuse = (code: number, message: string): Reply => ({
  status: code,
  body: JSON.stringify({ error: { code, message, status: "REFUSED" } }),
  headers: { "Content-Type": "application/json" },
});

const textOf = (message: AssistantMessage) =>
  message.content.map((block) => (block.type === "text" ? block.text : "")).join("");

function patient(options: Partial<PatientGeminiOptions> & { onWait?: () => void } = {}) {
  const outcomes: CallOutcome[] = [];
  const waits: number[] = [];
  const streamFn = patientGemini({
    record: options.record ?? ((_model, outcome) => outcomes.push(outcome)),
    opensAt: options.opensAt ?? (async () => null),
    proxyAnswers: options.proxyAnswers ?? (async () => true),
    sleep: async (ms) => {
      waits.push(ms);
      // Date counts whole milliseconds, as a real timer waits at least one.
      vi.setSystemTime(Date.now() + Math.max(1, Math.ceil(ms)));
      options.onWait?.();
    },
  });
  const ask = async (model = gemini(), signal?: AbortSignal) => {
    const context = normalizeContext({
      messages: [{ role: "user", content: "Hello", timestamp: Date.now() }],
    });
    return (await streamFn(model, context, { apiKey: "k", signal })).result();
  };
  return { ask, outcomes, waits };
}

const total = (waits: number[]) => waits.reduce((sum, ms) => sum + ms, 0);

describe("a harness call on Gemini", () => {
  test("cools Flash when it's busy and makes the same call again, the wait doubling", async () => {
    standIn.start([
      refuse(503, "The model is overloaded."),
      refuse(503, "Still overloaded."),
      says("Hello."),
    ]);
    const { ask, outcomes, waits } = patient();

    const message = await ask();

    expect(textOf(message)).toBe("Hello.");
    expect(outcomes.map((outcome) => outcome.failure)).toEqual(["busy", "busy", null]);
    // 30 s, then 60 s, each with jitter of half to one and a half times.
    expect(total(waits)).toBeGreaterThanOrEqual(45_000);
    expect(total(waits)).toBeLessThanOrEqual(135_000);
  });

  test("waits for the first account to fill when every account is out of its limit, without cooling", async () => {
    standIn.start([refuse(429, "RESOURCE_EXHAUSTED: You have exhausted your capacity."), says("Back.")]);
    const fills = Date.now() + 3 * HOUR;
    const { ask, outcomes, waits } = patient({ opensAt: async () => fills });

    const message = await ask();

    expect(textOf(message)).toBe("Back.");
    expect(outcomes.map((outcome) => outcome.failure)).toEqual(["rate", null]);
    expect(waits).toHaveLength(1);
    expect(waits[0]).toBeGreaterThanOrEqual(3 * HOUR);
    expect(waits[0]).toBeLessThanOrEqual(3 * HOUR + 1.5 * MINUTE);
  });

  test("cools Flash for a limit while an account still has some left, or when the limits can't be read", async () => {
    standIn.start([refuse(429, "Too many requests."), refuse(429, "Too many requests."), says("Hello.")]);
    let asked = 0;
    const { ask, waits } = patient({
      opensAt: async () => {
        asked += 1;
        if (asked === 1) return Date.now();
        throw new Error("CLIProxyAPI isn't answering.");
      },
    });

    expect(textOf(await ask())).toBe("Hello.");
    // 60 s, then 120 s, with jitter.
    expect(total(waits)).toBeGreaterThanOrEqual(90_000);
  });

  test("takes a quota for a limit however it's worded", async () => {
    standIn.start([
      refuse(403, "Quota exceeded for quota metric 'Generate Content API requests'."),
      says("Hi."),
    ]);
    const { ask, outcomes } = patient();

    expect(textOf(await ask())).toBe("Hi.");
    expect(outcomes[0]?.failure).toBe("rate");
  });

  test("looks for the proxy every minute while it's down, then makes the call again", async () => {
    standIn.start([refuse(502, "Bad gateway."), says("Hello again.")]);
    const answers = [false, false, true];
    const { ask, outcomes, waits } = patient({ proxyAnswers: async () => answers.shift() ?? true });

    expect(textOf(await ask())).toBe("Hello again.");
    expect(outcomes.map((outcome) => outcome.failure)).toEqual(["busy", null]);
    expect(waits).toHaveLength(2);
    for (const wait of waits) {
      expect(wait).toBeGreaterThanOrEqual(30_000);
      expect(wait).toBeLessThanOrEqual(90_000);
    }
  });

  test("ends on a sign-in turned away, saying where to look", async () => {
    standIn.start([refuse(401, "Request had invalid authentication credentials.")]);
    const { ask, waits } = patient();

    const message = await ask();

    expect(message.stopReason).toBe("error");
    expect(message.errorMessage).toMatch(/turned the call away .*admin page's model accounts/);
    expect(standIn.requests).toHaveLength(1);
    expect(waits).toEqual([]);
  });

  test("ends on a request Gemini refuses, since waiting can't fix it", async () => {
    standIn.start([refuse(400, "Invalid JSON payload received.")]);
    const { ask } = patient();

    const message = await ask();

    expect(message.stopReason).toBe("error");
    expect(standIn.requests).toHaveLength(1);
  });

  test("ends stopped when its run is stopped during a wait", async () => {
    standIn.start([refuse(429, "RESOURCE_EXHAUSTED"), says("Never sent.")]);
    const controller = new AbortController();
    const { ask } = patient({ opensAt: async () => Date.now() + HOUR, onWait: () => controller.abort() });

    const message = await ask(gemini(), controller.signal);

    expect(message.stopReason).toBe("aborted");
    expect(standIn.requests).toHaveLength(1);
  });

  test("records every try against its run", async () => {
    const chat = await openChat(deps.db, "wise_toad");
    const run = await startRun(deps.db, {
      chatId: chat.id,
      model: "gemini",
      systemPrompt: "s",
      triggers: [{ kind: "schedule", schedule: "test" }],
    });
    standIn.start([refuse(503, "Overloaded."), says("Hello.")]);
    const model = gemini();
    const { ask } = patient({ record: recordTo(deps.db, run.id) });

    await ask(model);

    await vi.waitFor(async () => {
      const rows = await deps.db
        .select({ ok: modelCall.ok, failure: modelCall.failure })
        .from(modelCall)
        .where(and(eq(modelCall.runId, run.id), eq(modelCall.model, model.id)));
      expect(rows.map((row) => row.failure).sort()).toEqual(["busy", null]);
    });
  });
});

describe("Antigravity's limits", () => {
  const summary = (buckets: object[]) => JSON.stringify({ groups: [{ buckets }] });
  const at = (iso: string) => Date.parse(iso);

  test("are read from the Gemini group only", () => {
    const text = JSON.stringify({
      groups: [
        {
          buckets: [
            {
              bucketId: "gemini-5h",
              window: "5h",
              remainingFraction: 0.25,
              resetTime: "2026-10-13T05:00:00Z",
            },
            {
              bucketId: "gemini-weekly",
              window: "weekly",
              remainingFraction: "0.9",
              resetTime: "2026-10-18T00:00:00Z",
            },
          ],
        },
        {
          buckets: [
            { bucketId: "3p-5h", window: "5h", remainingFraction: 0, resetTime: "2026-10-13T06:00:00Z" },
          ],
        },
      ],
    });
    expect(geminiWindows(text)).toEqual([
      { window: "5h", usedPercent: 75, resetsAt: "2026-10-13T05:00:00Z" },
      { window: "weekly", usedPercent: 10, resetsAt: "2026-10-18T00:00:00Z" },
    ]);
    expect(geminiWindows("not json")).toBeNull();
    expect(geminiWindows(summary([]))).toBeNull();
  });

  test("open an account when the last of its used-up limits fills", () => {
    const now = at("2026-10-13T00:00:00Z");
    const open = { window: "5h", usedPercent: 40, resetsAt: "2026-10-13T05:00:00Z" };
    const fiveHours = { window: "5h", usedPercent: 100, resetsAt: "2026-10-13T05:00:00Z" };
    const weekly = { window: "weekly", usedPercent: 100, resetsAt: "2026-10-15T00:00:00Z" };
    expect(opensAt([open], now)).toBe(now);
    expect(opensAt([fiveHours, weekly], now)).toBe(at("2026-10-15T00:00:00Z"));
    expect(opensAt([{ ...fiveHours, resetsAt: null }], now)).toBeNull();
  });

  test("say the soonest an account opens, asking Google through the proxy's api-call", async () => {
    const now = at("2026-10-13T00:00:00Z");
    const accounts = [
      { provider: "antigravity", auth_index: "a", project_id: "p-a" },
      { provider: "antigravity", auth_index: "b", project_id: "p-b" },
      { provider: "antigravity", auth_index: "c", project_id: "p-c", disabled: true },
      { provider: "codex", auth_index: "d" },
    ];
    const quota: Record<string, string> = {
      a: summary([
        { bucketId: "gemini-5h", window: "5h", remainingFraction: 0, resetTime: "2026-10-13T04:00:00Z" },
      ]),
      b: summary([
        { bucketId: "gemini-5h", window: "5h", remainingFraction: 0, resetTime: "2026-10-13T02:00:00Z" },
      ]),
    };
    const asked: unknown[] = [];
    const fetchFn = (async (url: string, init?: RequestInit) => {
      if (url.endsWith("/v8/management/credentials")) return Response.json({ files: accounts });
      const request = JSON.parse(String(init?.body)) as { auth_index: string; data: string };
      asked.push(request);
      return Response.json({ status_code: 200, body: quota[request.auth_index] });
    }) as typeof fetch;
    const config = { url: "http://proxy", apiKey: "k", managementKey: "m" };

    expect(await geminiOpensAt(config, fetchFn, () => now)).toBe(at("2026-10-13T02:00:00Z"));
    expect(asked).toHaveLength(2);
    expect(asked[0]).toMatchObject({
      auth_index: "a",
      method: "POST",
      header: { Authorization: "Bearer $TOKEN$" },
      data: JSON.stringify({ project: "p-a" }),
    });
  });
});
