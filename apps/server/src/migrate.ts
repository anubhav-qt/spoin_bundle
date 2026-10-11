import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { migrateDatabase } from "./db/migrations.ts";

/*
 * Brings both databases to the latest schema. Each has its own migrations and its own
 * URL, and the corpus's is never a fallback to the app's (ADR-0088): a convenience
 * fallback is how a corpus migration lands on the app database. Runs from src/ in
 * development and dist/ in the image, where both folders sit beside the bundle.
 */
const here = dirname(fileURLToPath(import.meta.url));
const appMigrations = process.env.MIGRATIONS_DIR ?? resolve(here, "../drizzle");
const universeMigrations =
  process.env.UNIVERSE_MIGRATIONS_DIR ?? resolve(here, "../../../packages/frog/drizzle");

const { DATABASE_URL, UNIVERSE_DATABASE_URL } = process.env;
if (!DATABASE_URL) throw new Error("DATABASE_URL is required");
await migrateDatabase(DATABASE_URL, "app", appMigrations);
if (UNIVERSE_DATABASE_URL) await migrateDatabase(UNIVERSE_DATABASE_URL, "universe", universeMigrations);
