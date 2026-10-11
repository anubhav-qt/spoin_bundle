import type { ProgressOut } from "@spoin/shared";
import { type Difficulty, difficultyRank, isTierless, type TopicScope } from "@spoin/shared/enums";
import { and, eq, isNull, or, sql } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import { card, subtopic, topic, userCardState, userTopicProgress } from "../db/schema.ts";

/*
 * Tier progression (ADR-0009). Shared by the progress endpoint and the quiz's start
 * check, so the two agree on what is unlocked without duplicating the latch write.
 *
 * A tierless topic (survey, one-shot; ADR-0106) has one quiz, kept in the advanced
 * slot of each per-tier array, so content-model.md's "mastered" stays one definition:
 * tier_content_complete[advanced] AND tier_quiz_passed[advanced].
 */

type Progress = typeof userTopicProgress.$inferSelect;

/** ADR-0032: only the tiers strictly below the entry tier start unlocked; the entry tier earns its quiz. */
export const entryTierUnlock = (entry: Difficulty): boolean[] =>
  [0, 1, 2].map((rank) => rank < difficultyRank(entry));

/** The slot a tierless topic's one quiz is recorded in. */
export const TIERLESS_QUIZ_TIER: Difficulty = "advanced";

export async function topicScope(db: Db | Tx, topicId: string): Promise<TopicScope> {
  const [row] = await db.select({ scope: topic.scope }).from(topic).where(eq(topic.id, topicId));
  return row?.scope ?? "topic";
}

export async function loadProgress(db: Db | Tx, userId: string, topicId: string): Promise<Progress | null> {
  const [row] = await db
    .select()
    .from(userTopicProgress)
    .where(and(eq(userTopicProgress.userId, userId), eq(userTopicProgress.topicId, topicId)));
  return row ?? null;
}

/**
 * Coverage of the WEAKEST subtopic in the tier, or in the whole topic when `tier` is
 * null. The gate is "80% of every subtopic", so the thinnest one governs: an average
 * would let one well-read subtopic carry an unopened one.
 */
export async function tierCoverage(
  db: Db | Tx,
  userId: string,
  topicId: string,
  tier: Difficulty | null,
): Promise<number> {
  const rows = await db
    .select({
      total: sql<number>`count(${card.id})::int`,
      seen: sql<number>`(count(${userCardState.cardId}) filter (where ${userCardState.state} = 'seen'))::int`,
    })
    .from(subtopic)
    .leftJoin(card, eq(card.subtopicId, subtopic.id))
    .leftJoin(userCardState, and(eq(userCardState.cardId, card.id), eq(userCardState.userId, userId)))
    .where(
      and(
        eq(subtopic.topicId, topicId),
        tier ? eq(subtopic.difficulty, tier) : undefined,
        or(isNull(card.id), eq(card.status, "active")),
      ),
    )
    .groupBy(subtopic.id);
  const ratios = rows.filter((r) => r.total > 0).map((r) => r.seen / r.total);
  return ratios.length ? Math.min(...ratios) : 0;
}

export type Snapshot = {
  progress: Progress | null;
  scope: TopicScope;
  /** The tier shown to the reader: always `beginner` on a tierless topic. */
  tier: Difficulty;
  /** The slot the quiz this snapshot gates is recorded in. */
  quizTier: Difficulty;
  coverage: number;
  unlocked: boolean;
  mastered: boolean;
};

/**
 * The tier a reader is shown. A tierless topic ignores what is stored: a requested
 * topic is followed at the requester's entry tier before the harness decides its scope.
 */
export const shownTier = (scope: TopicScope, stored: Difficulty | null | undefined): Difficulty =>
  isTierless(scope) ? "beginner" : (stored ?? "beginner");

/** Read-only: no latch write, so any reader can use it. */
export async function progressSnapshot(
  db: Db | Tx,
  gate: number,
  userId: string,
  topicId: string,
): Promise<Snapshot> {
  const progress = await loadProgress(db, userId, topicId);
  const scope = await topicScope(db, topicId);
  const tierless = isTierless(scope);
  const tier = shownTier(scope, progress?.currentDifficulty);
  const quizTier = tierless ? TIERLESS_QUIZ_TIER : tier;
  const coverage = await tierCoverage(db, userId, topicId, tierless ? null : tier);
  const alreadyUnlocked = Boolean(progress?.tierUnlocked[difficultyRank(quizTier)]);
  return {
    progress,
    scope,
    tier,
    quizTier,
    coverage,
    unlocked: alreadyUnlocked || coverage >= gate,
    mastered: progress?.masteredAt != null,
  };
}

/**
 * The snapshot, plus the unlock latch written the first time it is earned. Once
 * unlocked it stays unlocked: recomputing would let new cards landing in the tier
 * drop a user from 8/10 (unlocked) to 8/20 (locked) with nothing they did.
 */
export async function ensureUnlockLatched(
  db: Db,
  gate: number,
  userId: string,
  topicId: string,
): Promise<Snapshot> {
  const snap = await progressSnapshot(db, gate, userId, topicId);
  const rank = difficultyRank(snap.quizTier);
  if (snap.unlocked && snap.progress && !snap.progress.tierUnlocked[rank]) {
    const latched = [...snap.progress.tierUnlocked];
    latched[rank] = true;
    await db
      .update(userTopicProgress)
      .set({ tierUnlocked: latched })
      .where(and(eq(userTopicProgress.userId, userId), eq(userTopicProgress.topicId, topicId)));
    snap.progress = { ...snap.progress, tierUnlocked: latched };
  }
  return snap;
}

export const tierQuizPassed = (p: Progress | null): boolean[] =>
  p ? [...p.tierQuizPassed] : [false, false, false];

export function toProgressOut(topicId: string, s: Snapshot): ProgressOut {
  return {
    topic_id: topicId,
    scope: s.scope,
    current_difficulty: s.tier,
    coverage: s.coverage,
    quiz_unlocked: s.unlocked,
    tier_quiz_passed: tierQuizPassed(s.progress),
    mastered: s.mastered,
  };
}
