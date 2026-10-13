import { chromiumBrowser } from "./agents/browser.ts";
import { filesUnder } from "./agents/context.ts";
import { oneShot } from "./agents/one-shot.ts";
import { agentSetUp } from "./agents/set-up.ts";
import { connectApp, connectUniverse } from "./db/client.ts";
import { makeEmbedder } from "./deps.ts";
import { loadEnv } from "./env.ts";
import { markInterruptedRuns } from "./harness/chats.ts";
import { patientGemini } from "./harness/gemini.ts";
import { runScheduler } from "./harness/scheduler.ts";
import { releaseTakenWakes } from "./harness/wakes.ts";
import { log } from "./log.ts";
import { recordTo } from "./models/calls.ts";
import { geminiOpensAt } from "./models/limits.ts";
import { geminiFrom, proxyAnswers, proxyConfig } from "./models/proxy.ts";
import { loadPrompts } from "./prompts.ts";

/*
 * The worker (task 0045): runs the authoring harness's scheduler, which wakes every chat but
 * AskAI's. A run or wake still going when it last stopped was cut off with it, so it ends those
 * runs and puts those wakes back before it starts.
 */

/**
 * How long a stop waits for the chats running to finish the step they are in, so no model output
 * already paid for is lost. A chat still running past it is waiting out Gemini's limits, with
 * nothing in flight, and is cut off. The worker's compose `stop_grace_period` is longer.
 */
const DRAIN_MS = 4 * 60_000;

const env = loadEnv();
const proxy = proxyConfig(env);
if (!proxy) throw new Error("The worker needs Gemini: set CLIPROXY_API_KEY.");
// The writers run on NIM (the owner's rule), Gemini only taking a call NIM gave up on, so no key, no worker.
if (!env.NVIDIA_NIM_API_KEY)
  throw new Error("The worker's writers run on NVIDIA NIM: set NVIDIA_NIM_API_KEY.");
if (!env.UNIVERSE_DATABASE_URL) throw new Error("The worker writes the corpus: set UNIVERSE_DATABASE_URL.");

const app = connectApp(env.DATABASE_URL);
const universe = connectUniverse(env.UNIVERSE_DATABASE_URL, { readOnly: false });
const prompts = loadPrompts();
const gemini = geminiFrom(proxy);
const browser = chromiumBrowser(env.WEB_URL ?? null);

const deps = {
  db: app.db,
  universe: universe.db,
  embedder: makeEmbedder(env),
  prompts,
  files: filesUnder(env.UNIVERSE_FILES_DIR),
  minCardsFraction: env.MIN_CARDS_FRACTION,
  webSearch: { proxy, model: gemini },
  oneShot: oneShot({
    model: gemini,
    apiKey: proxy.apiKey,
    streamFn: (runId) =>
      patientGemini({
        record: recordTo(app.db, runId),
        opensAt: () => geminiOpensAt(proxy),
        proxyAnswers: () => proxyAnswers(proxy),
      }),
  }),
  browser,
};

const interrupted = await markInterruptedRuns(app.db);
const released = await releaseTakenWakes(app.db);
log.info({ interrupted: interrupted.length, released: released.length }, "worker starting");

const draining = new AbortController();
const stopping = new AbortController();
const stop = () => {
  if (draining.signal.aborted) return;
  log.info("worker stopping: each chat running ends once the step it is in is stored");
  draining.abort();
  setTimeout(() => stopping.abort(), DRAIN_MS).unref();
  setTimeout(() => process.exit(0), DRAIN_MS + 30_000).unref();
};
process.on("SIGTERM", stop);
process.on("SIGINT", stop);

await runScheduler({
  db: app.db,
  prompts,
  setUp: agentSetUp({ deps, proxy, nimKey: env.NVIDIA_NIM_API_KEY }),
  signal: stopping.signal,
  drain: draining.signal,
  onEvent(event) {
    if (event.type === "error") {
      log.error({ error: event.error }, "the scheduler hit an error");
      return;
    }
    const chat = {
      id: event.chat.id,
      role: event.chat.role,
      task: event.chat.task,
      topic: event.chat.topicId,
    };
    if (event.type === "woke") {
      log.info({ chat, wakes: event.wakes.length }, "chat woke");
      return;
    }
    log.info({ chat, outcome: event.outcome, runs: event.runs.length }, "chat settled");
  },
});

await Promise.all([app.pool.end(), universe.pool.end()]);
process.exit(0);
