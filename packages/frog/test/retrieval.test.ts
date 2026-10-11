import { eq } from "drizzle-orm";
import { describe, expect, it } from "vitest";
import { EMBEDDING_DIM, type Embedder } from "../src/embeddings.ts";
import {
  corpusVersion,
  countImages,
  type Hit,
  resolveGrounding,
  search,
  searchImages,
  searchMany,
} from "../src/retrieval.ts";
import { chunk, document, image } from "../src/universe/schema.ts";
import { useUniverse } from "./universe.ts";

/*
 * What retrieval promises, against the real database: the array overlap, the enum
 * comparison and pgvector's ordering are the database's own behaviour.
 *
 * The load-bearing test is the query side. ADR-0092 made the embedder asymmetric, and
 * embedding a query on the passage side is a silent recall loss, so it is asserted twice:
 * on which method ran, and on the ranking a wrong call would reverse.
 */

const db = useUniverse();

/** A unit vector at `radians` from the first axis, in the plane of the first two. */
function atAngle(radians: number): number[] {
  const v = new Array<number>(EMBEDDING_DIM).fill(0);
  v[0] = Math.cos(radians);
  v[1] = Math.sin(radians);
  return v;
}

/** Strictly falling cosines from the first axis: chunk 0 is the best hit, chunk 3 the worst, no ties. */
const ANGLES = [0, 0.3, 0.6, 0.9];

/**
 * Qwen3's query/passage asymmetry, exaggerated until visible: the query side answers on
 * the first axis and the passage side on the second, orthogonal to it, so the two sides
 * rank the corpus in opposite orders.
 */
class Asymmetric implements Embedder {
  readonly modelName = "asymmetric-stub";
  queryCalls: string[][] = [];
  passageCalls: string[][] = [];
  async embedQuery(texts: string[]) {
    this.queryCalls.push([...texts]);
    return texts.map(() => atAngle(0));
  }
  async embedPassage(texts: string[]) {
    this.passageCalls.push([...texts]);
    return texts.map(() => atAngle(Math.PI / 2));
  }
}

/** One document per filter axis; canon carries no category or scope, as the CHECK allows. */
const DOCUMENTS = [
  {
    sourcePath: "cs/pg/mvcc.md",
    kind: "topic_source",
    category: "computer science",
    subCategory: "databases",
    scope: "topic",
    tags: ["postgresql"],
    headings: ["Snapshot isolation"],
  },
  {
    sourcePath: "_canon/ascii.md",
    kind: "spoin_canon",
    category: null,
    subCategory: null,
    scope: null,
    tags: ["ascii art"],
    headings: ["The box rule"],
  },
  {
    // Two chunks, so excluding the document removes something excluding one chunk would not.
    sourcePath: "cs/dist/consensus.md",
    kind: "topic_source",
    category: "computer science",
    subCategory: null,
    scope: "survey",
    tags: ["distributed systems"],
    headings: ["Raft", "Paxos"],
  },
] as const;

async function corpus() {
  const docs = await db
    .insert(document)
    .values(
      DOCUMENTS.map((d, i) => ({
        title: `Document ${i}`,
        source: `https://example.invalid/${i}`,
        sourcePath: d.sourcePath,
        kind: d.kind,
        category: d.category,
        subCategory: d.subCategory,
        scope: d.scope,
        contentHash: String(i).padStart(64, "0"),
        ingestedAt: new Date(),
      })),
    )
    .returning();
  const owners = [0, 1, 2, 2];
  const chunks = await db
    .insert(chunk)
    .values(
      owners.map((owner, index) => {
        const spec = DOCUMENTS[owner] as (typeof DOCUMENTS)[number];
        const heading = spec.headings[owner === 2 ? index - 2 : 0] as string;
        return {
          documentId: (docs[owner] as { id: string }).id,
          ordinal: owner === 2 ? index - 2 : 0,
          text: `Document ${owner} — ${heading}\n\nBody ${index}.`,
          heading,
          embedding: atAngle(ANGLES[index] as number),
          // From atAngle, not a model, and the stamp says so.
          embeddingModel: "fixture-at-angle",
          topicTags: [...spec.tags],
        };
      }),
    )
    .returning();
  return { docs, chunks };
}

const ids = (hits: Hit[]) => hits.map((h) => h.chunkId);

describe("search", () => {
  it("returns similarity, not distance, most similar first", async () => {
    // pgvector returns a distance; compared the intuitive way it would keep the worst.
    const { chunks } = await corpus();
    const hits = await search(db, new Asymmetric(), "anything");
    expect(ids(hits)).toEqual(chunks.map((c) => c.id));
    expect(hits.map((h) => h.score.toFixed(4))).toEqual(ANGLES.map((a) => Math.cos(a).toFixed(4)));
  });

  it("embeds the query with the query side (ADR-0092)", async () => {
    const { chunks } = await corpus();
    const embedder = new Asymmetric();
    const hits = await search(db, embedder, "how does MVCC work");
    expect(embedder.queryCalls).toEqual([["how does MVCC work"]]);
    expect(embedder.passageCalls).toEqual([]);
    // The passage side ranks this corpus in the opposite order.
    expect(hits[0]?.chunkId).toBe(chunks[0]?.id);
  });

  it("carries the document's provenance on each hit", async () => {
    const { docs, chunks } = await corpus();
    const [hit] = await search(db, new Asymmetric(), "q", { k: 1 });
    expect(hit).toMatchObject({
      chunkId: chunks[0]?.id,
      documentId: docs[0]?.id,
      documentTitle: "Document 0",
      sourcePath: "cs/pg/mvcc.md",
      kind: "topic_source",
      category: "computer science",
      subCategory: "databases",
      ordinal: 0,
      heading: "Snapshot isolation",
      topicTags: ["postgresql"],
    });
    // The header is what was embedded; a consumer that never sees it cannot tell sections apart.
    expect(hit?.text.startsWith("Document 0 — Snapshot isolation")).toBe(true);
  });

  it("limits the candidates to k", async () => {
    await corpus();
    expect(await search(db, new Asymmetric(), "q", { k: 2 })).toHaveLength(2);
  });

  it("shortens the result with a floor rather than widening the search", async () => {
    await corpus();
    const embedder = new Asymmetric();
    const floor = Math.cos(0.45);
    expect(await search(db, embedder, "q", { minScore: floor })).toHaveLength(2);
    expect(await search(db, embedder, "q", { k: 3, minScore: floor })).toHaveLength(2);
    // Task 0040's shape: top-1 above a floor, and nothing when nothing clears it.
    expect(await search(db, embedder, "q", { k: 1, minScore: 1.5 })).toEqual([]);
  });

  it("is cross-topic until the caller narrows it (ADR-0088)", async () => {
    await corpus();
    const embedder = new Asymmetric();
    const open = await search(db, embedder, "q");
    expect(new Set(open.map((h) => h.kind))).toEqual(new Set(["spoin_canon", "topic_source"]));
    expect(new Set(open.map((h) => h.documentId)).size).toBe(3);
    const canon = await search(db, embedder, "q", { kinds: ["spoin_canon"] });
    expect(canon.map((h) => h.sourcePath)).toEqual(["_canon/ascii.md"]);
    expect(await search(db, embedder, "q", { kinds: [] })).toEqual([]);
  });

  it("matches a chunk that carries any of the tags", async () => {
    await corpus();
    const hits = await search(db, new Asymmetric(), "q", {
      topicTags: ["postgresql", "distributed systems"],
    });
    expect(hits.map((h) => h.sourcePath)).toEqual([
      "cs/pg/mvcc.md",
      "cs/dist/consensus.md",
      "cs/dist/consensus.md",
    ]);
  });

  it("drops a whole document or a single chunk", async () => {
    const { docs, chunks } = await corpus();
    const embedder = new Asymmetric();
    const byDoc = await search(db, embedder, "q", { excludeDocumentIds: [docs[2]?.id as string] });
    expect(ids(byDoc)).toEqual([chunks[0]?.id, chunks[1]?.id]);
    const byChunk = await search(db, embedder, "q", { excludeChunkIds: [chunks[2]?.id as string] });
    expect(ids(byChunk)).toEqual([chunks[0]?.id, chunks[1]?.id, chunks[3]?.id]);
  });

  it("changes nothing for exclusions of something absent", async () => {
    await corpus();
    const embedder = new Asymmetric();
    const baseline = ids(await search(db, embedder, "q"));
    expect(ids(await search(db, embedder, "q", { excludeDocumentIds: [] }))).toEqual(baseline);
    expect(ids(await search(db, embedder, "q", { excludeChunkIds: [crypto.randomUUID()] }))).toEqual(
      baseline,
    );
  });

  it("ranks within an included set, and an empty set is an empty scope, not an open one", async () => {
    const { chunks } = await corpus();
    const embedder = new Asymmetric();
    const scoped = await search(db, embedder, "q", {
      includeChunkIds: [chunks[3]?.id as string, chunks[1]?.id as string],
    });
    expect(ids(scoped)).toEqual([chunks[1]?.id, chunks[3]?.id]);
    expect(await search(db, embedder, "q", { includeChunkIds: [] })).toEqual([]);
  });

  it("embeds a batch once and answers in query order", async () => {
    await corpus();
    const embedder = new Asymmetric();
    const results = await searchMany(db, embedder, ["first", "second", "third"], { k: 1 });
    expect(embedder.queryCalls).toEqual([["first", "second", "third"]]);
    expect(results.map((r) => r.length)).toEqual([1, 1, 1]);
  });

  it("does not call the model for an empty batch", async () => {
    const embedder = new Asymmetric();
    expect(await searchMany(db, embedder, [])).toEqual([]);
    expect(embedder.queryCalls).toEqual([]);
  });
});

describe("resolving grounding references", () => {
  it("resolves path#heading by join, and returns the misses", async () => {
    const { chunks } = await corpus();
    const { chunkIds, missing } = await resolveGrounding(db, [
      "cs/dist/consensus.md#Paxos",
      "cs/pg/mvcc.md#Snapshot isolation",
      "cs/pg/mvcc.md#Snapshot", // a prefix of a real heading is not that heading
      "cs/gone.md#Raft",
      "not a ref",
    ]);
    expect(chunkIds).toEqual([chunks[3]?.id, chunks[0]?.id]);
    expect(missing).toEqual(["cs/pg/mvcc.md#Snapshot", "cs/gone.md#Raft", "not a ref"]);
  });

  it("resolves a heading used twice in one document to both sections", async () => {
    const { chunks } = await corpus();
    await db
      .update(chunk)
      .set({ heading: "Raft" })
      .where(eq(chunk.id, chunks[3]?.id as string));
    const { chunkIds } = await resolveGrounding(db, ["cs/dist/consensus.md#Raft"]);
    expect(chunkIds).toEqual([chunks[2]?.id, chunks[3]?.id]);
  });

  it("answers no references with nothing", async () => {
    expect(await resolveGrounding(db, [])).toEqual({ chunkIds: [], missing: [] });
  });
});

describe("the corpus version", () => {
  it("moves when a document is added or re-ingested", async () => {
    expect(await corpusVersion(db)).toBe("0@empty");
    await corpus();
    const first = await corpusVersion(db);
    expect(first).toMatch(/^3@\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/);
    await db
      .update(document)
      .set({ ingestedAt: new Date(Date.now() + 1000) })
      .where(eq(document.sourcePath, "cs/pg/mvcc.md"));
    expect(await corpusVersion(db)).not.toBe(first);
  });
});

describe("image search", () => {
  async function catalog() {
    return db
      .insert(image)
      .values(
        [0, 0.4, 0.8].map((angle, i) => ({
          manifestPath: "nature/images.md",
          sourceUrl: `https://example.org/${i}.jpg`,
          contentHash: String(i).padStart(64, "0"),
          title: `Image ${i}`,
          description: `Description ${i}`,
          sourcePage: `https://example.org/${i}`,
          licence: "cc-by" as const,
          attribution: `Photographer ${i}`,
          category: i === 2 ? "weaving" : "shores",
          topicTags: ["shores"],
          embedding: atAngle(angle),
          embeddingModel: "fixture-at-angle",
          hostedUrl: i === 1 ? "https://cdn.example/1.jpg" : null,
          ingestedAt: new Date(),
        })),
      )
      .returning();
  }

  it("ranks by the query side and resolves the display url", async () => {
    const rows = await catalog();
    const embedder = new Asymmetric();
    const hits = await searchImages(db, embedder, "a tide pool");
    expect(embedder.queryCalls).toEqual([["a tide pool"]]);
    expect(hits.map((h) => h.imageId)).toEqual(rows.map((r) => r.id));
    expect(hits.map((h) => h.displayUrl)).toEqual([
      "https://example.org/0.jpg",
      "https://cdn.example/1.jpg",
      "https://example.org/2.jpg",
    ]);
    expect(hits[0]).toMatchObject({ attribution: "Photographer 0", licence: "cc-by" });
  });

  it("filters by category before ranking and excludes images already used", async () => {
    const rows = await catalog();
    const embedder = new Asymmetric();
    const shores = await searchImages(db, embedder, "q", {
      categories: ["shores"],
      excludeImageIds: [rows[0]?.id as string],
    });
    expect(shores.map((h) => h.title)).toEqual(["Image 1"]);
    expect(await searchImages(db, embedder, "q", { k: 1, minScore: 1.5 })).toEqual([]);
  });

  it("counts what is available to assign", async () => {
    const rows = await catalog();
    expect(await countImages(db)).toBe(3);
    expect(await countImages(db, { categories: ["shores"] })).toBe(2);
    expect(await countImages(db, { categories: ["shores"], excludeImageIds: [rows[0]?.id as string] })).toBe(
      1,
    );
    expect(await countImages(db, { categories: [] })).toBe(0);
  });
});
