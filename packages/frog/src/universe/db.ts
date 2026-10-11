import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import pg from "pg";
import * as schema from "./schema.ts";

export type UniverseDb = NodePgDatabase<typeof schema>;
export type UniverseTx = Parameters<Parameters<UniverseDb["transaction"]>[0]>[0];
/** Anything frog queries through: the database, or a transaction the caller owns. */
export type Universe = UniverseDb | UniverseTx;

/**
 * The corpus database's URL, from `UNIVERSE_DATABASE_URL` and nothing else (ADR-0088).
 * Never a fallback to `DATABASE_URL`: a convenience default is how a corpus write lands
 * on the app's database, so an unset variable stops the caller instead.
 */
export function universeUrl(env: NodeJS.ProcessEnv = process.env): string {
  const url = env.UNIVERSE_DATABASE_URL;
  if (!url) {
    throw new Error(
      "UNIVERSE_DATABASE_URL is not set. frog talks to the_spoin_universe only (ADR-0088) and will not fall back to DATABASE_URL.",
    );
  }
  return url;
}

/** A writable connection for frog's own entrypoints; the API reads the corpus through its own, read-only. */
export function connectUniverse(url: string): { pool: pg.Pool; db: UniverseDb } {
  const pool = new pg.Pool({ connectionString: url, max: 2, application_name: "spoin-frog" });
  return { pool, db: drizzle(pool, { schema }) };
}
