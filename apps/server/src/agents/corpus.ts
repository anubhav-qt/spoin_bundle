import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { parseDocument } from "@spoin/frog/ingest/contract";
import { normalizeTopicText } from "@spoin/frog/normalize";
import { search } from "@spoin/frog/retrieval";
import { document } from "@spoin/frog/schema";
import { inArray } from "drizzle-orm";
import { Type } from "typebox";
import type { topic } from "../db/schema.ts";
import { topicById } from "../harness/intake.ts";
import { CLOSED, Id } from "../harness/schemas.ts";
import { type HarnessTool, ToolError } from "../harness/tools.ts";
import { slugify } from "../topics/slug.ts";
import type { AgentDeps } from "./context.ts";

/*
 * The corpus as the chats read it (harness-tools.md, task 0045): searched by meaning once
 * ingested, and listed and read as the files the writers wrote, ingested or not. The corpus is
 * brand new: the tadpoles write all of it.
 */

/** Sections `search_corpus` returns. */
const SEARCH_RESULTS = 8;

type Topic = typeof topic.$inferSelect;

/**
 * A topic's directory under the corpus, `<category>/<sub category>/<slug>`, as the contract lays
 * it out (antigravity-corpus-authoring.md). The level with no sub category is left out.
 */
export function topicDir(found: Topic): string {
  const parts = [slugify(found.category ?? "uncategorized")];
  if (found.subCategory) parts.push(slugify(found.subCategory));
  parts.push(found.slug);
  return parts.join("/");
}

/** A path under the corpus, or a tool error for one that would leave it. */
export function corpusFile(deps: AgentDeps, path: string): string {
  const root = resolve(deps.files.corpus);
  const full = resolve(root, path);
  if (!full.startsWith(root + sep)) throw new ToolError(`${path} is not a path under the corpus.`);
  return full;
}

/** Every document under the corpus, or under one of its directories, as paths relative to the corpus. */
export function corpusPaths(deps: AgentDeps, under = ""): string[] {
  const start = under ? corpusFile(deps, under) : resolve(deps.files.corpus);
  if (!existsSync(start)) return [];
  return readdirSync(start, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
    .map((entry) => relative(deps.files.corpus, join(entry.parentPath, entry.name)).split(sep).join("/"))
    .sort();
}

const SearchCorpusParameters = Type.Object(
  { query: Type.String({ minLength: 1, description: "What you want the corpus to say" }) },
  CLOSED,
);

export function searchCorpusTool(deps: AgentDeps): HarnessTool<typeof SearchCorpusParameters> {
  return {
    name: "search_corpus",
    label: "Search the corpus",
    description: deps.prompts.render("tools/search-corpus.njk", {}),
    parameters: SearchCorpusParameters,
    kind: "read",
    async execute(params) {
      const hits = await search(deps.universe, deps.embedder, params.query, {
        k: SEARCH_RESULTS,
        kinds: ["topic_source"],
      });
      return {
        value: deps.prompts.render("tool-results/corpus-sections.njk", { query: params.query, hits }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

const ListDocumentsParameters = Type.Object(
  {
    category: Type.Optional(Type.String({ minLength: 1, description: "Only this category's documents" })),
    topic: Type.Optional(Id),
  },
  CLOSED,
);

export function listDocumentsTool(deps: AgentDeps): HarnessTool<typeof ListDocumentsParameters> {
  return {
    name: "list_documents",
    label: "List the corpus's documents",
    description: deps.prompts.render("tools/list-documents.njk", {}),
    parameters: ListDocumentsParameters,
    kind: "read",
    async execute(params, context) {
      let under = "";
      if (params.topic) under = topicDir(await topicById(context.db, params.topic));
      else if (params.category) under = slugify(normalizeTopicText(params.category));
      const paths = corpusPaths(deps, under);
      const ingested = new Set<string>();
      if (paths.length > 0) {
        const rows = await deps.universe
          .select({ sourcePath: document.sourcePath })
          .from(document)
          .where(inArray(document.sourcePath, paths));
        for (const row of rows) ingested.add(row.sourcePath);
      }
      const documents = paths.map((path) => {
        const { document: parsed } = parseDocument(path, readFileSync(corpusFile(deps, path)));
        return {
          path,
          title: parsed?.title ?? null,
          sections: parsed?.sections.length ?? null,
          ingested: ingested.has(path),
        };
      });
      return {
        value: deps.prompts.render("tool-results/documents.njk", { documents, under }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

const ReadDocumentParameters = Type.Object(
  { path: Type.String({ minLength: 1, description: "The document's path under the corpus" }) },
  CLOSED,
);

export function readDocumentTool(deps: AgentDeps): HarnessTool<typeof ReadDocumentParameters> {
  return {
    name: "read_document",
    label: "Read a corpus document",
    description: deps.prompts.render("tools/read-document.njk", {}),
    parameters: ReadDocumentParameters,
    kind: "read",
    async execute(params) {
      const full = corpusFile(deps, params.path);
      if (!existsSync(full)) {
        throw new ToolError(`There is no document ${params.path}; list_documents shows what there is.`);
      }
      const raw = readFileSync(full);
      const { document: parsed, errors } = parseDocument(params.path, raw);
      return {
        value: deps.prompts.render("tool-results/document.njk", {
          path: params.path,
          text: raw.toString("utf8"),
          headings: parsed?.sections.map((section) => section.heading) ?? [],
          problems: errors.problems,
        }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}
