import { contentHash, isMapping, readFrontMatter, show } from "../front-matter.ts";
import { type DocumentScope, scopeOf } from "../ingest/contract.ts";

/*
 * Parsing and validating one authored curriculum against the delivery contract
 * (docs/handoff/antigravity-curriculum-authoring.md; architecture in
 * docs/architecture/authored-curriculum.md). A curriculum is consumed by a deterministic
 * projection into topics and subtopics, and nothing here calls a model or opens a
 * database, so `curriculum:check` runs while one is being written. Every problem in a
 * file is reported, never just the first.
 *
 * frog imports neither the server nor the shared contract (ADR-0087), so the two
 * vocabularies and the `target_cards` band below are mirrored by value, and a server
 * test keeps them equal: the tiers mirror `Difficulty`, the card types `CardType`, and
 * the band the CHECK `target_cards BETWEEN 5 AND 25` on `subtopic`, so a value outside
 * it fails here rather than at the projection's INSERT.
 */

export const TIERS = ["beginner", "intermediate", "advanced"] as const;
export const CARD_TYPES = ["prose", "image", "code", "diagram", "comparison", "ascii"] as const;
export const MIN_TARGET_CARDS = 5;
export const MAX_TARGET_CARDS = 25;

export type Tier = (typeof TIERS)[number];

/**
 * `"a/b.md#Some Heading"` to `["a/b.md", "Some Heading"]`, or null if malformed. Split on
 * the FIRST `#`: a path cannot contain one and a heading routinely can. The one parser of
 * this format, shared by the validator, the projection and retrieval.
 */
export function splitGroundingRef(ref: string): [string, string] | null {
  const at = ref.indexOf("#");
  if (at < 0) return null;
  const path = ref.slice(0, at).trim();
  const heading = ref.slice(at + 1).trim();
  return path && heading ? [path, heading] : null;
}

/** One tier's plan: how many cards, the mix, and which corpus sections ground them. */
export interface ParsedTier {
  tier: Tier;
  targetCards: number;
  /** Only the types the author named; a missing type is zero. The values sum to `targetCards`. */
  cardTypes: Record<string, number>;
  /**
   * The sections this tier's cards may be written from, as `<path>#<exact ## heading>`.
   * A scope, not a citation: retrieval ranks within it per card, so too narrow is the
   * real failure (two sections grounding twenty cards). Never empty, or the tier would
   * fall through to an open corpus-wide query.
   */
  grounding: string[];
}

/** One curriculum unit; becomes a subtopic group spanning its tiers. */
export interface ParsedSubtopic {
  title: string;
  description: string;
  prerequisites: string[];
  tiers: ParsedTier[];
}

export interface ParsedCurriculum {
  sourcePath: string;
  contentHash: string;
  topic: string;
  description: string;
  scope: DocumentScope;
  subtopics: ParsedSubtopic[];
}

export interface CurriculumErrors {
  /** The file's identity in the curricula tree (`rust/curriculum.md`), as the `curriculum` row names it. */
  sourcePath: string;
  problems: string[];
}

/**
 * Every distinct document a subtopic's tiers ground on, in first-seen order. Derived,
 * never authored, which is what keeps it from disagreeing with `grounding`.
 */
export function sourcePaths(subtopic: ParsedSubtopic): string[] {
  const paths: string[] = [];
  for (const tier of subtopic.tiers) {
    for (const ref of tier.grounding) {
      const split = splitGroundingRef(ref);
      if (split && !paths.includes(split[0])) paths.push(split[0]);
    }
  }
  return paths;
}

const at = (where: string, message: string) => (where ? `${where}: ${message}` : message);

/**
 * Parse and validate one curriculum. Everything checkable from the file alone is checked
 * here; the one cross-file check, every grounding reference naming a real section, is the
 * runner's, because only it has the corpus tree.
 */
export function parseCurriculum(
  sourcePath: string,
  raw: Uint8Array,
): { curriculum: ParsedCurriculum | null; errors: CurriculumErrors } {
  const errors: CurriculumErrors = { sourcePath, problems: [] };
  const problems = errors.problems;
  const read = readFrontMatter(raw, problems);
  if (!read) return { curriculum: null, errors };
  const { front, body } = read;

  if (body.trim()) {
    problems.push(
      "content after the closing `---`: a curriculum is data and has no prose body; move any notes into a comment or delete them",
    );
  }

  const topic = requiredString(front, "topic", "", problems);
  const description = requiredString(front, "description", "", problems);
  // A file still saying `is_survey` was written against the old contract; naming the
  // replacement is the actual work, so it stands in for "`scope` is missing".
  if ("is_survey" in front) {
    problems.push("`is_survey` was replaced by `scope`: `survey` for true, `topic` or `one_shot` for false");
  }
  const scope = "is_survey" in front && !("scope" in front) ? null : scopeOf(front, problems);
  const subtopics = subtopicsOf(front, problems);

  if (problems.length > 0 || !topic || !description || !scope || !subtopics) {
    return { curriculum: null, errors };
  }
  return {
    curriculum: { sourcePath, contentHash: contentHash(raw), topic, description, scope, subtopics },
    errors,
  };
}

function requiredString(
  mapping: Record<string, unknown>,
  key: string,
  where: string,
  problems: string[],
): string | null {
  const value = mapping[key];
  if (value === undefined || value === null) {
    problems.push(at(where, `\`${key}\` is missing (required by the contract)`));
    return null;
  }
  if (typeof value !== "string" || !value.trim()) {
    problems.push(at(where, `\`${key}\` must be a non-empty string, got ${show(value)}`));
    return null;
  }
  return value.trim();
}

function subtopicsOf(front: Record<string, unknown>, problems: string[]): ParsedSubtopic[] | null {
  const raw = front.subtopics;
  if (raw === undefined || raw === null) {
    problems.push("`subtopics` is missing (required: a non-empty list)");
    return null;
  }
  if (!Array.isArray(raw) || raw.length === 0) {
    problems.push(`\`subtopics\` must be a non-empty list, got ${show(raw)}`);
    return null;
  }

  const parsed: ParsedSubtopic[] = [];
  const titles = new Set<string>();
  raw.forEach((entry, index) => {
    const subtopic = subtopicOf(entry, index, problems);
    if (!subtopic) return;
    if (titles.has(subtopic.title)) {
      // The projection matches on (topic, title, tier): two rows with one title collapse into one.
      problems.push(
        `subtopic ${index}: duplicate title ${show(subtopic.title)}: titles are the projection's match key and must be unique within a curriculum`,
      );
      return;
    }
    titles.add(subtopic.title);
    parsed.push(subtopic);
  });
  if (parsed.length === 0) return null;

  checkPrerequisites(parsed, problems);
  return parsed;
}

function subtopicOf(entry: unknown, index: number, problems: string[]): ParsedSubtopic | null {
  const fallback = `subtopic ${index}`;
  if (!isMapping(entry)) {
    problems.push(`${fallback}: must be a mapping, got ${show(entry)}`);
    return null;
  }
  const title = requiredString(entry, "title", fallback, problems);
  const where = title ? `subtopic ${show(title)}` : fallback;
  const description = requiredString(entry, "description", where, problems);
  const prerequisites = stringList(entry, "prerequisites", where, problems, true);
  const tiers = tiersOf(entry, where, problems);

  if ("sources" in entry) {
    // A file still carrying the old field was written against the old contract, and
    // every tier in it lacks the `grounding` that replaced it.
    problems.push(
      at(
        where,
        "`sources` was replaced by per-tier `grounding`: move each path to the tier(s) that use it, as `<path>#<exact ## heading>`",
      ),
    );
  }
  if (!title || !description || !prerequisites || !tiers) return null;
  return { title, description, prerequisites, tiers };
}

function stringList(
  entry: Record<string, unknown>,
  key: string,
  where: string,
  problems: string[],
  allowEmpty: boolean,
): string[] | null {
  if (!(key in entry)) {
    problems.push(at(where, `\`${key}\` is missing (required by the contract)`));
    return null;
  }
  const raw = entry[key];
  if (!Array.isArray(raw)) {
    problems.push(at(where, `\`${key}\` must be a list, got ${show(raw)}`));
    return null;
  }
  if (raw.length === 0 && !allowEmpty) {
    problems.push(at(where, `\`${key}\` must not be empty`));
    return null;
  }
  const values: string[] = [];
  for (const item of raw) {
    if (typeof item !== "string" || !item.trim()) {
      problems.push(at(where, `\`${key}\` entries must be non-empty strings, got ${show(item)}`));
      continue;
    }
    values.push(item.trim());
  }
  return values;
}

function tiersOf(entry: Record<string, unknown>, where: string, problems: string[]): ParsedTier[] | null {
  const raw = entry.tiers;
  if (raw === undefined || raw === null) {
    problems.push(at(where, "`tiers` is missing (a map of tier -> plan)"));
    return null;
  }
  if (!isMapping(raw) || Object.keys(raw).length === 0) {
    problems.push(at(where, `\`tiers\` must be a non-empty mapping, got ${show(raw)}`));
    return null;
  }
  const tiers: ParsedTier[] = [];
  for (const [name, plan] of Object.entries(raw)) {
    if (!(TIERS as readonly string[]).includes(name)) {
      problems.push(at(where, `unknown tier ${show(name)}: must be one of ${TIERS.join(", ")}`));
      continue;
    }
    const parsed = tierPlan(name as Tier, plan, where, problems);
    if (parsed) tiers.push(parsed);
  }
  return tiers.length > 0 ? tiers : null;
}

const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value);

function tierPlan(tier: Tier, plan: unknown, where: string, problems: string[]): ParsedTier | null {
  const here = `${where}, tier ${show(tier)}`;
  if (!isMapping(plan)) {
    problems.push(`${here}: must be a mapping with \`target_cards\` and \`card_types\``);
    return null;
  }

  const rawTarget = plan.target_cards;
  let targetCards: number | null = null;
  if (!isCount(rawTarget)) {
    problems.push(`${here}: \`target_cards\` must be an integer, got ${show(rawTarget)}`);
  } else if (rawTarget < MIN_TARGET_CARDS || rawTarget > MAX_TARGET_CARDS) {
    problems.push(
      `${here}: \`target_cards\` is ${rawTarget}, outside the ${MIN_TARGET_CARDS}-${MAX_TARGET_CARDS} band the database enforces`,
    );
  } else {
    targetCards = rawTarget;
  }

  const cardTypes = cardTypesOf(plan, here, problems);
  const grounding = groundingOf(plan, here, problems);
  if (targetCards === null || !cardTypes || !grounding) return null;

  const total = Object.values(cardTypes).reduce((sum, n) => sum + n, 0);
  if (total !== targetCards) {
    problems.push(`${here}: \`card_types\` sums to ${total}, not \`target_cards\` (${targetCards})`);
    return null;
  }
  return { tier, targetCards, cardTypes, grounding };
}

/**
 * The tier's declared corpus scope. Only the shape is checked here; whether the file and
 * its heading exist is the runner's job. A section named twice is collapsed, not
 * rejected: a copy-paste slip with an obvious intent.
 */
function groundingOf(plan: Record<string, unknown>, here: string, problems: string[]): string[] | null {
  const refs = stringList(plan, "grounding", here, problems, false);
  if (!refs) return null;
  const seen: string[] = [];
  let ok = true;
  for (const ref of refs) {
    if (!splitGroundingRef(ref)) {
      problems.push(
        `${here}: grounding entry ${show(ref)} is not \`<path relative to corpus/>#<exact ## heading>\`. Headings often contain \`: \`, so the whole entry must be QUOTED in YAML or it parses as a mapping.`,
      );
      ok = false;
      continue;
    }
    if (!seen.includes(ref)) seen.push(ref);
  }
  return ok ? seen : null;
}

function cardTypesOf(
  plan: Record<string, unknown>,
  here: string,
  problems: string[],
): Record<string, number> | null {
  const raw = plan.card_types;
  if (!isMapping(raw) || Object.keys(raw).length === 0) {
    problems.push(`${here}: \`card_types\` must be a non-empty mapping`);
    return null;
  }
  const quotas: Record<string, number> = {};
  let ok = true;
  for (const [name, count] of Object.entries(raw)) {
    if (!(CARD_TYPES as readonly string[]).includes(name)) {
      problems.push(`${here}: unknown card type ${show(name)}: must be one of ${CARD_TYPES.join(", ")}`);
      ok = false;
      continue;
    }
    if (!isCount(count) || count < 0) {
      problems.push(`${here}: card type ${show(name)} must be a non-negative integer, got ${show(count)}`);
      ok = false;
      continue;
    }
    quotas[name] = count;
  }
  return ok ? quotas : null;
}

/** `prerequisites` must name titles in this file, and the graph must be acyclic. */
function checkPrerequisites(subtopics: ParsedSubtopic[], problems: string[]): void {
  const titles = new Set(subtopics.map((s) => s.title));
  const edges = new Map<string, string[]>();
  for (const subtopic of subtopics) {
    const resolved: string[] = [];
    for (const prerequisite of subtopic.prerequisites) {
      if (prerequisite === subtopic.title) {
        problems.push(`subtopic ${show(subtopic.title)}: lists itself as a prerequisite`);
      } else if (!titles.has(prerequisite)) {
        problems.push(
          `subtopic ${show(subtopic.title)}: prerequisite ${show(prerequisite)} is not a subtopic in this curriculum`,
        );
      } else {
        resolved.push(prerequisite);
      }
    }
    edges.set(subtopic.title, resolved);
  }
  const cycle = firstCycle(edges);
  if (cycle) problems.push(`prerequisite cycle: ${cycle.join(" -> ")}: the graph must be a DAG`);
}

/** One cycle as an ordered path, or null: a depth-first search with three-colour marking. */
function firstCycle(edges: Map<string, string[]>): string[] | null {
  const colour = new Map<string, "white" | "grey" | "black">([...edges.keys()].map((k) => [k, "white"]));
  const visit = (node: string, path: string[]): string[] | null => {
    colour.set(node, "grey");
    path.push(node);
    for (const next of edges.get(node) ?? []) {
      if (colour.get(next) === "grey") return [...path.slice(path.indexOf(next)), next];
      if (colour.get(next) === "white") {
        const found = visit(next, path);
        if (found) return found;
      }
    }
    path.pop();
    colour.set(node, "black");
    return null;
  };
  for (const start of edges.keys()) {
    if (colour.get(start) === "white") {
      const found = visit(start, []);
      if (found) return found;
    }
  }
  return null;
}
