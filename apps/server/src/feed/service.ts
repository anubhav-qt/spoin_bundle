import { DIFFICULTIES, type Difficulty } from "@spoin/shared/enums";
import { and, asc, eq, gt, inArray, isNull, lt, lte, or, sql } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import {
  card,
  cardStats,
  feedPlan,
  feedSlate,
  subtopic,
  userCardState,
  userSessionTopicSignal,
  userSubtopicProgress,
  userTopic,
  userTopicAffinity,
  userTopicCycle,
  userTopicDifficultyProgress,
} from "../db/schema.ts";
import type { Env } from "../env.ts";
import { loadProgress } from "../topics/progress.ts";
import { buildPlan, filterKey } from "./interleave.ts";
import { type Candidate, diversify, type Rng, rank, shuffle } from "./ranking.ts";
import { clampShares, rawWeight, shareFingerprint } from "./session-profile.ts";
import { dynamicMix, resolveMix, served as servedOf } from "./strata.ts";

/*
 * Feed serving (ADR-0010).
 *
 *   per topic:     SELECT (stratified) -> RANK (within strata) -> SLATE (~25)
 *   across topics: INTERLEAVE PLAN (session-weighted) -> page from the plan
 *
 * Hard rule 1: no model call anywhere in here or in anything it calls. A swipe is
 * ~50ms, a model call seconds; if a model seems needed here, the answer is a batch job
 * that precomputes a column. Rule two: no aggregation at request time. Every score
 * input is a column kept current elsewhere (ADR-0011), which is what keeps this under
 * 100ms with no cache layer.
 */

type Plan = typeof feedPlan.$inferSelect;
type Slate = typeof feedSlate.$inferSelect;

export type FeedPage = {
  cardIds: string[];
  /** One integer into the plan: what keeps pagination simple while the ranking underneath shifts. */
  nextPosition: number;
  /** A starved pool made this page short: the client shows an honest "more coming soon". */
  degraded: boolean;
  exhausted: boolean;
  /** Some topic on this page is on a repeat pass, which the client announces once. */
  recycling: boolean;
};

export async function page(
  db: Db,
  env: Env,
  userId: string,
  opts: { topicFilter?: string[]; position?: number; rng?: Rng } = {},
): Promise<FeedPage> {
  return db.transaction(async (tx) => {
    const plan = await ensurePlan(tx, env, userId, opts.topicFilter);
    const order = plan.topicOrder;
    if (order.length === 0)
      return { cardIds: [], nextPosition: 0, degraded: false, exhausted: true, recycling: false };

    let cursor = opts.position ?? plan.position;
    const cardIds: string[] = [];
    let degraded = false;
    // Serving a card does not make it ineligible: it stays UNSEEN until the reader acts
    // on it. So a slate rebuilt mid-page could re-pick a card just handed out; tracking
    // what went out keeps a card from appearing twice on one page.
    const served = new Set<string>();
    const slates = new Map<string, Slate>();

    // One card from each topic's slate in turn. An empty slate is skipped, not the end
    // of the page: one starved topic must not starve the others.
    let attempts = 0;
    while (cardIds.length < env.PAGE_SIZE && attempts < order.length * 2) {
      if (cursor >= order.length) cursor = 0;
      const topicId = order[cursor] as string;
      cursor += 1;
      attempts += 1;

      const slate = await ensureSlate(tx, env, userId, topicId, slates, served, opts.rng);
      if (!slate) continue;
      degraded ||= slate.degraded;
      while (slate.position < slate.cardIds.length && served.has(slate.cardIds[slate.position] as string))
        slate.position += 1;
      const next = slate.cardIds[slate.position];
      if (next === undefined) continue;
      cardIds.push(next);
      served.add(next);
      slate.position += 1;
      attempts = 0;
    }

    const topics = [...new Set(order)];
    // Short and nothing active anywhere in the plan: the true end, not a thin stretch.
    const exhausted = cardIds.length < env.PAGE_SIZE && !(await anyActive(tx, topics));
    const recycling = await anyRecycling(tx, userId, topics);

    for (const s of slates.values())
      await tx.update(feedSlate).set({ position: s.position }).where(eq(feedSlate.id, s.id));
    await tx.update(feedPlan).set({ position: cursor }).where(eq(feedPlan.id, plan.id));
    return { cardIds, nextPosition: cursor, degraded, exhausted, recycling };
  });
}

// ---------------------------------------------------------------------- plan --

async function ensurePlan(tx: Tx, env: Env, userId: string, topicFilter?: string[]): Promise<Plan> {
  const key = filterKey(topicFilter);
  const [existing] = await tx.select().from(feedPlan).where(eq(feedPlan.userId, userId));
  const shares = await topicShares(tx, env, userId, topicFilter);
  const fingerprint = shareFingerprint(shares, env.SESSION_SHARE_BUCKET);

  if (
    existing &&
    existing.filterKey === key &&
    // ADR-0055's third trigger: the session profile moved enough to reorder the feed.
    existing.shareFingerprint === fingerprint &&
    sameSet(existing.topicOrder, [...shares.keys()])
  )
    return existing;

  const values = {
    topicOrder: buildPlan(shares, env.PLAN_SIZE, env.FEED_TOPIC_RUN),
    // Reset on every rebuild, and must be: it indexes `topicOrder`, so carried across a
    // reordered list it would land on an unrelated topic. Nothing is lost: which card
    // each topic serves next lives in its slate, which a rebuild never touches.
    position: 0,
    filterKey: key,
    shareFingerprint: fingerprint,
  };
  // An upsert: a double-fired first fetch reaches here twice with no plan.
  const [plan] = await tx
    .insert(feedPlan)
    .values({ userId, ...values })
    .onConflictDoUpdate({ target: feedPlan.userId, set: { ...values, updatedAt: sql`now()` } })
    .returning();
  if (!plan) throw new Error("feed plan upsert returned nothing");
  return plan;
}

const sameSet = (a: string[], b: string[]) => {
  const left = new Set(a);
  const right = new Set(b);
  return left.size === right.size && [...left].every((x) => right.has(x));
};

/**
 * Each topic's share of the plan, summing to 1 (ADR-0055), from the CURRENT session's
 * engagement; long-run affinity still feeds per-card ranking, a separate concern. One
 * row per subscription, no aggregation: the score is kept current at ingest.
 */
async function topicShares(tx: Tx, env: Env, userId: string, topicFilter?: string[]) {
  const rows = await tx
    .select({
      topicId: userTopic.topicId,
      score: userSessionTopicSignal.score,
      lastEventAt: userSessionTopicSignal.lastEventAt,
    })
    .from(userTopic)
    .leftJoin(
      userSessionTopicSignal,
      and(
        eq(userSessionTopicSignal.userId, userTopic.userId),
        eq(userSessionTopicSignal.topicId, userTopic.topicId),
      ),
    )
    .where(
      and(
        eq(userTopic.userId, userId),
        topicFilter?.length ? inArray(userTopic.topicId, topicFilter) : undefined,
      ),
    );
  const now = Date.now();
  const raw = new Map<string, number>();
  for (const r of rows) {
    // Expiry is checked here too, not only at ingest: the write-side reset fires on the
    // next event, so a reader back the next morning would otherwise get yesterday's profile.
    const stale = !r.lastEventAt || now - r.lastEventAt.getTime() > env.SESSION_WINDOW_SECONDS * 1000;
    raw.set(r.topicId, rawWeight(stale ? 0 : (r.score ?? 0), env));
  }
  return clampShares(raw, { lo: env.SESSION_SHARE_FLOOR, hi: env.SESSION_SHARE_CEILING });
}

// --------------------------------------------------------------------- slate --

async function ensureSlate(
  tx: Tx,
  env: Env,
  userId: string,
  topicId: string,
  slates: Map<string, Slate>,
  served: Set<string>,
  rng?: Rng,
): Promise<Slate | null> {
  let slate = slates.get(topicId);
  if (!slate) {
    [slate] = await tx
      .select()
      .from(feedSlate)
      .where(and(eq(feedSlate.userId, userId), eq(feedSlate.topicId, topicId)));
    if (slate) slates.set(topicId, slate);
  }
  if (slate && slate.expiresAt > new Date() && slate.position < slate.cardIds.length) return slate;
  const built = await buildSlate(tx, env, userId, topicId, { rng, exclude: served });
  if (built) slates.set(topicId, built);
  return built;
}

/**
 * One topic's eligible cards ranked into a ~25-card slate. Expensive, deliberately:
 * this is the layer where invalidation is rare. Slates refill independently, and
 * topics the reader is not in cost nothing to re-rank.
 */
export async function buildSlate(
  db: Db | Tx,
  env: Env,
  userId: string,
  topicId: string,
  opts: { rng?: Rng; exclude?: Set<string> } = {},
): Promise<Slate | null> {
  const { rng = Math.random, exclude = new Set<string>() } = opts;
  const now = new Date();
  const tier = (await loadProgress(db, userId, topicId))?.currentDifficulty ?? "beginner";
  const [previous] = await db
    .select({ degraded: feedSlate.degraded })
    .from(feedSlate)
    .where(and(eq(feedSlate.userId, userId), eq(feedSlate.topicId, topicId)));
  const affinity = await topicAffinity(db, userId, topicId);

  // One query per stratum: what makes the mix exact rather than emergent. Ranking
  // happens within a stratum, never across.
  const byTier = new Map<Difficulty, Candidate[]>();
  for (const d of DIFFICULTIES) {
    let found = await candidates(db, env, { userId, topicId, difficulty: d, affinity, eligibleOnly: true });
    // Empty: either the difficulty has nothing, or everything is DEFERRED waiting for
    // the cycle to turn over. Only the second advances it.
    if (found.length === 0 && (await maybeAdvanceCycle(db, userId, topicId, d)))
      found = await candidates(db, env, { userId, topicId, difficulty: d, affinity, eligibleOnly: true });
    byTier.set(
      d,
      found.filter((c) => !exclude.has(c.cardId)),
    );
  }

  let recycled: Set<Difficulty>;
  if (![...byTier.values()].some((c) => c.length > 0)) {
    // Everything eligible was consumed this page or this pass: refill from the whole
    // active pool so the feed goes on rather than ending abruptly.
    for (const d of DIFFICULTIES) {
      const all = await candidates(db, env, {
        userId,
        topicId,
        difficulty: d,
        affinity,
        eligibleOnly: false,
      });
      const unblocked = all.filter((c) => !exclude.has(c.cardId));
      byTier.set(d, unblocked.length > 0 ? unblocked : all);
    }
    recycled = new Set(DIFFICULTIES);
  } else {
    const cycles = await cyclesOf(db, userId, topicId);
    recycled = new Set(DIFFICULTIES.filter((d) => (cycles.get(d) ?? 0) > 0));
  }

  const outcome = resolveMix(env.SLATE_SIZE, tier, new Map([...byTier].map(([d, c]) => [d, c.length])), {
    wasDegraded: previous?.degraded ?? false,
    poolLow: env.POOL_LOW,
    poolHigh: env.POOL_HIGH,
    mix: dynamicMix(tier, await tierReadFraction(db, userId, topicId, tier), {
      start: env.MIX_RAMP_START,
      end: env.MIX_RAMP_END,
    }),
  });

  const picked: Candidate[] = [];
  for (const fill of outcome.fills) {
    const pool = byTier.get(fill.difficulty) ?? [];
    const n = servedOf(fill);
    // A repeat pass: ranking's inputs have stopped meaning anything (coverage need is
    // ~0 everywhere, and quality and recency give the same order every cycle), so a
    // re-read would feel like a replay. Shuffle; `diversify` still stops clumping.
    if (recycled.has(fill.difficulty)) picked.push(...shuffle([...pool], rng).slice(0, n));
    else picked.push(...rank(pool, env, { now, limit: n, rng }));
  }
  if (picked.length === 0) return null;

  const values = {
    cardIds: diversify(picked).map((c) => c.cardId),
    position: 0,
    degraded: outcome.degraded,
    expiresAt: new Date(now.getTime() + env.SLATE_TTL_SECONDS * 1000),
  };
  const [slate] = await db
    .insert(feedSlate)
    .values({ userId, topicId, ...values })
    .onConflictDoUpdate({
      target: [feedSlate.userId, feedSlate.topicId],
      set: { ...values, updatedAt: sql`now()` },
    })
    .returning();
  if (!slate) throw new Error("feed slate upsert returned nothing");
  return slate;
}

// ---------------------------------------------------------------- candidates --

async function topicAffinity(db: Db | Tx, userId: string, topicId: string): Promise<number> {
  const [row] = await db
    .select({ affinity: userTopicAffinity.affinity })
    .from(userTopicAffinity)
    .where(and(eq(userTopicAffinity.userId, userId), eq(userTopicAffinity.topicId, topicId)));
  return row?.affinity ?? 1;
}

/** Active cards of one stratum, in curriculum order. */
const active = (topicId: string, difficulty: Difficulty) =>
  and(eq(card.topicId, topicId), eq(card.difficulty, difficulty), eq(card.status, "active"));

/**
 * Eligible = UNSEEN, or DEFERRED in an earlier cycle. SEEN never returns: it counts
 * toward the gate. DEFERRED comes back once the cycle turns, which is what makes
 * scrolling past free. Without `eligibleOnly`, the whole active pool (a repeat pass).
 */
async function candidates(
  db: Db | Tx,
  env: Env,
  q: { userId: string; topicId: string; difficulty: Difficulty; affinity: number; eligibleOnly: boolean },
): Promise<Candidate[]> {
  const currentCycle = sql`coalesce((select ${userTopicCycle.cycle} from ${userTopicCycle}
    where ${userTopicCycle.userId} = ${q.userId} and ${userTopicCycle.topicId} = ${q.topicId}
      and ${userTopicCycle.difficulty} = ${q.difficulty}), 0)`;
  const eligible = or(
    isNull(userCardState.state),
    eq(userCardState.state, "unseen"),
    and(eq(userCardState.state, "deferred"), lt(userCardState.deferredCycle, currentCycle)),
  );
  const rows = await db
    .select({
      cardId: card.id,
      subtopicId: card.subtopicId,
      createdAt: card.createdAt,
      cardQuality: sql<number>`coalesce(${cardStats.quality}, 0)`,
      // An untouched subtopic is maximally needy: exactly what should surface. Float
      // on both sides of the division, so it is never a decimal.
      coverageNeed: sql<number>`coalesce(1.0::float8 - ${userSubtopicProgress.seenCount}::float8
        / nullif(${userSubtopicProgress.totalCount}, 0)::float8, 1.0::float8)`,
      archetype: card.archetype,
      subtopicPosition: subtopic.position,
    })
    .from(card)
    .innerJoin(subtopic, eq(subtopic.id, card.subtopicId))
    .leftJoin(cardStats, eq(cardStats.cardId, card.id))
    .leftJoin(userCardState, and(eq(userCardState.cardId, card.id), eq(userCardState.userId, q.userId)))
    .leftJoin(
      userSubtopicProgress,
      and(eq(userSubtopicProgress.subtopicId, card.subtopicId), eq(userSubtopicProgress.userId, q.userId)),
    )
    .where(and(active(q.topicId, q.difficulty), q.eligibleOnly ? eligible : undefined))
    .orderBy(asc(subtopic.position), asc(card.createdAt))
    // A generous multiple of the slate: something to choose between without pulling the corpus into memory.
    .limit(env.SLATE_SIZE * 6);
  return rows.map((r) => ({ ...r, topicAffinity: q.affinity }));
}

/** The reader's cycle per difficulty for one topic; no row is cycle 0, the first pass. */
async function cyclesOf(db: Db | Tx, userId: string, topicId: string): Promise<Map<Difficulty, number>> {
  const rows = await db
    .select({ difficulty: userTopicCycle.difficulty, cycle: userTopicCycle.cycle })
    .from(userTopicCycle)
    .where(and(eq(userTopicCycle.userId, userId), eq(userTopicCycle.topicId, topicId)));
  return new Map(rows.map((r) => [r.difficulty, r.cycle]));
}

/**
 * Turns this difficulty over so its DEFERRED pile is eligible again. Both conditions
 * are required: nothing UNSEEN left (fresh material always outranks a repeat), and
 * something deferred at the current cycle (otherwise the difficulty is starved, not
 * finished, and bumping the counter would hide a pool that should be filled).
 * Called only when a stratum came back empty, so two EXISTS on a path about to serve nothing.
 */
async function maybeAdvanceCycle(db: Db | Tx, userId: string, topicId: string, d: Difficulty) {
  const current = (await cyclesOf(db, userId, topicId)).get(d) ?? 0;
  const base = (state: ReturnType<typeof and>) =>
    db
      .select({ id: card.id })
      .from(card)
      .leftJoin(userCardState, and(eq(userCardState.cardId, card.id), eq(userCardState.userId, userId)))
      .where(and(active(topicId, d), state))
      .limit(1);

  const [unseen] = await base(or(isNull(userCardState.state), eq(userCardState.state, "unseen")));
  if (unseen) return false;
  const [deferred] = await base(
    and(eq(userCardState.state, "deferred"), lte(userCardState.deferredCycle, current)),
  );
  if (!deferred) return false;

  await db
    .insert(userTopicCycle)
    .values({ userId, topicId, difficulty: d, cycle: current + 1 })
    .onConflictDoUpdate({
      target: [userTopicCycle.userId, userTopicCycle.topicId, userTopicCycle.difficulty],
      set: { cycle: sql`${userTopicCycle.cycle} + 1`, updatedAt: sql`now()` },
    });
  return true;
}

/**
 * How much of this topic's `tier` the reader has read: the ramp's input. A row read
 * on the aggregate ingest keeps current, never a count. No row, or a tier with no
 * cards, reads as 0: the ramp's own start.
 */
async function tierReadFraction(db: Db | Tx, userId: string, topicId: string, tier: Difficulty) {
  const [row] = await db
    .select({ seen: userTopicDifficultyProgress.seenCount, total: userTopicDifficultyProgress.totalCount })
    .from(userTopicDifficultyProgress)
    .where(
      and(
        eq(userTopicDifficultyProgress.userId, userId),
        eq(userTopicDifficultyProgress.topicId, topicId),
        eq(userTopicDifficultyProgress.difficulty, tier),
      ),
    );
  return row?.total ? row.seen / row.total : 0;
}

async function anyActive(tx: Tx, topicIds: string[]): Promise<boolean> {
  const [hit] = await tx
    .select({ id: card.id })
    .from(card)
    .where(and(inArray(card.topicId, topicIds), eq(card.status, "active")))
    .limit(1);
  return hit !== undefined;
}

/** A cycle row exists only once a difficulty has turned over, so a reader on fresh content costs nothing here. */
async function anyRecycling(tx: Tx, userId: string, topicIds: string[]): Promise<boolean> {
  const [hit] = await tx
    .select({ cycle: userTopicCycle.cycle })
    .from(userTopicCycle)
    .where(
      and(
        eq(userTopicCycle.userId, userId),
        inArray(userTopicCycle.topicId, topicIds),
        gt(userTopicCycle.cycle, 0),
      ),
    )
    .limit(1);
  return hit !== undefined;
}
