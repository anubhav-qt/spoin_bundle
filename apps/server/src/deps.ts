import { type Embedder, HashEmbedder, Qwen3OnnxEmbedder } from "@spoin/frog/embeddings";
import { noAskChat } from "./ask/chat.ts";
import { makeAuth } from "./auth.ts";
import type { Deps } from "./context.ts";
import { connectApp, connectUniverse, type Db } from "./db/client.ts";
import type { Env } from "./env.ts";
import { BALANCER_DEFAULTS, Balancer } from "./models/balancer.ts";
import { recordTo } from "./models/calls.ts";
import { NIM_LADDER } from "./models/nim.ts";
import { geminiFrom, proxyConfig } from "./models/proxy.ts";
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
    askChat: noAskChat,
    close: async () => {
      await Promise.all([app.pool.end(), universe?.pool.end()]);
    },
  };
}
