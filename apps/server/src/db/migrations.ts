import { drizzle } from "drizzle-orm/node-postgres";
import { migrate } from "drizzle-orm/node-postgres/migrator";
import { log } from "../log.ts";
import { makePool } from "./client.ts";

const LOCK = "hashtext('spoin:migrate')";

/** Applies one database's migrations, under an advisory lock so two starting processes don't race. */
export async function migrateDatabase(url: string, name: string, migrationsFolder: string): Promise<void> {
  const pool = makePool(url, { name: `migrate-${name}`, max: 2 });
  const lock = await pool.connect();
  try {
    await lock.query(`SELECT pg_advisory_lock(${LOCK})`);
    // drizzle-kit doesn't emit extensions; both databases store vectors.
    await lock.query("CREATE EXTENSION IF NOT EXISTS vector");
    await migrate(drizzle(pool), { migrationsFolder });
    await lock.query(`SELECT pg_advisory_unlock(${LOCK})`);
  } finally {
    lock.release();
    await pool.end();
  }
  log.info(`${name} migrated`);
}
