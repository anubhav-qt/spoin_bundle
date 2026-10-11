import { existsSync, readFileSync } from "node:fs";
import { charCount, contentHash, markdownFiles, readFrontMatter, show } from "../front-matter.ts";
import { normalized } from "../ingest/contract.ts";
import { normalizeTopicText } from "../normalize.ts";
import { imageLicence } from "../universe/schema.ts";

/*
 * Parsing and validating one image manifest against the delivery contract (§10 of
 * docs/handoff/antigravity-corpus-authoring.md; ADR-0095, task 0040).
 *
 * Purity is the point: nothing here opens a database, loads a model or touches the
 * network, not even to check that a `source_url` resolves. That is what makes
 * `images:check` runnable while a manifest is being written, and a liveness probe would
 * destroy it; one belongs behind its own flag. Every problem in every manifest is
 * reported: a manifest is dozens of entries authored in one pass, so its mistakes arrive
 * in batches.
 */

export type ImageLicence = (typeof imageLicence.enumValues)[number];

/** The only `kind` a manifest may declare, so a corpus document saved under `images/` fails loudly. */
export const MANIFEST_KIND = "image_manifest";

/**
 * A description shorter than this is a caption or alt text, not the retrieval surface the
 * contract asks for. Loose on purpose: no length tells "Saturn" from a description that
 * retrieves a card about ring composition, so this catches the entry nobody wrote, not
 * the one written badly. The first delivered manifest's descriptions ran 397-730.
 */
export const MIN_DESCRIPTION_CHARS = 120;

/** Required on every entry; listed once so the message and the schema's NOT NULLs cannot drift. */
const REQUIRED = ["title", "description", "source_url", "source_page", "licence", "attribution"] as const;

/** One entry that satisfied the contract. No embedding: that is the runner's. */
export interface ParsedImage {
  sourceUrl: string;
  contentHash: string;
  title: string;
  description: string;
  sourcePage: string;
  licence: ImageLicence;
  attribution: string;
  topicTags: string[];
}

export interface ParsedManifest {
  manifestPath: string;
  category: string;
  subCategory: string | null;
  images: ParsedImage[];
}

export interface ManifestErrors {
  manifestPath: string;
  problems: string[];
}

/**
 * sha256 of the fields that decide what a row means, per entry rather than per file:
 * hashing the file would re-embed every entry because one description was reworded.
 * `topic_tags` is a retrieval filter, and the title and attribution are displayed, so a
 * corrected one must reach the database. `hosted_url` is deliberately absent, so a
 * reworded description never discards an upload that already happened.
 */
export function entryHash(entry: Omit<ParsedImage, "contentHash">): string {
  return contentHash(
    JSON.stringify({
      attribution: entry.attribution,
      description: entry.description,
      licence: entry.licence,
      source_page: entry.sourcePage,
      source_url: entry.sourceUrl,
      title: entry.title,
      topic_tags: entry.topicTags,
    }),
  );
}

/** Parse and validate one manifest. Never throws for bad content. */
export function parseManifest(
  manifestPath: string,
  raw: Uint8Array,
): { manifest: ParsedManifest | null; errors: ManifestErrors } {
  const errors: ManifestErrors = { manifestPath, problems: [] };
  const problems = errors.problems;
  const read = readFrontMatter(raw, problems);
  if (!read) return { manifest: null, errors };
  const { front, body } = read;

  if (body.trim()) {
    problems.push(
      "a manifest is front matter only: the text after the closing `---` would never be read, so it is an error rather than a comment",
    );
  }
  if (front.kind !== MANIFEST_KIND) {
    problems.push(`\`kind\` must be exactly \`${MANIFEST_KIND}\`, got ${show(front.kind)}`);
  }
  // On the manifest header, not per entry: repeating a category on every entry is that
  // many chances to typo one into a category of its own.
  const category = normalized(front, "category", problems, true);
  const subCategory = normalized(front, "sub_category", problems, false);
  const images = imagesOf(front, problems);

  if (problems.length > 0 || !category) return { manifest: null, errors };
  return { manifest: { manifestPath, category, subCategory, images }, errors };
}

/**
 * Every manifest under `root`, everything reported at once. A missing directory is an
 * empty delivery rather than an error: a topic with no sourceable imagery is a normal
 * outcome the contract asks to be reported (task 0040).
 */
export function parseImages(root: string): { parsed: ParsedManifest[]; failures: ManifestErrors[] } {
  const parsed: ParsedManifest[] = [];
  const failures: ManifestErrors[] = [];
  if (!existsSync(root)) return { parsed, failures };
  for (const [manifestPath, full] of markdownFiles(root)) {
    const { manifest, errors } = parseManifest(manifestPath, readFileSync(full));
    if (manifest) parsed.push(manifest);
    if (errors.problems.length > 0) failures.push(errors);
  }
  rejectCrossManifestDuplicates(parsed, failures);
  return { parsed, failures };
}

/**
 * Fail a `source_url` delivered in two manifests. `image.source_url` is globally unique,
 * so it would otherwise surface mid-ingest as a constraint name rather than as the two
 * files that disagree, and the same photograph under two subjects is exactly what a
 * per-file check cannot see.
 */
function rejectCrossManifestDuplicates(parsed: ParsedManifest[], failures: ManifestErrors[]): void {
  const seen = new Map<string, string>();
  for (const manifest of parsed) {
    for (const image of manifest.images) {
      const first = seen.get(image.sourceUrl);
      if (first === undefined) seen.set(image.sourceUrl, manifest.manifestPath);
      else if (first !== manifest.manifestPath) {
        failures.push({
          manifestPath: manifest.manifestPath,
          problems: [
            `\`source_url\` ${image.sourceUrl} was already delivered in ${first}: an image is one catalog entry, so pick the manifest it belongs in and remove the other`,
          ],
        });
      }
    }
  }
}

function imagesOf(front: Record<string, unknown>, problems: string[]): ParsedImage[] {
  const raw = front.images;
  if (raw === undefined || raw === null) {
    problems.push("`images` is missing (a manifest with no entries is not a manifest)");
    return [];
  }
  if (!Array.isArray(raw) || raw.length === 0) {
    problems.push(`\`images\` must be a non-empty list, got ${show(raw)}`);
    return [];
  }
  const images: ParsedImage[] = [];
  const seen = new Set<string>();
  raw.forEach((entry, index) => {
    const image = imageOf(entry, index, problems);
    if (!image) return;
    if (seen.has(image.sourceUrl)) {
      problems.push(
        `images[${index}] (${show(image.title)}): duplicate \`source_url\` within this manifest: ${image.sourceUrl}`,
      );
      return;
    }
    seen.add(image.sourceUrl);
    images.push(image);
  });
  return images;
}

const LICENCES = imageLicence.enumValues.join(", ");

/** One entry. Its index is in every message: a manifest has no other way to say where. */
function imageOf(entry: unknown, index: number, problems: string[]): ParsedImage | null {
  const where = `images[${index}]`;
  if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
    problems.push(`${where}: must be a mapping, got ${show(entry)}`);
    return null;
  }
  const fields = entry as Record<string, unknown>;
  const values: Partial<Record<(typeof REQUIRED)[number], string>> = {};
  for (const key of REQUIRED) {
    const value = fields[key];
    if (value === undefined || value === null) {
      problems.push(`${where}: \`${key}\` is missing (required by the contract, NOT NULL in the schema)`);
    } else if (typeof value !== "string" || !value.trim()) {
      problems.push(`${where}: \`${key}\` must be a non-empty string, got ${show(value)}`);
    } else {
      values[key] = value.trim();
    }
  }

  let licence: ImageLicence | null = null;
  if (values.licence !== undefined) {
    if ((imageLicence.enumValues as readonly string[]).includes(values.licence)) {
      licence = values.licence as ImageLicence;
    } else {
      problems.push(
        `${where}: \`licence\` ${show(values.licence)} is not in the allowlist (${LICENCES}). NonCommercial is excluded because Spoin is commercial, and NoDerivatives because serving at card width crops and resizes, a derivative work (task 0040)`,
      );
    }
  }
  const description = values.description;
  if (description !== undefined && charCount(description) < MIN_DESCRIPTION_CHARS) {
    problems.push(
      `${where}: \`description\` is ${charCount(description)} characters, under the ${MIN_DESCRIPTION_CHARS} minimum: it is the text a card's body is matched against, not alt text, so it needs to say what is IN the image and what it illustrates`,
    );
  }
  const topicTags = topicTagsOf(fields, where, problems);

  const { title, source_url, source_page, attribution } = values;
  if (!title || !source_url || !source_page || !attribution || !licence || description === undefined) {
    return null;
  }
  const image = {
    sourceUrl: source_url,
    title,
    description,
    sourcePage: source_page,
    licence,
    attribution,
    topicTags,
  };
  return { ...image, contentHash: entryHash(image) };
}

function topicTagsOf(fields: Record<string, unknown>, where: string, problems: string[]): string[] {
  const raw = fields.topic_tags;
  if (raw === undefined || raw === null) {
    problems.push(`${where}: \`topic_tags\` is missing`);
    return [];
  }
  if (!Array.isArray(raw) || raw.length === 0) {
    problems.push(`${where}: \`topic_tags\` must be a non-empty list, got ${show(raw)}`);
    return [];
  }
  const tags: string[] = [];
  for (const tag of raw) {
    if (typeof tag !== "string" || !tag.trim()) {
      problems.push(`${where}: every \`topic_tags\` entry must be a non-empty string`);
      continue;
    }
    // The normalizer prose tags go through (ADR-0093), so an image tag and a topic name
    // cannot become two vocabularies.
    const normalizedTag = normalizeTopicText(tag);
    if (!tags.includes(normalizedTag)) tags.push(normalizedTag);
  }
  return tags;
}
