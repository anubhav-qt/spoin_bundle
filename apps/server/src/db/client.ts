import * as universeSchema from "@spoin/frog/schema";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import pg from "pg";
import { log } from "../log.ts";
import * as schema from "./schema.ts";

export type Db = NodePgDatabase<typeof schema>;
export type UniverseDb = NodePgDatabase<typeof universeSchema>;

// bigint and numeric come back as strings by default; every count here fits a JS number.
pg.types.setTypeParser(pg.types.builtins.INT8, (v) => Number(v));
pg.types.setTypeParser(pg.types.builtins.NUMERIC, (v) => Number(v));

export function makePool(url: string, opts: { name: string; max?: number; readOnly?: boolean }): pg.Pool {
  const pool = new pg.Pool({
    connectionString: url,
    max: opts.max ?? 10,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
    application_name: `spoin-${opts.name}`,
    // Every transaction READ ONLY, so a stray write raises in Postgres rather than
    // depending on nobody committing one.
    options: opts.readOnly ? "-c default_transaction_read_only=on" : undefined,
  });
  pool.on("error", (err) => log.warn({ err, pool: opts.name }, "idle database connection failed"));
  return pool;
}

export function connectApp(url: string, max = 10): { pool: pg.Pool; db: Db } {
  const pool = makePool(url, { name: "app", max });
  return { pool, db: drizzle(pool, { schema }) };
}

/**
 * The corpus. Read-only from the API: its writer is the worker (the tadpoles and
 * ingestion), and the API has no legitimate reason to write it.
 */
export function connectUniverse(
  url: string,
  opts: { readOnly: boolean; max?: number },
): { pool: pg.Pool; db: UniverseDb } {
  const pool = makePool(url, { name: "universe", max: opts.max ?? 3, readOnly: opts.readOnly });
  return { pool, db: drizzle(pool, { schema: universeSchema }) };
}

/** A transaction handle; services that compose take `Db | Tx`. */
export type Tx = Parameters<Parameters<Db["transaction"]>[0]>[0];
