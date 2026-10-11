import { sql } from "drizzle-orm";
import { afterAll, beforeEach } from "vitest";
import { connectUniverse } from "../src/db/client.ts";
import { env } from "./helpers.ts";

/**
 * A writable handle on the corpus test database, standing in for frog's ingestion: the
 * API's own handle is read-only. Emptied before each test of a file that uses it.
 */
export function useCorpus() {
  const { pool, db } = connectUniverse(env.UNIVERSE_DATABASE_URL as string, { readOnly: false, max: 2 });
  beforeEach(async () => {
    await db.execute(sql`TRUNCATE document, chunk, image, curriculum, curriculum_subtopic`);
  });
  afterAll(() => pool.end());
  return db;
}
