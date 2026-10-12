import { type Embedder, HashEmbedder, Qwen3OnnxEmbedder } from "@spoin/frog/embeddings";
import { type AskChat, noAskChat } from "./ask/chat.ts";
import { harnessAskChat } from "./ask/harness-chat.ts";
import { makeAuth } from "./auth.ts";
import type { Deps } from "./context.ts";
import { connectApp, connectUniverse, type Db } from "./db/client.ts";
import type { Env } from "./env.ts";
import { log } from "./log.ts";
import { BALANCER_DEFAULTS, Balancer } from "./models/balancer.ts";
import { recordTo } from "./models/calls.ts";
import { geminiThenNim } from "./models/gemini-then-nim.ts";
import { NIM_LADDER } from "./models/nim.ts";
import { GEMINI_ID, GEMINI_THINKING, geminiFrom, proxyConfig } from "./models/proxy.ts";
import { loadPrompts } from "./prompts.ts";
import { type Grader, noGrader } from "./quiz/grader.ts";
import { modelGrader } from "./quiz/model-grader.ts";

export function makeEmbedder(env: Env): Embedder {
  return env.EMBEDDER === "qwen3"
    ? new Qwen3OnnxEmbedder({ cacheDir: env.MODEL_CACHE_DIR })
    : new HashEmbedder();
}

/** Gemini first, NIM when it fails; a process with neither key grades nothing. */
export function makeGrader(env: Env, db: Db): Grader {
  const proxy = proxyConfig(env);
  const nimKey = env.NVIDIA_NIM_API_KEY;
  if (!proxy && !nimKey) return noGrader;
  const record = recordTo(db);
  return modelGrader({
    prompts: loadPrompts(),
    gemini: proxy ? { model: geminiFrom(proxy), apiKey: proxy.apiKey } : null,
    // The API never ends, so a model that refuses the key is asked again later.
    nim: nimKey ? new Balancer(NIM_LADDER, nimKey, record, { ...BALANCER_DEFAULTS, patient: true }) : null,
    record,
  });
}

/**
 * AskAI's chat on Gemini, then NIM when it fails; a process with neither key answers nothing. A turn
 * runs on NIM's top model when there is no proxy, or the proxy can't say what Gemini is.
 */
export function makeAskChat(env: Env, db: Db): AskChat {
  const proxy = proxyConfig(env);
  const nimKey = env.NVIDIA_NIM_API_KEY;
  if (!proxy && !nimKey) return noAskChat;
  const gemini = proxy ? geminiFrom(proxy) : null;
  const [top] = NIM_LADDER;
  return harnessAskChat({
    db,
    prompts: loadPrompts(),
    async model() {
      if (gemini) {
        try {
          return await gemini();
        } catch (error) {
          if (!nimKey || !top) throw error;
          log.warn({ err: error }, "Gemini couldn't be looked up, so the turn runs on NIM");
        }
      }
      if (!top) throw new Error("NIM's ladder is empty.");
      return top.model;
    },
    thinkingLevel: GEMINI_THINKING,
    apiKey: proxy?.apiKey ?? nimKey ?? "",
    streamFn: (run) => {
      const record = recordTo(db, run.id);
      return geminiThenNim({
        gemini: proxy && run.model === GEMINI_ID ? { apiKey: proxy.apiKey } : null,
        // The API never ends, so a model that refuses the key is asked again later.
        nim: nimKey
          ? new Balancer(NIM_LADDER, nimKey, record, { ...BALANCER_DEFAULTS, patient: true })
          : null,
        record,
      });
    },
  });
}

/** Built once per process; `close` ends its pools. */
export function makeDeps(env: Env): Deps & { close: () => Promise<void> } {
  const app = connectApp(env.DATABASE_URL);
  const universe = env.UNIVERSE_DATABASE_URL
    ? connectUniverse(env.UNIVERSE_DATABASE_URL, { readOnly: true })
    : null;
  return {
    env,
    db: app.db,
    pool: app.pool,
    universe: universe?.db ?? null,
    auth: makeAuth(env, app.db),
    embedder: makeEmbedder(env),
    grader: makeGrader(env, app.db),
    askChat: makeAskChat(env, app.db),
    close: async () => {
      await Promise.all([app.pool.end(), universe?.pool.end()]);
    },
  };
}
