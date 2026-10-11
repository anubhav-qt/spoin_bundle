import { connectApp, connectUniverse } from "../db/client.ts";
import { makeEmbedder } from "../deps.ts";
import { loadEnv } from "../env.ts";
import { projectCurricula, projectionSummary } from "./projection.ts";

/*
 * `npm run curriculum:project`: the ingested curricula onto the app's topics and
 * subtopics. Reads the corpus read-only; writes only the app database.
 */

const env = loadEnv();
if (!env.UNIVERSE_DATABASE_URL)
  throw new Error("UNIVERSE_DATABASE_URL is required: the curricula live there");
const app = connectApp(env.DATABASE_URL, 2);
const universe = connectUniverse(env.UNIVERSE_DATABASE_URL, { readOnly: true, max: 1 });
try {
  const report = await projectCurricula({
    db: app.db,
    universe: universe.db,
    embedder: makeEmbedder(env),
    minCardsFraction: env.MIN_CARDS_FRACTION,
  });
  console.log(projectionSummary(report));
} finally {
  await Promise.all([app.pool.end(), universe.pool.end()]);
}
