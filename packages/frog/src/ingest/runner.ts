import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { eq } from "drizzle-orm";
import type { Embedder } from "../embeddings.ts";
import { markdownFiles } from "../front-matter.ts";
import type { Universe } from "../universe/db.ts";
import { chunk, document } from "../universe/schema.ts";
import { chunkTexts } from "./chunking.ts";
import { type DocumentErrors, type ParsedDocument, parseDocument } from "./contract.ts";

/*
 * The delivered corpus written into `the_spoin_universe`, organised around one
 * requirement: re-ingesting an unchanged corpus writes nothing (ADR-0088). The corpus is
 * re-delivered many times as it is revised, so an ingester that duplicates on the second
 * run is not one. Identity is `source_path`; change is a sha256 of the raw file.
 */

/**
 * Texts per embedding call. Bulk and offline, so this is about memory, not a rate limit:
 * the embedder is local and never metered.
 */
const EMBED_BATCH = 64;

/** Not corpus content: the contract documents the layout in the tree itself. */
const SKIP_NAMES = new Set(["README.md"]);

/**
 * What one run did, in counts a human can check. `failed` and `unchanged` are never
 * folded together (CLAUDE.md): a rejected document and an unchanged one are different
 * facts, and one number would make a clean re-run read as a validation catastrophe.
 */
export interface IngestReport {
  scanned: number;
  ingested: number;
  unchanged: number;
  failed: number;
  chunksWritten: number;
  errors: DocumentErrors[];
}

export const ingestSummary = (r: IngestReport): string =>
  `scanned=${r.scanned} ingested=${r.ingested} unchanged=${r.unchanged} failed=${r.failed} chunks_written=${r.chunksWritten}`;

/**
 * Parse and validate the whole corpus without touching the database: runnable on its own
 * (`corpus:check`), and a failing corpus is reported in full before a row is written.
 */
export function parseCorpus(root: string): { parsed: ParsedDocument[]; failures: DocumentErrors[] } {
  const parsed: ParsedDocument[] = [];
  const failures: DocumentErrors[] = [];
  for (const [sourcePath, full] of markdownFiles(root)) {
    if (SKIP_NAMES.has(basename(full))) continue;
    const { document: doc, errors } = parseDocument(sourcePath, readFileSync(full));
    if (doc) parsed.push(doc);
    else failures.push(errors);
  }
  return { parsed, failures };
}

/**
 * Write one document and its chunks; returns how many chunks were written. An unchanged
 * hash returns 0 and touches nothing. The caller owns the transaction: a changed
 * document's chunks are deleted and rebuilt, and a crash between the two must not leave a
 * document with no chunks still claiming a current hash.
 */
export async function ingestDocument(
  db: Universe,
  parsed: ParsedDocument,
  embedder: Embedder,
  opts: { force?: boolean } = {},
): Promise<number> {
  const [existing] = await db
    .select({ id: document.id, contentHash: document.contentHash })
    .from(document)
    .where(eq(document.sourcePath, parsed.sourcePath));
  if (existing && existing.contentHash === parsed.contentHash && !opts.force) return 0;

  const texts = chunkTexts(parsed);
  // Embedded before any write, so a model failure cannot leave a half-replaced document,
  // and on the PASSAGE side: corpus material is what is searched, not what searches
  // (ADR-0092). Backwards is a silent recall loss, not an error.
  const vectors: number[][] = [];
  for (let start = 0; start < texts.length; start += EMBED_BATCH) {
    vectors.push(...(await embedder.embedPassage(texts.slice(start, start + EMBED_BATCH))));
  }

  const fields = {
    title: parsed.title,
    kind: parsed.kind,
    source: parsed.source,
    category: parsed.category,
    subCategory: parsed.subCategory,
    scope: parsed.scope,
    sourceDate: parsed.sourceDate,
    contentHash: parsed.contentHash,
    ingestedAt: new Date(),
  };
  let documentId: string;
  if (existing) {
    // A revision keeps the document row, and its id that cards may cite, and replaces only its chunks.
    documentId = existing.id;
    await db.delete(chunk).where(eq(chunk.documentId, documentId));
    await db.update(document).set(fields).where(eq(document.id, documentId));
  } else {
    const [created] = await db
      .insert(document)
      .values({ sourcePath: parsed.sourcePath, ...fields })
      .returning({ id: document.id });
    documentId = (created as { id: string }).id;
  }

  if (texts.length > 0) {
    await db.insert(chunk).values(
      parsed.sections.map((section, ordinal) => ({
        documentId,
        ordinal,
        text: texts[ordinal] as string,
        // Beside the text it is already prefixed into, so a `<path>#<heading>` reference
        // resolves by join rather than by matching the front of `text`.
        heading: section.heading,
        embedding: vectors[ordinal] as number[],
        // From the embedder that just made the vector, never from config: a stamp read
        // from somewhere other than the thing that did the work can lie.
        embeddingModel: embedder.modelName,
        // Tags sit on the chunk so a broad source can tag sections differently; the
        // contract has no per-section tags yet, so every chunk inherits the document's.
        topicTags: [...parsed.topicTags],
      })),
    );
  }
  return texts.length;
}

/**
 * Validate the whole corpus, then ingest every document that passed. A failing document
 * does not stop the others: the good ones are usable now, the failures are a list to
 * hand back.
 */
export async function ingestCorpus(
  db: Universe,
  root: string,
  embedder: Embedder,
  opts: { force?: boolean; log?: (line: string) => void } = {},
): Promise<IngestReport> {
  const { parsed, failures } = parseCorpus(root);
  const report: IngestReport = {
    scanned: parsed.length + failures.length,
    ingested: 0,
    unchanged: 0,
    failed: failures.length,
    chunksWritten: 0,
    errors: failures,
  };
  for (const doc of parsed) {
    const written = await ingestDocument(db, doc, embedder, opts);
    if (written) {
      report.ingested += 1;
      report.chunksWritten += written;
      opts.log?.(`ingested ${doc.sourcePath} (${written} chunks)`);
    } else {
      report.unchanged += 1;
    }
  }
  return report;
}
