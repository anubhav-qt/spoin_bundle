import { join } from "node:path";
import type { Embedder } from "@spoin/frog/embeddings";
import type { Db, UniverseDb } from "../db/client.ts";
import type { WebSearchConfig } from "../harness/web-search.ts";
import type { Prompts } from "../prompts.ts";
import type { Browser } from "./browser.ts";
import type { OneShot } from "./one-shot.ts";

/**
 * What the agents' tools reach beyond the chat calling them (task 0045): the corpus, written and
 * read as files and ingested into `the_spoin_universe`, the pages fetched, the embedder, and the
 * models a tool calls itself.
 */
export interface AgentDeps {
  db: Db;
  /** Writable: the worker ingests the corpus and the curricula the chats write. */
  universe: UniverseDb;
  embedder: Embedder;
  prompts: Prompts;
  files: Files;
  /** The coverage threshold the projection sets on each tier (ADR-0007). */
  minCardsFraction: number;
  /** Null in a process with no proxy: the chats can't search the web. */
  webSearch: WebSearchConfig | null;
  /** The auditors' and pass 2's fixed calls. */
  oneShot: OneShot;
  /** Headless Chromium: pages with no text in their HTML, and designer_toad's renders. */
  browser: Browser;
}

/** Where the chats' files live: the corpus and curricula they write, and the pages they fetch. */
export interface Files {
  corpus: string;
  curricula: string;
  pages: string;
}

export function filesUnder(root: string): Files {
  return { corpus: join(root, "corpus"), curricula: join(root, "curricula"), pages: join(root, "pages") };
}
