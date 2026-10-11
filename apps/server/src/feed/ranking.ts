import type { Env } from "../env.ts";

/*
 * Linear ranking plus epsilon-greedy exploration (ADR-0010). At this scale a weighted
 * linear score beats a model: debuggable, tunable and explainable when the output
 * looks wrong, and there is no training data yet anyway. Weights live in the env.
 */

/** A source of uniform numbers in [0, 1); `Math.random` unless a test pins it. */
export type Rng = () => number;

export type RankKnobs = Pick<
  Env,
  "RANK_W_QUALITY" | "RANK_W_AFFINITY" | "RANK_W_COVERAGE" | "RANK_W_FRESHNESS" | "RANK_EPSILON"
>;

export type Candidate = {
  cardId: string;
  subtopicId: string;
  createdAt: Date;
  /**
   * Engagement RATE across all users, never a total: raw counts make old cards
   * permanently dominant and new ones permanently invisible.
   */
  cardQuality: number;
  /** This user's long-run weight for the card's topic. */
  topicAffinity: number;
  /** Prefers under-read subtopics, which quietly drives a reader toward the coverage gate. */
  coverageNeed: number;
  /** Used only by `diversify`, never a score input: a slate-ordering concern. */
  archetype: string[];
  /** The concept's place in the tier's curriculum; lower is earlier. */
  subtopicPosition: number;
};

/** A card is "new" for about a fortnight. */
const FRESHNESS_HALF_LIFE_MS = 14 * 24 * 3600 * 1000;

/** Exponential decay in [0, 1]. */
export function freshness(createdAt: Date, now: Date): number {
  const age = now.getTime() - createdAt.getTime();
  return age <= 0 ? 1 : 0.5 ** (age / FRESHNESS_HALF_LIFE_MS);
}

export const score = (c: Candidate, k: RankKnobs, now: Date): number =>
  k.RANK_W_QUALITY * c.cardQuality +
  k.RANK_W_AFFINITY * c.topicAffinity +
  k.RANK_W_COVERAGE * c.coverageNeed +
  k.RANK_W_FRESHNESS * freshness(c.createdAt, now);

/** Fisher-Yates, in place. */
export function shuffle<T>(items: T[], rng: Rng = Math.random): T[] {
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [items[i], items[j]] = [items[j] as T, items[i] as T];
  }
  return items;
}

/**
 * The top candidates in curriculum order, with a fixed slice reserved for exploration.
 * Serving only top scores is a cold-start death spiral: new cards get no impressions,
 * so no quality signal, so never rank. The exploration picks are shuffled in, not
 * appended, since past where most readers stop is a slower way of never showing them.
 */
export function rank(
  candidates: Candidate[],
  k: RankKnobs,
  opts: { now: Date; limit: number; rng?: Rng },
): Candidate[] {
  const { now, limit, rng = Math.random } = opts;
  if (limit <= 0 || candidates.length === 0) return [];
  const scored = candidates.map((c) => ({ c, s: score(c, k, now) }));
  scored.sort((a, b) => a.c.subtopicPosition - b.c.subtopicPosition || b.s - a.s);
  const ordered = scored.map((x) => x.c);

  const explore = Math.min(Math.trunc(limit * k.RANK_EPSILON), Math.max(ordered.length - limit, 0));
  const exploit = limit - explore;
  const chosen = ordered.slice(0, exploit);
  if (explore > 0) {
    chosen.push(...shuffle(ordered.slice(exploit), rng).slice(0, explore));
    shuffle(chosen, rng);
  }
  return chosen.slice(0, limit);
}

/** The web's `getPrimaryArchetype`, for back-to-back comparison only: never stored, never scored. */
function primaryArchetype(tags: string[]): string {
  const code = tags.includes("code");
  const diagram = tags.includes("diagram");
  if (code && diagram) return "combo";
  if (code) return "code";
  if (diagram) return "diagram";
  if (tags.includes("comparison")) return "comparison";
  return "default";
}

/**
 * Spreads consecutive cards across subtopics, and more weakly across archetypes. Five
 * excellent cards from one subtopic make a worse page than five good ones from five,
 * and that depends on what came before, so no per-card score can say it. Never drops
 * a card: when variety runs out, quantity wins.
 */
export function diversify(candidates: Candidate[]): Candidate[] {
  const remaining = [...candidates];
  const out: Candidate[] = [];
  let lastSubtopic: string | null = null;
  let lastArchetype: string | null = null;
  while (remaining.length > 0) {
    const pick =
      remaining.find(
        (c) => c.subtopicId !== lastSubtopic && primaryArchetype(c.archetype) !== lastArchetype,
      ) ??
      remaining.find((c) => c.subtopicId !== lastSubtopic) ??
      (remaining[0] as Candidate);
    remaining.splice(remaining.indexOf(pick), 1);
    out.push(pick);
    lastSubtopic = pick.subtopicId;
    lastArchetype = primaryArchetype(pick.archetype);
  }
  return out;
}
