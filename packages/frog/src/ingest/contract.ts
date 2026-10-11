import { charCount, contentHash, readFrontMatter, show } from "../front-matter.ts";
import { normalizeTopicText } from "../normalize.ts";
import { documentKind, documentScope } from "../universe/schema.ts";

/*
 * Parsing and validating one corpus document against the ingestion contract
 * (docs/handoff/antigravity-corpus-authoring.md). Pure: no database, no model, which is
 * what lets `corpus:check` run while the corpus is being written.
 *
 * Every problem in every document is reported, never just the first. A corpus drifts in
 * batches: the first real audit found 18 documents missing `title` and 26 with an
 * unparseable `source_date`, which a fail-fast validator would have surfaced as dozens
 * of separate runs (task 0038, Phase 2).
 */

export type DocumentKind = (typeof documentKind.enumValues)[number];
export type DocumentScope = (typeof documentScope.enumValues)[number];

/**
 * `## ` at the start of a line. One section, one chunk, and deliberately no
 * sub-splitter: a section is the author's judgment about where one idea ends, and a
 * recursive splitter would overrule it with machinery that has read less of the
 * material than they have. That holds only while sections stay chunk-sized, hence the
 * enforced limit below.
 */
const SECTION = /^## +(.+?)[ \t]*$/gm;

/**
 * A section over this fails the document (owner's decision, 2026-09-05: 512 tokens).
 *
 * Characters, not tokens, on purpose: counting real tokens would make the check need the
 * Qwen3 tokenizer, a model download, and stop it being the cheap offline thing an author
 * runs. Calibrated, not guessed: the corpus measured 4.58 characters per token under
 * Qwen3's own tokenizer, so 2200 is about 512 tokens, and the proxy disagreed with a true
 * 512-token cut on 6 of 358 real sections, all borderline.
 */
export const MAX_SECTION_CHARS = 2200;

/**
 * `YYYY-MM-DD`, `YYYY-MM` or `YYYY`, widened to the first instant of the period. A bare
 * year is honest for material sourced from practice and postmortems, where demanding a
 * day would make the author invent a precision the source does not have.
 */
const SOURCE_DATE = /^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$/;

/** One `##` section: the chunk-to-be. */
export interface ParsedSection {
  heading: string;
  text: string;
}

/** A document that satisfied the contract. No embedding: parsing is pure, embedding is the runner's. */
export interface ParsedDocument {
  sourcePath: string;
  contentHash: string;
  title: string;
  kind: DocumentKind;
  source: string;
  category: string | null;
  subCategory: string | null;
  scope: DocumentScope | null;
  sourceDate: Date | null;
  topicTags: string[];
  sections: ParsedSection[];
}

/** Every contract violation in one document. `sourcePath` is its database identity, so an error and a row name one thing. */
export interface DocumentErrors {
  sourcePath: string;
  problems: string[];
}

/** Parse and validate one document. Never throws for bad content: a malformed document is data the caller wants in full. */
export function parseDocument(
  sourcePath: string,
  raw: Uint8Array,
): { document: ParsedDocument | null; errors: DocumentErrors } {
  const errors: DocumentErrors = { sourcePath, problems: [] };
  const problems = errors.problems;
  const read = readFrontMatter(raw, problems);
  if (!read) return { document: null, errors };
  const { front, body } = read;

  const kind = kindOf(front, problems);
  const title = requiredString(front, "title", problems);
  const source = requiredString(front, "source", problems);
  const sourceDate = sourceDateOf(front, problems);
  const sections = sectionsOf(body, problems);

  // Mirrors the CHECK on `document` (ADR-0091) rather than replacing it: the database is
  // the guarantee, and this is the half that can name the file and the field.
  let category: string | null = null;
  let subCategory: string | null = null;
  let scope: DocumentScope | null = null;
  if (kind === "topic_source") {
    category = normalized(front, "category", problems, true);
    subCategory = normalized(front, "sub_category", problems, false);
    scope = scopeOf(front, problems);
  } else if ("category" in front || "scope" in front) {
    problems.push(
      "spoin_canon must not carry `category` or `scope`: canon sits outside the subject hierarchy (ADR-0091)",
    );
  }
  const topicTags = topicTagsOf(front, problems, kind === "topic_source");

  if (problems.length > 0 || !kind || !title || !source) return { document: null, errors };
  return {
    document: {
      sourcePath,
      contentHash: contentHash(raw),
      title,
      kind,
      source,
      category,
      subCategory,
      scope,
      sourceDate,
      topicTags,
      sections,
    },
    errors,
  };
}

export function requiredString(
  front: Record<string, unknown>,
  key: string,
  problems: string[],
): string | null {
  const value = front[key];
  if (value === undefined || value === null) {
    problems.push(`\`${key}\` is missing (required by the contract, NOT NULL in the schema)`);
    return null;
  }
  if (typeof value !== "string" || !value.trim()) {
    problems.push(`\`${key}\` must be a non-empty string, got ${show(value)}`);
    return null;
  }
  return value.trim();
}

/**
 * A hierarchy field, normalized the way tags are. One normalizer across tags, category
 * and sub-category (ADR-0091) is what stops "Computer Science" and "computer-science"
 * becoming two categories in the column the intake step offers back as options.
 */
export function normalized(
  front: Record<string, unknown>,
  key: string,
  problems: string[],
  required: boolean,
): string | null {
  if (!(key in front)) {
    if (required) problems.push(`\`${key}\` is required for topic_source documents (ADR-0091)`);
    return null;
  }
  const value = front[key];
  if (typeof value !== "string" || !value.trim()) {
    problems.push(`\`${key}\` must be a non-empty string, got ${show(value)}`);
    return null;
  }
  return normalizeTopicText(value);
}

function kindOf(front: Record<string, unknown>, problems: string[]): DocumentKind | null {
  const raw = front.kind;
  if (raw === undefined || raw === null) {
    problems.push("`kind` is missing (must be exactly `spoin_canon` or `topic_source`)");
    return null;
  }
  if (!(documentKind.enumValues as readonly unknown[]).includes(raw)) {
    problems.push(
      `\`kind\` must be exactly \`spoin_canon\` or \`topic_source\`, got ${show(raw)}: a typo here would otherwise be a silent third kind nothing retrieves (ADR-0088)`,
    );
    return null;
  }
  return raw as DocumentKind;
}

const SCOPES = documentScope.enumValues.map((s) => `\`${s}\``).join(", ");

export function scopeOf(front: Record<string, unknown>, problems: string[]): DocumentScope | null {
  const raw = front.scope;
  if (raw === undefined || raw === null) {
    problems.push(`\`scope\` is required (${SCOPES})`);
    return null;
  }
  if (!(documentScope.enumValues as readonly unknown[]).includes(raw)) {
    problems.push(`\`scope\` must be one of ${SCOPES}, got ${show(raw)}`);
    return null;
  }
  return raw as DocumentScope;
}

function sourceDateOf(front: Record<string, unknown>, problems: string[]): Date | null {
  const raw = front.source_date;
  if (raw === undefined || raw === null) return null;
  // An unquoted `2024` arrives as a number.
  const match =
    typeof raw === "string" || typeof raw === "number" ? SOURCE_DATE.exec(String(raw).trim()) : null;
  if (match) {
    const [year, month, day] = [Number(match[1]), Number(match[2] ?? 1), Number(match[3] ?? 1)];
    const date = new Date(Date.UTC(year, month - 1, day));
    // Date.UTC rolls 2024-02-30 over into March; a real date round-trips.
    if (date.getUTCMonth() === month - 1 && date.getUTCDate() === day) return date;
  }
  problems.push(`\`source_date\` must be YYYY-MM-DD, YYYY-MM or YYYY, got ${show(raw)}`);
  return null;
}

function topicTagsOf(front: Record<string, unknown>, problems: string[], required: boolean): string[] {
  const raw = front.topic_tags;
  if (raw === undefined || raw === null) {
    if (required) problems.push("`topic_tags` is required for topic_source documents");
    return [];
  }
  if (!Array.isArray(raw)) {
    problems.push(`\`topic_tags\` must be a list, got ${show(raw)}`);
    return [];
  }
  const tags: string[] = [];
  for (const entry of raw) {
    if (typeof entry !== "string") {
      problems.push(`\`topic_tags\` entries must be strings, got ${show(entry)}`);
      continue;
    }
    const tag = normalizeTopicText(entry);
    if (tag && !tags.includes(tag)) tags.push(tag);
  }
  return tags;
}

/**
 * The body split on `##` headings. Text before the first one fails the document (owner's
 * decision, 2026-09-05): a chunk is shown to a model without its neighbours, so a
 * paragraph belonging to no section is either lost or smuggled into a chunk it does not
 * describe. An H1 line is the one exception, since it repeats `title`, which every
 * chunk's header already carries.
 */
function sectionsOf(body: string, problems: string[]): ParsedSection[] {
  const matches = [...body.matchAll(SECTION)];
  const first = matches[0];
  if (!first) {
    problems.push("no `##` sections: the ingester chunks on `##` headings");
    return [];
  }

  const preamble = body
    .slice(0, first.index)
    .split(/\r\n|\r|\n/)
    .filter((line) => !line.trimStart().startsWith("# "))
    .join("\n")
    .trim();
  if (preamble) {
    problems.push(
      `${charCount(preamble)} characters of prose before the first \`##\` heading (${show(preamble.slice(0, 80).replaceAll("\n", " "))}...): every chunk must belong to a section, so move this into a section or delete it`,
    );
  }

  const sections: ParsedSection[] = [];
  matches.forEach((match, index) => {
    const end = matches[index + 1]?.index ?? body.length;
    const heading = (match[1] ?? "").trim();
    const text = body.slice(match.index + match[0].length, end).trim();
    if (!text) {
      problems.push(`section ${show(heading)} has no body`);
      return;
    }
    const length = charCount(text);
    if (length > MAX_SECTION_CHARS) {
      // Nothing splits this for the author: an oversized section becomes one chunk that
      // wins a retrieval slot and then spends the prompt on material only partly relevant.
      problems.push(
        `section ${show(heading)} is ${length} characters, over the ${MAX_SECTION_CHARS} limit (~512 tokens): one section is one chunk and nothing splits it for you, so break this into two or more \`##\` sections, each self-contained`,
      );
      return;
    }
    sections.push({ heading, text });
  });
  return sections;
}
