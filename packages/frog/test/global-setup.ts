import { resolve } from "node:path";
import { drizzle } from "drizzle-orm/node-postgres";
import { migrate } from "drizzle-orm/node-postgres/migrator";
import pg from "pg";
import { TEST_URL } from "./universe.ts";

/**
 * A fresh, migrated corpus test database. Refuses (never skips) a name that does not end
 * in `_test`: dropping it is the first thing this does, so a mistyped URL fails here.
 */
export default async function setup() {
  const url = new URL(TEST_URL);
  const name = url.pathname.slice(1);
  if (!name.endsWith("_test")) throw new Error(`refusing to recreate ${name}: test databases end in _test`);
  url.pathname = "/postgres";
  const admin = new pg.Client({ connectionString: url.toString() });
  await admin.connect();
  await admin.query(`DROP DATABASE IF EXISTS "${name}" WITH (FORCE)`);
  await admin.query(`CREATE DATABASE "${name}"`);
  await admin.end();

  const pool = new pg.Pool({ connectionString: TEST_URL, max: 1 });
  try {
    // drizzle-kit doesn't emit extensions.
    await pool.query("CREATE EXTENSION IF NOT EXISTS vector");
    await migrate(drizzle(pool), { migrationsFolder: resolve(import.meta.dirname, "../drizzle") });
  } finally {
    await pool.end();
  }
}
