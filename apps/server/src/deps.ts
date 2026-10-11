import { type Embedder, HashEmbedder, Qwen3OnnxEmbedder } from "@spoin/frog/embeddings";
import { noAskChat } from "./ask/chat.ts";
import { makeAuth } from "./auth.ts";
import type { Deps } from "./context.ts";
import { connectApp, connectUniverse } from "./db/client.ts";
import type { Env } from "./env.ts";
import { noGrader } from "./quiz/grader.ts";

export function makeEmbedder(env: Env): Embedder {
  return env.EMBEDDER === "qwen3"
    ? new Qwen3OnnxEmbedder({ cacheDir: env.MODEL_CACHE_DIR })
    : new HashEmbedder();
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
    grader: noGrader,
    askChat: noAskChat,
    close: async () => {
      await Promise.all([app.pool.end(), universe?.pool.end()]);
    },
  };
}
