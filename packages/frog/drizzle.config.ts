import { defineConfig } from "drizzle-kit";

/**
 * `the_spoin_universe` only (ADR-0088). Generating migrations needs no database; there
 * is deliberately no `dbCredentials` here, so this config cannot push or migrate the
 * wrong database by accident. Migrations run through `apps/server/src/migrate.ts`,
 * which reads `UNIVERSE_DATABASE_URL` and nothing else for them.
 */
export default defineConfig({
  dialect: "postgresql",
  schema: "./src/universe/schema.ts",
  out: "./drizzle",
});
