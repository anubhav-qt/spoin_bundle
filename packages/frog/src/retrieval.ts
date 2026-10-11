import {
  and,
  arrayOverlaps,
  asc,
  cosineDistance,
  count,
  eq,
  inArray,
  max,
  notInArray,
  type SQL,
  sql,
} from "drizzle-orm";
import { splitGroundingRef } from "./curriculum/contract.ts";
import type { Embedder } from "./embeddings.ts";
import type { ImageLicence } from "./images/contract.ts";
import type { DocumentKind } from "./ingest/contract.ts";
import type { Universe } from "./universe/db.ts";
import { chunk, document, image } from "./universe/schema.ts";

/*
 * Search over `the_spoin_universe` (ADR-0089; ADR-0088 for why the filters exist but are
 * off by default). Search and nothing else: packing hits into a prompt against a budget
 * is prompt work and belongs to the caller, and an image assignment is a top-1 lookup
 * that is not prompt assembly at all.
 *
 * Queries embed with `embedQuery`; the corpus was embedded with `embedPassage`. ADR-0092
 * made the embedder asymmetric because getting this backwards is a silent recall loss,
 * not an error, and the tests assert which side is called.
 *
 * There is no ANN index on `chunk.embedding`, deliberately: at this corpus size a
 * sequential scan is fast and EXACT, while HNSW is approximate, and an index added before
 * measuring would make retrieval numbers reflect index recall rather than embedding
 * quality (rag-design-space 3.6).
 */

/**
 * Candidates per query when the caller does not say. Wider than a prompt carries:
 * packing cuts to a budget, and a reranker would want a wide set to rerank.
 */
export const DEFAULT_K = 20;

/** One retrieved chunk, with its document's provenance, so citing or auditing it needs no second query. */
export interface Hit {
  chunkId: string;
  documentId: string;
  /**
   * Cosine similarity in [-1, 1], NOT the distance pgvector returns: higher is closer,
   * so a `minScore` floor reads as "at least this similar".
   */
  score: number;
  /**
   * The stored text, contextual header included. Do not strip the `<title> — <heading>`
   * line or add another: it is what was embedded, and the reading model should see it.
   */
  text: string;
  ordinal: number;
  heading: string | null;
  topicTags: string[];
  documentTitle: string;
  source: string;
  sourcePath: string;
  kind: DocumentKind;
  category: string | null;
  subCategory: string | null;
}

/**
 * Every filter is available and none is on by default (ADR-0088): retrieval is
 * cross-topic, because a PostgreSQL card may legitimately ground itself in
 * distributed-systems material.
 */
export interface SearchOptions {
  k?: number;
  kinds?: DocumentKind[];
  /** Overlap, not containment: a chunk carrying any of these matches. */
  topicTags?: string[];
  /** Applied after the database returns its `k`: it shortens the result, it never widens the search. */
  minScore?: number;
  excludeDocumentIds?: string[];
  excludeChunkIds?: string[];
  /**
   * Rank WITHIN these chunks, the mechanism behind a curriculum's declared scope
   * (authored-curriculum.md §10). An EMPTY list is an empty scope and returns nothing,
   * distinct from absent, which is unscoped: collapsing the two would turn a curriculum
   * whose references all failed to resolve into a silent open query.
   */
  includeChunkIds?: string[];
}

/** Top-`k` chunks for one query, most similar first. Task 0040's "top-1 above a floor" is `k: 1` with a `minScore`. */
export async function search(
  db: Universe,
  embedder: Embedder,
  query: string,
  opts: SearchOptions = {},
): Promise<Hit[]> {
  return (await searchMany(db, embedder, [query], opts))[0] ?? [];
}

/**
 * `search` for several queries with one embedding call, answered in query order so a
 * caller can zip them back. The database is still queried once per query: a top-k per
 * vector is not one statement, and at this size batching the scan buys nothing.
 */
export async function searchMany(
  db: Universe,
  embedder: Embedder,
  queries: string[],
  opts: SearchOptions = {},
): Promise<Hit[][]> {
  if (queries.length === 0) return [];
  if (opts.includeChunkIds?.length === 0) return queries.map(() => []);
  // The query side: see the module note.
  const vectors = await embedder.embedQuery(queries);

  const filters: SQL[] = [];
  if (opts.kinds) filters.push(opts.kinds.length > 0 ? inArray(document.kind, opts.kinds) : sql`false`);
  if (opts.topicTags) filters.push(arrayOverlaps(chunk.topicTags, opts.topicTags));
  if (opts.includeChunkIds) filters.push(inArray(chunk.id, opts.includeChunkIds));
  if (opts.excludeDocumentIds?.length) filters.push(notInArray(document.id, opts.excludeDocumentIds));
  if (opts.excludeChunkIds?.length) filters.push(notInArray(chunk.id, opts.excludeChunkIds));

  const results: Hit[][] = [];
  for (const vector of vectors) {
    const distance = cosineDistance(chunk.embedding, vector);
    const rows = await db
      .select({
        chunkId: chunk.id,
        documentId: document.id,
        score: sql<number>`1 - (${distance})`.mapWith(Number),
        text: chunk.text,
        ordinal: chunk.ordinal,
        heading: chunk.heading,
        topicTags: chunk.topicTags,
        documentTitle: document.title,
        source: document.source,
        sourcePath: document.sourcePath,
        kind: document.kind,
        category: document.category,
        subCategory: document.subCategory,
      })
      .from(chunk)
      .innerJoin(document, eq(document.id, chunk.documentId))
      .where(and(...filters))
      .orderBy(distance)
      .limit(opts.k ?? DEFAULT_K);
    const { minScore } = opts;
    results.push(minScore === undefined ? rows : rows.filter((hit) => hit.score >= minScore));
  }
  return results;
}

/**
 * Authored `<path>#<heading>` references to chunk ids, plus the references that missed.
 * A join on `(document.source_path, chunk.heading)` rather than a prefix match on
 * `chunk.text`, which would resolve `#Ownership` to `## Ownership Foundations`. A heading
 * that occurs twice in one document resolves to both sections.
 *
 * Misses are returned, not dropped: a reference that stopped resolving (a renamed
 * heading, a corpus not re-ingested since) is the difference between "scoped narrowly"
 * and "the scope evaporated", and the caller has to be able to say which.
 */
export async function resolveGrounding(
  db: Universe,
  refs: string[],
): Promise<{ chunkIds: string[]; missing: string[] }> {
  const keyed = refs.map((ref) => ({ ref, key: splitGroundingRef(ref) }));
  const wanted = keyed.flatMap(({ key }) => (key ? [key] : []));
  if (wanted.length === 0) return { chunkIds: [], missing: [...refs] };

  const rows = await db
    .select({ sourcePath: document.sourcePath, heading: chunk.heading, id: chunk.id })
    .from(chunk)
    .innerJoin(document, eq(document.id, chunk.documentId))
    .where(
      sql`(${document.sourcePath}, ${chunk.heading}) IN (${sql.join(
        wanted.map(([path, heading]) => sql`(${path}, ${heading})`),
        sql`, `,
      )})`,
    )
    .orderBy(asc(document.sourcePath), asc(chunk.ordinal));
  const found = new Map<string, string[]>();
  for (const row of rows) {
    const key = JSON.stringify([row.sourcePath, row.heading]);
    found.set(key, [...(found.get(key) ?? []), row.id]);
  }

  const chunkIds: string[] = [];
  const missing: string[] = [];
  for (const { ref, key } of keyed) {
    const ids = key ? found.get(JSON.stringify(key)) : undefined;
    if (!ids) missing.push(ref);
    else for (const id of ids) if (!chunkIds.includes(id)) chunkIds.push(id);
  }
  return { chunkIds, missing };
}

/**
 * A token that changes whenever the corpus does, for a caller's cache key. A
 * long-running worker caches retrieval while the corpus is re-ingested underneath it, so
 * a key on the subtopic alone would serve context from a revised or retracted document.
 *
 * Cheap on purpose: a count and a max. `ingested_at` moves whenever a document's hash
 * changes and the count when one is added or deleted, so every edit the ingester makes
 * is visible. Not a content hash of the corpus, an accepted trade.
 */
export async function corpusVersion(db: Universe): Promise<string> {
  const [row] = await db
    .select({
      documents: count(),
      // Microseconds, in UTC: a JS Date would drop the last three digits.
      latest: sql<
        string | null
      >`to_char(${max(document.ingestedAt)} AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`,
    })
    .from(document);
  return `${row?.documents ?? 0}@${row?.latest ?? "empty"}`;
}

/**
 * One catalog image, with everything needed to attach and display it. Not a `Hit`: a
 * chunk is evidence a card is written FROM, an image an asset it SHOWS and must
 * attribute, and one shape for both would leave half its fields null on every row.
 */
export interface ImageHit {
  imageId: string;
  /** Cosine similarity, as `Hit.score`; recorded per assignment so a floor can be set from a measured distribution. */
  score: number;
  title: string;
  description: string;
  /** `hostedUrl` once re-hosted, `sourceUrl` until then, resolved here so no renderer learns the fallback. */
  displayUrl: string;
  sourceUrl: string;
  sourcePage: string;
  licence: ImageLicence;
  /** Must be displayed: CC BY and CC BY-SA make it a licence condition, so it rides on the hit. */
  attribution: string;
  category: string;
  subCategory: string | null;
  topicTags: string[];
}

export interface ImageSearchOptions {
  k?: number;
  /**
   * Filters BEFORE ranking. Unlike prose, which is cross-topic because an unexpected
   * supporting passage is a feature, an unexpected photograph is a wrong image that
   * looks sourced.
   */
  categories?: string[];
  minScore?: number;
  /**
   * How uniqueness works, as a query rather than caller-held state: two cards drafted at
   * once cannot collide, because the second simply asks for the next best (task 0040).
   */
  excludeImageIds?: string[];
}

function imageFilters(opts: { categories?: string[]; excludeImageIds?: string[] }): SQL[] {
  const filters: SQL[] = [];
  if (opts.categories) {
    filters.push(opts.categories.length > 0 ? inArray(image.category, opts.categories) : sql`false`);
  }
  if (opts.excludeImageIds?.length) filters.push(notInArray(image.id, opts.excludeImageIds));
  return filters;
}

/** Top-`k` catalog images for one query, a drafted card's own text, most similar first (ADR-0095). */
export async function searchImages(
  db: Universe,
  embedder: Embedder,
  query: string,
  opts: ImageSearchOptions = {},
): Promise<ImageHit[]> {
  const [vector] = await embedder.embedQuery([query]);
  if (!vector) return [];
  const distance = cosineDistance(image.embedding, vector);
  const rows = await db
    .select({
      imageId: image.id,
      score: sql<number>`1 - (${distance})`.mapWith(Number),
      title: image.title,
      description: image.description,
      hostedUrl: image.hostedUrl,
      sourceUrl: image.sourceUrl,
      sourcePage: image.sourcePage,
      licence: image.licence,
      attribution: image.attribution,
      category: image.category,
      subCategory: image.subCategory,
      topicTags: image.topicTags,
    })
    .from(image)
    .where(and(...imageFilters(opts)))
    .orderBy(distance)
    .limit(opts.k ?? DEFAULT_K);
  const hits = rows.map(({ hostedUrl, ...row }) => ({ ...row, displayUrl: hostedUrl ?? row.sourceUrl }));
  const { minScore } = opts;
  return minScore === undefined ? hits : hits.filter((hit) => hit.score >= minScore);
}

/**
 * How many images are available to assign: the ceiling a planner reads. A card planned
 * as an image card whose image cannot be resolved is rejected and regenerated, which
 * plans another image card; capping the plan at real availability makes that loop
 * unreachable, and a cap has to come from a count, not a top-k (task 0040).
 */
export async function countImages(
  db: Universe,
  opts: { categories?: string[]; excludeImageIds?: string[] } = {},
): Promise<number> {
  const [row] = await db
    .select({ n: count() })
    .from(image)
    .where(and(...imageFilters(opts)));
  return row?.n ?? 0;
}
