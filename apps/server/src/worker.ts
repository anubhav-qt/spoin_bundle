import type { ChatRole } from "@spoin/shared/enums";
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
import { BALANCER_DEFAULTS, Balancer } from "./models/balancer.ts";
import { letCallsWait, recordTo } from "./models/calls.ts";
import { geminiOpensAt } from "./models/limits.ts";
import { NIM_LADDER } from "./models/nim.ts";
import { nimThenGemini } from "./models/nim-then-gemini.ts";
import { geminiFrom, proxyAnswers, proxyConfig } from "./models/proxy.ts";
import { loadPrompts } from "./prompts.ts";

/*
 * The worker (task 0045): runs the authoring harness's scheduler, which wakes every chat but
 * AskAI's. A run or wake still going when it last stopped was cut off with it, so it ends those
 * runs and puts those wakes back before it starts.
 */

/** How long a big write goes without an answer from NIM before Gemini takes it: a bad day on NIM. */
const NIM_PATIENCE_S = 30 * 60;

/**
 * How long a stop waits for the chats running to finish the step they are in, so no model output
 * already paid for is lost: a NIM write's whole patience and a minute more, since a write runs up
 * to it (4 minutes cut 19 writes in flight). A chat still running past it is waiting out Gemini's
 * limits, with nothing in flight, and is cut off. The worker's compose `stop_grace_period` is longer.
 */
const DRAIN_MS = (NIM_PATIENCE_S + 60) * 1000;

const env = loadEnv();
const proxy = proxyConfig(env);
if (!proxy) throw new Error("The worker needs Gemini: set CLIPROXY_API_KEY.");
letCallsWait();
// The big writes run on NIM (the owner's rule), Gemini only taking a call NIM gave up on, so no key, no worker.
const nimKey = env.NVIDIA_NIM_API_KEY;
if (!nimKey) throw new Error("The writers' big writes run on NVIDIA NIM: set NVIDIA_NIM_API_KEY.");
const [nimTop] = NIM_LADDER;
if (!nimTop) throw new Error("NIM's ladder is empty.");
if (!env.UNIVERSE_DATABASE_URL) throw new Error("The worker writes the corpus: set UNIVERSE_DATABASE_URL.");

const app = connectApp(env.DATABASE_URL);
const universe = connectUniverse(env.UNIVERSE_DATABASE_URL, { readOnly: false });
const prompts = loadPrompts();
const gemini = geminiFrom(proxy);
const browser = chromiumBrowser(env.WEB_URL ?? null);

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
  oneShot: oneShot({
    model: gemini,
    apiKey: proxy.apiKey,
    streamFn: waitingOutGemini,
  }),
  nim: {
    // The ladder picks the model for each try; this one names the call.
    model: nimTop.model,
    apiKey: nimKey,
    streamFn: (runId: string) =>
      nimThenGemini({
        // The worker never ends, so a model that refuses the key is asked again later.
        nim: new Balancer(NIM_LADDER, nimKey, recordTo(app.db, runId), {
          ...BALANCER_DEFAULTS,
          patient: true,
          giveUpAfterS: NIM_PATIENCE_S,
        }),
        geminiModel: gemini,
        gemini: waitingOutGemini(runId),
        geminiApiKey: proxy.apiKey,
      }),
  },
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

let onlyRoles: ChatRole[] | undefined;
if (env.WORKER_ONLY_ROLES.length > 0) {
  onlyRoles = env.WORKER_ONLY_ROLES;
  log.warn({ onlyRoles }, "waking only these roles; every other chat's wakes wait");
}

await runScheduler({
  db: app.db,
  prompts,
  setUp: agentSetUp({ deps, proxy }),
  signal: stopping.signal,
  drain: draining.signal,
  onlyRoles,
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
