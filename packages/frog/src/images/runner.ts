import { eq, inArray } from "drizzle-orm";
import type { Embedder } from "../embeddings.ts";
import type { Universe } from "../universe/db.ts";
import { image } from "../universe/schema.ts";
import { type ManifestErrors, type ParsedImage, type ParsedManifest, parseImages } from "./contract.ts";

/*
 * Validated manifests written into the image catalog, with the prose ingester's posture:
 * validate everything before writing anything, a failing manifest does not stop the
 * others, and an unchanged entry is skipped.
 *
 * Re-hosting is not here. `image.hosted_url` is nullable so it lands later as a backfill
 * over existing rows, not as a re-ingest that re-embeds the catalog to write one URL per
 * row; until then the renderer serves `source_url`.
 */

/** As the prose ingester's: a description is far shorter than a section, so this is comfortable, not tuned. */
const EMBED_BATCH = 64;

export interface ImageIngestReport {
  scannedManifests: number;
  failedManifests: number;
  /** Entries written for the first time. */
  created: number;
  /** Entries whose hash changed, rewritten and re-embedded. */
  updated: number;
  /** Entries whose hash matched: no embedding, no write. */
  unchanged: number;
  /**
   * Rows their manifest no longer lists, removed: the manifest is the truth and the
   * database follows it, so an image the author withdrew stops being assignable.
   */
  removed: number;
  errors: ManifestErrors[];
}

export const imageSummary = (r: ImageIngestReport): string =>
  `manifests=${r.scannedManifests} failed=${r.failedManifests} created=${r.created} updated=${r.updated} unchanged=${r.unchanged} removed=${r.removed}`;

export interface ManifestOutcome {
  created: number;
  updated: number;
  unchanged: number;
  removed: number;
}

/**
 * Reconcile one manifest's entries against the catalog. Embedding is batched across
 * everything that changed: per-call overhead dominates a single short description.
 */
export async function ingestManifest(
  db: Universe,
  manifest: ParsedManifest,
  embedder: Embedder,
  opts: { force?: boolean } = {},
): Promise<ManifestOutcome> {
  const rows = await db
    .select({ id: image.id, sourceUrl: image.sourceUrl, contentHash: image.contentHash })
    .from(image)
    .where(eq(image.manifestPath, manifest.manifestPath));
  const existing = new Map(rows.map((row) => [row.sourceUrl, row]));
  const delivered = new Set(manifest.images.map((entry) => entry.sourceUrl));

  const stale = rows.filter((row) => !delivered.has(row.sourceUrl)).map((row) => row.id);
  if (stale.length > 0) await db.delete(image).where(inArray(image.id, stale));

  const changed: ParsedImage[] = [];
  let unchanged = 0;
  for (const entry of manifest.images) {
    const row = existing.get(entry.sourceUrl);
    if (row && row.contentHash === entry.contentHash && !opts.force) unchanged += 1;
    else changed.push(entry);
  }
  if (changed.length === 0) return { created: 0, updated: 0, unchanged, removed: stale.length };

  // Before any write, so a model failure cannot leave rows whose hash claims they are
  // current, and on the PASSAGE side: a description is what is searched (ADR-0092).
  const vectors: number[][] = [];
  for (let start = 0; start < changed.length; start += EMBED_BATCH) {
    const batch = changed.slice(start, start + EMBED_BATCH).map((entry) => entry.description);
    vectors.push(...(await embedder.embedPassage(batch)));
  }

  let created = 0;
  let updated = 0;
  const now = new Date();
  for (const [index, entry] of changed.entries()) {
    const fields = {
      manifestPath: manifest.manifestPath,
      contentHash: entry.contentHash,
      title: entry.title,
      description: entry.description,
      sourcePage: entry.sourcePage,
      licence: entry.licence,
      attribution: entry.attribution,
      category: manifest.category,
      subCategory: manifest.subCategory,
      topicTags: [...entry.topicTags],
      embedding: vectors[index] as number[],
      embeddingModel: embedder.modelName,
      ingestedAt: now,
    };
    const row = existing.get(entry.sourceUrl);
    if (row) {
      await db.update(image).set(fields).where(eq(image.id, row.id));
      updated += 1;
    } else {
      // A `source_url` claimed by another manifest is caught by the contract first; the
      // unique constraint is the backstop, not the check.
      await db.insert(image).values({ sourceUrl: entry.sourceUrl, ...fields });
      created += 1;
    }
  }
  return { created, updated, unchanged, removed: stale.length };
}

/** Validate every manifest under `root`, then ingest the ones that passed. */
export async function ingestImages(
  db: Universe,
  root: string,
  embedder: Embedder,
  opts: { force?: boolean; log?: (line: string) => void } = {},
): Promise<ImageIngestReport> {
  const { parsed, failures } = parseImages(root);
  const report: ImageIngestReport = {
    scannedManifests: parsed.length + failures.length,
    failedManifests: failures.length,
    created: 0,
    updated: 0,
    unchanged: 0,
    removed: 0,
    errors: failures,
  };
  // A manifest that lost a `source_url` to another is in both lists; writing it would
  // trip the unique constraint the contract check exists to get ahead of.
  const failing = new Set(failures.map((f) => f.manifestPath));
  for (const manifest of parsed.filter((m) => !failing.has(m.manifestPath))) {
    const outcome = await ingestManifest(db, manifest, embedder, opts);
    report.created += outcome.created;
    report.updated += outcome.updated;
    report.unchanged += outcome.unchanged;
    report.removed += outcome.removed;
    opts.log?.(
      `ingested ${manifest.manifestPath} (+${outcome.created} ~${outcome.updated} =${outcome.unchanged} -${outcome.removed})`,
    );
  }
  return report;
}
