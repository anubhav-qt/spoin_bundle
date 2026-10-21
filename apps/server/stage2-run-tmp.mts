/*
 * Stage 2 rerun (2026-10-14, the owner's stage review, never committed): the real scheduler, chats,
 * prompts and tools on a scratch database holding only the three topics and their intakes, so the
 * live database is never touched. Only toad_sage, the tadpoles and their helpers wake. It stops a
 * tadpole at its documents, and stops itself once every topic's maps have a go-on review.
 *
 * Run from apps/server: GEMINI_THINKING=low STAGE2_DIR=<scratch> STAGE2_DB=<db> STAGE2_UNIVERSE_DB=<db>
 * [STAGE2_REQUEST=<name>] [STAGE2_MODELS=<dir>] npx tsx stage2-run-tmp.mts. A request is queued as a
 * user's would be when the database has no topic yet, so toad_sage's intake runs too.
 */
import { readFileSync } from "node:fs";
import { sql } from "drizzle-orm";
import { chromiumBrowser } from "./src/agents/browser.ts";
import { filesUnder } from "./src/agents/context.ts";
import { oneShot } from "./src/agents/one-shot.ts";
import { agentSetUp } from "./src/agents/set-up.ts";
import { connectApp, connectUniverse } from "./src/db/client.ts";
import { harnessRecord, topic } from "./src/db/schema.ts";
import { resolve } from "./src/topics/request.ts";
import { makeEmbedder } from "./src/deps.ts";
import { loadEnv } from "./src/env.ts";
import { type Chat, markInterruptedRuns } from "./src/harness/chats.ts";
import { patientGemini } from "./src/harness/gemini.ts";
import { runScheduler } from "./src/harness/scheduler.ts";
import { ToolError } from "./src/harness/tools.ts";
import { releaseTakenWakes } from "./src/harness/wakes.ts";
import { BALANCER_DEFAULTS, Balancer } from "./src/models/balancer.ts";
import { letCallsWait, recordTo } from "./src/models/calls.ts";
import { geminiOpensAt } from "./src/models/limits.ts";
import { NIM_LADDER } from "./src/models/nim.ts";
import { nimThenGemini } from "./src/models/nim-then-gemini.ts";
import { GEMINI_THINKING, geminiFrom, proxyAnswers, proxyConfig, waitForModel } from "./src/models/proxy.ts";
import { loadPrompts } from "./src/prompts.ts";

const dir = process.env.STAGE2_DIR;
if (!dir) throw new Error("STAGE2_DIR");
const fromFile = Object.fromEntries(
  readFileSync("../../infra/.env", "utf8")
    .split("\n")
    .filter((line) => line.includes("=") && !line.trim().startsWith("#"))
    .map((line) => {
      const at = line.indexOf("=");
      return [line.slice(0, at).trim(), line.slice(at + 1).trim().replace(/^"|"$/g, "")];
    }),
);
const env = loadEnv({
  ...process.env,
  CLIPROXY_API_KEY: fromFile.CLIPROXY_API_KEY,
  CLIPROXY_MANAGEMENT_KEY: fromFile.CLIPROXY_MANAGEMENT_KEY,
  NVIDIA_NIM_API_KEY: fromFile.NVIDIA_NIM_API_KEY,
  DATABASE_URL: `postgres://spoin:spoin@localhost:5434/${process.env.STAGE2_DB ?? "spoin_stage2"}`,
  UNIVERSE_DATABASE_URL: `postgres://spoin:spoin@localhost:5434/${process.env.STAGE2_UNIVERSE_DB ?? "spoin_universe_stage2"}`,
  AUTH_SECRET: "stage-two-review-scratch-secret-0123456789",
  CLIPROXY_URL: "http://127.0.0.1:8319",
  EMBEDDER: "qwen3",
  MODEL_CACHE_DIR: process.env.STAGE2_MODELS ?? `${dir}/models`,
  UNIVERSE_FILES_DIR: `${dir}/files`,
});
const say = (what: Record<string, unknown>) =>
  console.log(JSON.stringify({ at: new Date().toISOString(), ...what }));
say({ event: "start", thinking: GEMINI_THINKING });

const proxy = proxyConfig(env);
if (!proxy) throw new Error("No proxy.");
const nimKey = env.NVIDIA_NIM_API_KEY;
if (!nimKey) throw new Error("No NIM key.");
const [nimTop] = NIM_LADDER;
if (!nimTop) throw new Error("No NIM ladder.");
letCallsWait();
// The worker's pool (worker.ts): a chat's queries wait out a busy pool rather than fail.
const app = connectApp(env.DATABASE_URL, 20, 60_000);
const universe = connectUniverse(env.UNIVERSE_DATABASE_URL ?? "", { readOnly: false });
const prompts = loadPrompts();
const gemini = geminiFrom(proxy);
const waitingOutGemini = (runId: string) =>
  patientGemini({
    record: recordTo(app.db, runId),
    opensAt: () => geminiOpensAt(proxy),
    proxyAnswers: () => proxyAnswers(proxy),
  });
const deps = {
  db: app.db,
  universe: universe.db,
  embedder: makeEmbedder(env),
  prompts,
  files: filesUnder(env.UNIVERSE_FILES_DIR),
  minCardsFraction: env.MIN_CARDS_FRACTION,
  webSearch: { proxy, model: gemini },
  oneShot: oneShot({ model: gemini, apiKey: proxy.apiKey, streamFn: waitingOutGemini }),
  nim: {
    model: nimTop.model,
    apiKey: nimKey,
    streamFn: (runId: string) =>
      nimThenGemini({
        nim: new Balancer(NIM_LADDER, nimKey, recordTo(app.db, runId), { ...BALANCER_DEFAULTS, patient: true }),
        geminiModel: gemini,
        gemini: waitingOutGemini(runId),
        geminiApiKey: proxy.apiKey,
      }),
  },
  browser: chromiumBrowser(null),
};

await markInterruptedRuns(app.db);
await releaseTakenWakes(app.db);
const draining = new AbortController();
const stopping = new AbortController();
await waitForModel(gemini, draining.signal, () => say({ event: "waiting for gemini" }));

// The stage under review ends at the maps' review: a tadpole told go on is stopped at its documents.
const base = agentSetUp({ deps, proxy });
const setUp = async (chat: Chat) => {
  const set = await base(chat);
  if (chat.role !== "tadpole") return set;
  const tools = set.tools.map((tool) => {
    if (tool.name !== "start_writer") return tool;
    return {
      ...tool,
      execute: async () => {
        throw new ToolError("This run of the harness stops at the maps: no documents are written yet. End your turn.");
      },
    };
  });
  return { ...set, tools };
};

// A rerun on a database that already passed its maps counts only reviews written after STAGE2_AFTER_SEQ.
const afterSeq = Number(process.env.STAGE2_AFTER_SEQ ?? "0");

/** Topics whose maps toad_sage said go on to. */
async function topicsPassed(): Promise<string[]> {
  const rows = await app.db.execute(sql`
    SELECT h.body ->> 'topic' AS topic FROM ${harnessRecord} r
    JOIN ${harnessRecord} h ON h.id::text = r.body -> 'handover' ->> 'id' AND h.kind = 'handover'
    WHERE r.kind = 'review' AND r.body ->> 'verdict' = 'go_on' AND h.body ->> 'kind' = 'maps'
      AND r.seq > ${afterSeq}`);
  return rows.rows.map((row) => String(row.topic));
}

const request = process.env.STAGE2_REQUEST;
const before = await app.db.select({ id: topic.id }).from(topic);
if (request && before.length === 0) {
  const made = await app.db.transaction((tx) =>
    resolve(tx, request, "", { priority: 10, decidedBy: "request" }),
  );
  say({ event: "requested", name: request, topic: made.topic.id });
}
const all = (await app.db.select({ id: topic.id }).from(topic)).map((row) => row.id);
const deadline = Date.now() + 6 * 60 * 60 * 1000;
const watcher = setInterval(async () => {
  try {
    const passed = await topicsPassed();
    if (passed.length >= all.length || Date.now() > deadline) {
      say({ event: "stopping", passed: passed.length });
      draining.abort();
      setTimeout(() => stopping.abort(), 5 * 60 * 1000).unref();
    }
  } catch (error) {
    say({ event: "watch failed", error: String(error) });
  }
}, 60_000);

await runScheduler({
  db: app.db,
  prompts,
  setUp,
  signal: stopping.signal,
  drain: draining.signal,
  onlyRoles: ["toad_sage", "tadpole", "helper"],
  onEvent(event) {
    if (event.type === "error") {
      say({ event: "error", error: event.error });
      return;
    }
    const chat = { id: event.chat.id, role: event.chat.role, task: event.chat.task, topic: event.chat.topicId };
    if (event.type === "woke") say({ event: "woke", chat, wakes: event.wakes.length });
    else say({ event: "settled", chat, outcome: event.outcome, runs: event.runs.length });
  },
});
clearInterval(watcher);
await Promise.all([app.pool.end(), universe.pool.end()]);
say({ event: "done" });
process.exit(0);
