import type { ProgressOut } from "@spoin/shared";
import { type Difficulty, difficultyRank } from "@spoin/shared/enums";
import { and, eq, isNull, or, sql } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import { card, subtopic, userCardState, userTopicProgress } from "../db/schema.ts";

/*
 * Tier progression (ADR-0009). Shared by the progress endpoint and the quiz's start
 * check, so the two agree on what is unlocked without duplicating the latch write.
 */

type Progress = typeof userTopicProgress.$inferSelect;

/** ADR-0032: only the tiers strictly below the entry tier start unlocked; the entry tier earns its quiz. */
export const entryTierUnlock = (entry: Difficulty): boolean[] =>
  [0, 1, 2].map((rank) => rank < difficultyRank(entry));

export async function loadProgress(db: Db | Tx, userId: string, topicId: string): Promise<Progress | null> {
  const [row] = await db
    .select()
    .from(userTopicProgress)
    .where(and(eq(userTopicProgress.userId, userId), eq(userTopicProgress.topicId, topicId)));
  return row ?? null;
}

/**
 * Coverage of the WEAKEST subtopic in the tier. The gate is "80% of every subtopic",
 * so the thinnest one governs: an average would let one well-read subtopic carry an
 * unopened one.
 */
export async function tierCoverage(
  db: Db | Tx,
  userId: string,
  topicId: string,
  tier: Difficulty,
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
        eq(subtopic.difficulty, tier),
        or(isNull(card.id), eq(card.status, "active")),
      ),
    )
    .groupBy(subtopic.id);
  const ratios = rows.filter((r) => r.total > 0).map((r) => r.seen / r.total);
  return ratios.length ? Math.min(...ratios) : 0;
}

export type Snapshot = {
  progress: Progress | null;
  tier: Difficulty;
  coverage: number;
  unlocked: boolean;
  mastered: boolean;
};

/** Read-only: no latch write, so any reader can use it. */
export async function progressSnapshot(
  db: Db | Tx,
  gate: number,
  userId: string,
  topicId: string,
): Promise<Snapshot> {
  const progress = await loadProgress(db, userId, topicId);
  const tier = progress?.currentDifficulty ?? "beginner";
  const coverage = await tierCoverage(db, userId, topicId, tier);
  const alreadyUnlocked = Boolean(progress?.tierUnlocked[difficultyRank(tier)]);
  return {
    progress,
    tier,
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
  const rank = difficultyRank(snap.tier);
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
    current_difficulty: s.tier,
    coverage: s.coverage,
    quiz_unlocked: s.unlocked,
    tier_quiz_passed: tierQuizPassed(s.progress),
    mastered: s.mastered,
  };
}
