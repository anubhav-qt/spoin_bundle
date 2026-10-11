import { resolve } from "node:path";
import { type Embedder, HashEmbedder, Qwen3OnnxEmbedder } from "./embeddings.ts";
import { connectUniverse, type UniverseTx, universeUrl } from "./universe/db.ts";

/*
 * What frog's three entrypoints share (`corpus`, `curriculum`, `images`). Each has a
 * `--check` that is pure: no database, no model, no network. That half is the one an
 * author runs while writing, so it must never need any of the three.
 */

/** The delivered trees, under the repository's `docs/the_spoin_universe/`. */
export const UNIVERSE_DOCS = resolve(import.meta.dirname, "../../../docs/the_spoin_universe");

/**
 * Every problem in every failing file, named by path. Files are written by another
 * track, so a failure is a work item handed to someone: "validation failed" is not one,
 * "`title` is missing" is.
 */
export function printFailures(failures: { path: string; problems: string[] }[]): void {
  for (const { path, problems } of failures) {
    console.error(`\nFAIL ${path}`);
    for (const problem of problems) console.error(`  - ${problem}`);
  }
}

/**
 * `qwen3` is the real model (ADR-0097); `hash` is a stand-in with NO semantic meaning,
 * for tests. Loud, because a corpus embedded with it looks normal in the database and is
 * useless, the shape of task 0039, where hash vectors sat unnoticed for months.
 */
export function cliEmbedder(name: string): Embedder {
  if (name === "hash") {
    console.warn(
      "HashEmbedder: vectors will have NO semantic meaning. Draw no retrieval conclusions from them.",
    );
    return new HashEmbedder();
  }
  if (name !== "qwen3") throw new Error(`--embedder must be qwen3 or hash, got ${name}`);
  return new Qwen3OnnxEmbedder({ cacheDir: process.env.MODEL_CACHE_DIR });
}

/**
 * One transaction for the whole run: rows are deleted and rebuilt, and a crash part-way
 * must not leave a row whose hash claims it is current while its children are gone.
 */
export async function inUniverse<T>(work: (tx: UniverseTx) => Promise<T>): Promise<T> {
  const { pool, db } = connectUniverse(universeUrl());
  try {
    return await db.transaction(work);
  } finally {
    await pool.end();
  }
}
