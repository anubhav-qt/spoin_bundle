import { defineConfig } from "drizzle-kit";

/**
 * The app database only. No `dbCredentials`: generating a migration needs no database,
 * and leaving them out means this config cannot push to one. Migrations run through
 * `src/migrate.ts`.
 */
export default defineConfig({
  dialect: "postgresql",
  schema: "./src/db/schema.ts",
  out: "./drizzle",
});
