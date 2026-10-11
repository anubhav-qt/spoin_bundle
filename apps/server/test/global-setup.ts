import { resolve } from "node:path";
import pg from "pg";
import { migrateDatabase } from "../src/db/migrations.ts";
import { testEnv } from "./env.ts";

/**
 * Fresh, migrated test databases. Refuses (never skips) any name not ending in
 * `_test`: dropping is the first thing this does, so a mistyped URL must fail here.
 */
export default async function setup() {
  const targets = [
    { url: testEnv.DATABASE_URL as string, migrations: resolve(import.meta.dirname, "../drizzle") },
    {
      url: testEnv.UNIVERSE_DATABASE_URL as string,
      migrations: resolve(import.meta.dirname, "../../../packages/frog/drizzle"),
    },
  ];
  for (const { url, migrations } of targets) {
    const u = new URL(url);
    const name = u.pathname.slice(1);
    if (!name.endsWith("_test")) throw new Error(`refusing to recreate ${name}: test databases end in _test`);
    u.pathname = "/postgres";
    const admin = new pg.Client({ connectionString: u.toString() });
    await admin.connect();
    await admin.query(`DROP DATABASE IF EXISTS "${name}" WITH (FORCE)`);
    await admin.query(`CREATE DATABASE "${name}"`);
    await admin.end();
    await migrateDatabase(url, name, migrations);
  }
}
