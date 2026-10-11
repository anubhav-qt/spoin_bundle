import type { Embedder } from "@spoin/frog/embeddings";
import type pg from "pg";
import type { Auth } from "./auth.ts";
import type { Db, UniverseDb } from "./db/client.ts";
import type { Env } from "./env.ts";

/** Everything a route needs, built once per process by the entrypoint and passed in. */
export interface Deps {
  env: Env;
  db: Db;
  pool: pg.Pool;
  /** The corpus, read-only; null when `UNIVERSE_DATABASE_URL` is unset. */
  universe: UniverseDb | null;
  auth: Auth;
  embedder: Embedder;
}

/** The signed-in caller, as the auth middleware resolves it. */
export interface Caller {
  id: string;
  isGuest: boolean;
  isAdmin: boolean;
}

export type AppEnv = {
  Variables: {
    requestId: string;
    /** The client's address, for rate limits. */
    ip: string;
    /** Null when the request carries no valid session. */
    caller: Caller | null;
  };
};
