// Tests run against the Hono stack's own Postgres (npm run stack, port 5434), in their own databases.
export const testEnv: Record<string, string> = {
  NODE_ENV: "test",
  LOG_LEVEL: "silent",
  DATABASE_URL: "postgres://spoin:spoin@localhost:5434/spoin_test",
  UNIVERSE_DATABASE_URL: "postgres://spoin:spoin@localhost:5434/the_spoin_universe_test",
  AUTH_SECRET: "spoin-test-secret-0123456789abcdef0123456789",
  ALLOWED_ORIGINS: "http://localhost:3000",
  // helpers.ts gives each simulated client its own address in this header.
  CLIENT_IP_HEADER: "x-forwarded-for",
  EMBEDDER: "hash",
  DEV_ROUTES: "true",
};
