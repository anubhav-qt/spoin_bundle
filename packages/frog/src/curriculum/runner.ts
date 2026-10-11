import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { eq } from "drizzle-orm";
import { show } from "../front-matter.ts";
import { parseDocument } from "../ingest/contract.ts";
import type { Universe } from "../universe/db.ts";
import { curriculum, curriculumSubtopic } from "../universe/schema.ts";
import { closestMatch } from "./close-match.ts";
import {
  type CurriculumErrors,
  type ParsedCurriculum,
  parseCurriculum,
  sourcePaths,
  splitGroundingRef,
} from "./contract.ts";

/*
 * The authored curricula, validated and ingested. Two separable halves: `validateCurricula`
 * is pure and adds the one cross-file check (every grounding reference names a real `##`
 * section of a real corpus document), and `ingestCurricula` writes the valid ones,
 * idempotent by content hash as the corpus ingester is (ADR-0088). A failing file never
 * stops the others: a failure is a work item to hand back, not a crash.
 */

/** One file per topic: `<curricula>/<topic slug>/curriculum.md`; the canonical name is its `topic` field. */
const CURRICULUM_FILE = "curriculum.md";

function curriculumFiles(root: string): string[] {
  if (!existsSync(root)) return [];
  return readdirSync(root)
    .sort()
    .filter((dir) => {
      const file = join(root, dir, CURRICULUM_FILE);
      return existsSync(file) && statSync(file).isFile();
    })
    .map((dir) => `${dir}/${CURRICULUM_FILE}`);
}

/** Validate every curriculum without a database: the ones that passed, and one entry per failing file. */
export function validateCurricula(
  curriculaRoot: string,
  corpusRoot: string,
): { passed: ParsedCurriculum[]; failures: CurriculumErrors[] } {
  const passed: ParsedCurriculum[] = [];
  const failures: CurriculumErrors[] = [];
  // Shared across the run: tiers name several sections of one document, and several
  // tiers name the same document, so each is parsed once.
  const headings = new Map<string, string[] | null>();
  for (const sourcePath of curriculumFiles(curriculaRoot)) {
    const { curriculum: parsed, errors } = parseCurriculum(
      sourcePath,
      readFileSync(join(curriculaRoot, sourcePath)),
    );
    if (parsed) checkGroundingExists(parsed, corpusRoot, errors.problems, headings);
    if (parsed && errors.problems.length === 0) passed.push(parsed);
    else failures.push(errors);
  }
  return { passed, failures };
}

/**
 * Every grounding reference must name a real section, checked with the same parser the
 * ingester chunks with rather than by searching the file for the heading text. A
 * substring search would pass `#Foo` against `## Foobar`, or match a `##` line inside a
 * code fence that never becomes a chunk; agreeing with the chunker is the point, because
 * a reference that validates here must resolve to a row after ingestion.
 */
function checkGroundingExists(
  parsed: ParsedCurriculum,
  corpusRoot: string,
  problems: string[],
  cache: Map<string, string[] | null>,
): void {
  for (const subtopic of parsed.subtopics) {
    for (const tier of subtopic.tiers) {
      const where = `subtopic ${show(subtopic.title)}, tier ${show(tier.tier)}`;
      for (const ref of tier.grounding) {
        const split = splitGroundingRef(ref);
        if (!split) continue; // the contract already checked the shape
        const [path, heading] = split;
        const known = documentHeadings(corpusRoot, path, cache);
        if (!known) {
          // Distinct from a missing heading: the author's next move is different.
          problems.push(
            `${where}: grounding document ${show(path)} does not exist under the corpus, or does not satisfy the corpus contract (run \`corpus:check\`)`,
          );
        } else if (!known.includes(heading)) {
          // Hand-copied long strings: the likely failure is a typo or a truncation, so
          // naming the near miss turns a delivery round-trip into a one-line fix.
          const near = closestMatch(heading, known);
          problems.push(
            `${where}: ${path} has no \`## ${heading}\` section${near ? `, did you mean ${show(near)}?` : ""}`,
          );
        }
      }
    }
  }
}

function documentHeadings(corpusRoot: string, path: string, cache: Map<string, string[] | null>) {
  if (!cache.has(path)) {
    const file = join(corpusRoot, path);
    let headings: string[] | null = null;
    if (existsSync(file) && statSync(file).isFile()) {
      const { document } = parseDocument(path, readFileSync(file));
      headings = document?.sections.map((s) => s.heading) ?? null;
    }
    cache.set(path, headings);
  }
  return cache.get(path) ?? null;
}

/** What one run did. `failed` and `unchanged` stay separate numbers (CLAUDE.md). */
export interface CurriculumIngestReport {
  scanned: number;
  ingested: number;
  unchanged: number;
  failed: number;
  errors: CurriculumErrors[];
}

export const curriculumSummary = (r: CurriculumIngestReport): string =>
  `scanned=${r.scanned} ingested=${r.ingested} unchanged=${r.unchanged} failed=${r.failed}`;

/**
 * Write one curriculum and its subtopics; false, touching nothing, when the hash is
 * unchanged. The caller owns the transaction: a revision keeps the curriculum row and
 * its id and replaces only its subtopics, as a document revision replaces its chunks.
 */
export async function ingestCurriculum(db: Universe, parsed: ParsedCurriculum): Promise<boolean> {
  const [existing] = await db
    .select({ id: curriculum.id, contentHash: curriculum.contentHash })
    .from(curriculum)
    .where(eq(curriculum.sourcePath, parsed.sourcePath));
  if (existing && existing.contentHash === parsed.contentHash) return false;

  const fields = {
    contentHash: parsed.contentHash,
    topicName: parsed.topic,
    description: parsed.description,
    scope: parsed.scope,
    ingestedAt: new Date(),
  };
  let curriculumId: string;
  if (existing) {
    curriculumId = existing.id;
    await db.delete(curriculumSubtopic).where(eq(curriculumSubtopic.curriculumId, curriculumId));
    await db.update(curriculum).set(fields).where(eq(curriculum.id, curriculumId));
  } else {
    const [created] = await db
      .insert(curriculum)
      .values({ sourcePath: parsed.sourcePath, ...fields })
      .returning({ id: curriculum.id });
    curriculumId = (created as { id: string }).id;
  }

  await db.insert(curriculumSubtopic).values(
    parsed.subtopics.map((s, ordinal) => ({
      curriculumId,
      ordinal,
      title: s.title,
      description: s.description,
      prerequisites: [...s.prerequisites],
      sourcePaths: sourcePaths(s),
      tiers: Object.fromEntries(
        s.tiers.map((t) => [
          t.tier,
          { target_cards: t.targetCards, card_types: { ...t.cardTypes }, grounding: [...t.grounding] },
        ]),
      ),
    })),
  );
  return true;
}

/** Validate every curriculum, then ingest the ones that passed. */
export async function ingestCurricula(
  db: Universe,
  curriculaRoot: string,
  corpusRoot: string,
): Promise<CurriculumIngestReport> {
  const { passed, failures } = validateCurricula(curriculaRoot, corpusRoot);
  const report: CurriculumIngestReport = {
    scanned: passed.length + failures.length,
    ingested: 0,
    unchanged: 0,
    failed: failures.length,
    errors: failures,
  };
  for (const parsed of passed) {
    if (await ingestCurriculum(db, parsed)) report.ingested += 1;
    else report.unchanged += 1;
  }
  return report;
}
