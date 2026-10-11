import { sql } from "drizzle-orm";
import { afterAll, beforeEach } from "vitest";
import { connectUniverse, type UniverseDb } from "../src/universe/db.ts";

// The Hono stack's own Postgres (npm run stack, port 5434), never the old project's.
export const TEST_URL = "postgres://spoin:spoin@localhost:5434/the_spoin_universe_test";

/**
 * The corpus test database, emptied before each test. The real database rather than a
 * mock, because what is under test is its own behaviour: `source_path`'s UNIQUE, the
 * CASCADEs, the array overlap and pgvector's ordering.
 */
export function useUniverse(): UniverseDb {
  const { pool, db } = connectUniverse(TEST_URL);
  beforeEach(async () => {
    await db.execute(sql`TRUNCATE document, chunk, image, curriculum, curriculum_subtopic`);
  });
  afterAll(() => pool.end());
  return db;
}
