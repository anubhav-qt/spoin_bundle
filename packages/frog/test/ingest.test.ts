import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { asc, count, eq } from "drizzle-orm";
import { describe, expect, it } from "vitest";
import { HashEmbedder } from "../src/embeddings.ts";
import { type ParsedDocument, parseDocument } from "../src/ingest/contract.ts";
import { ingestCorpus, ingestDocument } from "../src/ingest/runner.ts";
import { chunk, document } from "../src/universe/schema.ts";
import { useUniverse } from "./universe.ts";

/*
 * Re-ingesting the corpus must not duplicate it (ADR-0088): the corpus is re-delivered
 * many times, and a duplicate fails silently, retrieval returning the same passage twice
 * and spending the prompt on it. So this runs against the real database.
 */

const db = useUniverse();

const DOC = `---
title: MVCC and transaction isolation
kind: topic_source
category: computer science
scope: topic
source: https://www.postgresql.org/docs/17/mvcc.html
topic_tags:
  - postgresql
---

## Snapshot isolation

Each transaction sees a snapshot taken at its start.

## Phantom reads

Postgres also prevents them at REPEATABLE READ.
`;

// Meaningless vectors, and fine: what is under test is row identity, not retrieval.
const embedder = new HashEmbedder();

const parsed = (raw: string): ParsedDocument => {
  const { document: doc, errors } = parseDocument("cs/pg/mvcc.md", new TextEncoder().encode(raw));
  if (!doc) throw new Error(errors.problems.join("; "));
  return doc;
};
const ingest = (raw: string, force = false) => ingestDocument(db, parsed(raw), embedder, { force });

async function counts(): Promise<[number, number]> {
  const [docs] = await db.select({ n: count() }).from(document);
  const [chunks] = await db.select({ n: count() }).from(chunk);
  return [docs?.n ?? 0, chunks?.n ?? 0];
}

describe("ingesting the corpus", () => {
  it("writes a document and its chunks the first time", async () => {
    expect(await ingest(DOC)).toBe(2);
    expect(await counts()).toEqual([1, 2]);
    const [row] = await db.select().from(chunk).orderBy(asc(chunk.ordinal));
    expect(row).toMatchObject({ ordinal: 0, heading: "Snapshot isolation", embeddingModel: "hash" });
    expect(row?.topicTags).toEqual(["postgresql"]);
  });

  it("does nothing for an unchanged document, not even restamp it", async () => {
    // A delete-and-reinsert would pass a count-only check while paying for a full re-embed.
    await ingest(DOC);
    const [before] = await db.select({ at: document.ingestedAt }).from(document);
    expect(await ingest(DOC)).toBe(0);
    expect(await counts()).toEqual([1, 2]);
    const [after] = await db.select({ at: document.ingestedAt }).from(document);
    expect(after?.at).toEqual(before?.at);
  });

  it("replaces a changed document's chunks, keeping the document row", async () => {
    // Cards cite chunks against the document (ADR-0089), so its id survives a revision.
    await ingest(DOC);
    const [first] = await db.select({ id: document.id }).from(document);
    expect(await ingest(DOC.replace("## Phantom reads", "## Phantom reads\n\nExtra.\n\n## Write skew"))).toBe(
      3,
    );
    expect(await counts()).toEqual([1, 3]);
    const [again] = await db.select({ id: document.id }).from(document);
    expect(again?.id).toBe(first?.id);
    const ordinals = await db.select({ o: chunk.ordinal }).from(chunk).orderBy(asc(chunk.ordinal));
    expect(ordinals.map((r) => r.o)).toEqual([0, 1, 2]);
  });

  it("carries a revised title into the stored chunk text", async () => {
    await ingest(DOC);
    await ingest(DOC.replace("title: MVCC and transaction isolation", "title: MVCC, revised"));
    const [doc] = await db.select({ title: document.title }).from(document);
    expect(doc?.title).toBe("MVCC, revised");
    const [first] = await db.select({ text: chunk.text }).from(chunk).orderBy(asc(chunk.ordinal));
    expect(first?.text.startsWith("MVCC, revised — ")).toBe(true);
  });

  it("re-embeds an unchanged document under force", async () => {
    // For what a hash cannot see: the file is the same but what is embedded from it changed.
    await ingest(DOC);
    expect(await ingest(DOC, true)).toBe(2);
    expect(await counts()).toEqual([1, 2]);
  });

  it("cascades a deleted document to its chunks", async () => {
    await ingest(DOC);
    await db.delete(document).where(eq(document.sourcePath, "cs/pg/mvcc.md"));
    expect(await counts()).toEqual([0, 0]);
  });

  it("reports failed documents apart from unchanged ones, and skips READMEs", async () => {
    const root = mkdtempSync(join(tmpdir(), "frog-corpus-"));
    writeFileSync(join(root, "good.md"), DOC);
    writeFileSync(join(root, "bad.md"), DOC.replace("title: MVCC and transaction isolation\n", ""));
    writeFileSync(join(root, "README.md"), "not corpus content");

    const first = await ingestCorpus(db, root, embedder);
    expect(first).toMatchObject({ scanned: 2, ingested: 1, unchanged: 0, failed: 1, chunksWritten: 2 });
    expect(first.errors[0]?.sourcePath).toBe("bad.md");

    const second = await ingestCorpus(db, root, embedder);
    expect(second).toMatchObject({ scanned: 2, ingested: 0, unchanged: 1, failed: 1, chunksWritten: 0 });
    expect(await counts()).toEqual([1, 2]);
  });

  it("names a nested document by its POSIX path whatever the OS", async () => {
    const root = mkdtempSync(join(tmpdir(), "frog-corpus-"));
    const nested = join(root, "cs", "pg");
    mkdirSync(nested, { recursive: true });
    writeFileSync(join(nested, "mvcc.md"), DOC);
    await ingestCorpus(db, root, embedder);
    const [row] = await db.select({ path: document.sourcePath }).from(document);
    expect(row?.path).toBe("cs/pg/mvcc.md");
  });
});
