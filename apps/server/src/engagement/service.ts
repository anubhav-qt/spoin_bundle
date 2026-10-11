import type { EngagementAck, EngagementEventIn } from "@spoin/shared";
import { COMPLETION_KINDS, type EngagementKind } from "@spoin/shared/enums";
import { and, eq, inArray, ne, sql } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import {
  card,
  cardBookmark,
  cardLike,
  engagementEvent,
  userCardState,
  userSessionTopicSignal,
  userSubtopicProgress,
  userTopicCycle,
  userTopicDifficultyProgress,
} from "../db/schema.ts";
import type { Env } from "../env.ts";

/*
 * Engagement ingest and the seen-state machine (ADR-0010, ADR-0011). Two things here
 * are easy to get wrong and expensive later:
 *
 * 1. `explicit_complete` and `dwell_complete` are separate events. Equal for the
 *    progression gate, very different for ranking; collapsed into one boolean the
 *    difference could never be recovered from the log.
 * 2. `occurred_at` is server-assigned, always.
 */

type Row = {
  id: string;
  cardId: string;
  topicId: string;
  subtopicId: string;
  difficulty: (typeof card.$inferSelect)["difficulty"];
  kind: EngagementKind;
  dwellMs: number | null;
  clientOccurredAt: Date | null;
  sessionId: string | null;
};

/** Per-kind contribution to the session profile (ADR-0055); kinds absent contribute nothing. */
function sessionWeights(env: Env): Partial<Record<EngagementKind, number>> {
  return {
    expand: env.SESSION_W_EXPAND,
    explicit_complete: env.SESSION_W_EXPLICIT_COMPLETE,
    dwell_complete: env.SESSION_W_DWELL_COMPLETE,
    like: env.SESSION_W_LIKE,
    // Undoing an action subtracts exactly what taking it added: a mis-tap leaves no residue.
    unlike: -env.SESSION_W_LIKE,
    bookmark: env.SESSION_W_BOOKMARK,
    unbookmark: -env.SESSION_W_BOOKMARK,
    note: env.SESSION_W_NOTE,
    share: env.SESSION_W_SHARE,
    ask_ai: env.SESSION_W_ASK_AI,
    skip: env.SESSION_W_SKIP,
  };
}

/**
 * Inserts a client batch, deduplicated on the client-generated id: retries must
 * collide, not inflate, because `card_quality` is a rate and a double impression
 * corrupts ranking rather than merely miscounting. One bad row never sinks the rest.
 */
export async function ingest(
  db: Db,
  env: Env,
  userId: string,
  events: EngagementEventIn[],
): Promise<EngagementAck> {
  if (events.length === 0) return { accepted: 0, duplicates: 0, rejected: 0 };

  const cards = new Map(
    (
      await db
        .select({
          id: card.id,
          topicId: card.topicId,
          subtopicId: card.subtopicId,
          difficulty: card.difficulty,
        })
        .from(card)
        .where(
          inArray(
            card.id,
            events.map((e) => e.card_id),
          ),
        )
    ).map((c) => [c.id, c]),
  );

  const rows: Row[] = [];
  let rejected = 0;
  for (const e of events) {
    const c = cards.get(e.card_id);
    // A dwell past the cap is discarded, not stored: one overnight tab skews a card's average for good.
    if (!c || (e.dwell_ms != null && e.dwell_ms > env.DWELL_MAX_MS)) {
      rejected += 1;
      continue;
    }
    rows.push({
      id: e.id,
      cardId: c.id,
      topicId: c.topicId,
      subtopicId: c.subtopicId,
      difficulty: c.difficulty,
      kind: e.kind,
      dwellMs: e.dwell_ms ?? null,
      clientOccurredAt: e.client_occurred_at ? new Date(e.client_occurred_at) : null,
      sessionId: e.session_id ?? null,
    });
  }
  if (rows.length === 0) return { accepted: 0, duplicates: 0, rejected };

  return db.transaction(async (tx) => {
    const inserted = await tx
      .insert(engagementEvent)
      .values(
        rows.map((r) => ({
          id: r.id,
          userId,
          cardId: r.cardId,
          topicId: r.topicId,
          subtopicId: r.subtopicId,
          kind: r.kind,
          dwellMs: r.dwellMs,
          clientOccurredAt: r.clientOccurredAt,
          sessionId: r.sessionId,
        })),
      )
      .onConflictDoNothing({ target: engagementEvent.id })
      .returning({ id: engagementEvent.id });

    // One lock order for every concurrent batch, so two never deadlock on the same
    // state rows. The sort is stable: events on one card keep their batch order.
    const ordered = [...rows].sort(
      (a, b) => a.subtopicId.localeCompare(b.subtopicId) || a.cardId.localeCompare(b.cardId),
    );
    const now = new Date();
    const weights = sessionWeights(env);
    for (const r of ordered) {
      await applyState(tx, userId, r);
      // Here, not in applyState: the session profile needs every kind, including
      // the ones the state machine handles and stops at.
      await bumpSessionSignal(tx, env, weights, userId, r, now);
    }
    return { accepted: inserted.length, duplicates: rows.length - inserted.length, rejected };
  });
}

async function applyState(tx: Tx, userId: string, r: Row) {
  switch (r.kind) {
    // An impression is a card on screen for ~1s: shown, so DEFERRED until the rest of
    // the tier has had its turn. Never SEEN: only reading advances the quiz gate.
    case "impression":
    case "skip":
      return defer(tx, userId, r);
    case "like":
      return tx.insert(cardLike).values({ userId, cardId: r.cardId }).onConflictDoNothing();
    case "unlike":
      return tx.delete(cardLike).where(and(eq(cardLike.userId, userId), eq(cardLike.cardId, r.cardId)));
    case "bookmark":
      return tx.insert(cardBookmark).values({ userId, cardId: r.cardId }).onConflictDoNothing();
    case "unbookmark":
      return tx
        .delete(cardBookmark)
        .where(and(eq(cardBookmark.userId, userId), eq(cardBookmark.cardId, r.cardId)));
    default:
      if (COMPLETION_KINDS.has(r.kind)) return markSeen(tx, userId, r);
  }
}

/** Shown but not read: back once this tier's cycle advances (the feed's cycle step). */
async function defer(tx: Tx, userId: string, r: Row) {
  const [current] = await tx
    .select({ cycle: userTopicCycle.cycle })
    .from(userTopicCycle)
    .where(
      and(
        eq(userTopicCycle.userId, userId),
        eq(userTopicCycle.topicId, r.topicId),
        eq(userTopicCycle.difficulty, r.difficulty),
      ),
    );
  const cycle = current?.cycle ?? 0;
  await tx
    .insert(userCardState)
    .values({
      userId,
      cardId: r.cardId,
      topicId: r.topicId,
      subtopicId: r.subtopicId,
      state: "deferred",
      deferredCycle: cycle,
    })
    .onConflictDoUpdate({
      target: [userCardState.userId, userCardState.cardId],
      set: { state: "deferred", deferredCycle: cycle },
      // SEEN is terminal: a stray skip after a completion never walks a card back out of the count.
      setWhere: ne(userCardState.state, "seen"),
    });
}

async function markSeen(tx: Tx, userId: string, r: Row) {
  const now = new Date();
  await tx
    .insert(userCardState)
    .values({
      userId,
      cardId: r.cardId,
      topicId: r.topicId,
      subtopicId: r.subtopicId,
      state: "seen",
      completedVia: r.kind,
      seenAt: now,
    })
    .onConflictDoUpdate({
      target: [userCardState.userId, userCardState.cardId],
      set: { state: "seen", completedVia: r.kind, seenAt: now },
      setWhere: ne(userCardState.state, "seen"),
    });
  await bumpProgress(tx, userId, r);
}

/**
 * The derived seen/total aggregates, kept current here so the gate and the
 * difficulty ramp are column reads and the read path never counts. Rebuildable from
 * the event log.
 */
async function bumpProgress(tx: Tx, userId: string, r: Row) {
  const res = await tx.execute<{
    sub_seen: number;
    sub_total: number;
    tier_seen: number;
    tier_total: number;
  }>(sql`
    SELECT
      (SELECT count(*)::int FROM user_card_state
        WHERE user_id = ${userId} AND subtopic_id = ${r.subtopicId} AND state = 'seen') AS sub_seen,
      (SELECT count(*)::int FROM card
        WHERE subtopic_id = ${r.subtopicId} AND status = 'active') AS sub_total,
      (SELECT count(*)::int FROM user_card_state s JOIN card c ON c.id = s.card_id
        WHERE s.user_id = ${userId} AND c.topic_id = ${r.topicId} AND c.difficulty = ${r.difficulty}
          AND s.state = 'seen') AS tier_seen,
      (SELECT count(*)::int FROM card
        WHERE topic_id = ${r.topicId} AND difficulty = ${r.difficulty} AND status = 'active') AS tier_total`);
  const counts = res.rows[0];
  const sub = { seenCount: counts?.sub_seen ?? 0, totalCount: counts?.sub_total ?? 0 };
  await tx
    .insert(userSubtopicProgress)
    .values({ userId, subtopicId: r.subtopicId, ...sub })
    .onConflictDoUpdate({ target: [userSubtopicProgress.userId, userSubtopicProgress.subtopicId], set: sub });

  const tier = { seenCount: counts?.tier_seen ?? 0, totalCount: counts?.tier_total ?? 0 };
  await tx
    .insert(userTopicDifficultyProgress)
    .values({ userId, topicId: r.topicId, difficulty: r.difficulty, ...tier })
    .onConflictDoUpdate({
      target: [
        userTopicDifficultyProgress.userId,
        userTopicDifficultyProgress.topicId,
        userTopicDifficultyProgress.difficulty,
      ],
      set: tier,
    });
}

/**
 * Accumulates the event into this session's weight for its topic, so the feed reads
 * a column and never aggregates (ADR-0011, ADR-0055). An event after the window has
 * lapsed starts a new session rather than resuming one from hours ago.
 */
async function bumpSessionSignal(
  tx: Tx,
  env: Env,
  weights: Partial<Record<EngagementKind, number>>,
  userId: string,
  r: Row,
  now: Date,
) {
  // Dwell is already capped above, so this cannot be an overnight tab posing as interest.
  const contribution = (weights[r.kind] ?? 0) + ((r.dwellMs ?? 0) / 1000) * env.SESSION_W_DWELL_PER_SECOND;
  if (contribution === 0) return;
  const lapsed = new Date(now.getTime() - env.SESSION_WINDOW_SECONDS * 1000);
  await tx
    .insert(userSessionTopicSignal)
    .values({ userId, topicId: r.topicId, score: contribution, lastEventAt: now })
    .onConflictDoUpdate({
      target: [userSessionTopicSignal.userId, userSessionTopicSignal.topicId],
      // Reset-or-accumulate in one statement: the conflicting row stays locked, so two
      // concurrent ingests for one (user, topic) serialize instead of losing a contribution.
      set: {
        score: sql`case when ${userSessionTopicSignal.lastEventAt} < ${lapsed} then excluded.score else ${userSessionTopicSignal.score} + excluded.score end`,
        lastEventAt: sql`excluded.last_event_at`,
      },
    });
}
