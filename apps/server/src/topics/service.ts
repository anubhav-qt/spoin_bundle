import type { Embedder } from "@spoin/frog/embeddings";
import type {
  CustomTopicStatusOut,
  GenerationProgressOut,
  OnboardingTopicChoice,
  TopicCurriculumOut,
  TopicDiscoverOut,
  TopicOut,
  TopicStatsOut,
} from "@spoin/shared";
import type { Difficulty } from "@spoin/shared/enums";
import { and, asc, desc, eq, inArray, ne, sql } from "drizzle-orm";
import type { Deps } from "../context.ts";
import type { Db, Tx } from "../db/client.ts";
import {
  appUser,
  card,
  cardBookmark,
  cardLike,
  engagementEvent,
  feedPlan,
  generationJob,
  subtopic,
  topic,
  userCardState,
  userTopic,
  userTopicProgress,
} from "../db/schema.ts";
import { HttpError, notFound } from "../lib/errors.ts";
import { iso } from "../lib/wire.ts";
import { assignAccentHue, defaultHuePositional, NO_TOPIC_COLOR } from "./accent.ts";
import { entryTierUnlock, loadProgress, progressSnapshot, tierQuizPassed } from "./progress.ts";

/*
 * Topic subscriptions, discovery and per-topic stats. The feed's cached interleave
 * plan is dropped on every change to what a user follows, so the next page is built
 * from the new set rather than serving a stale mix.
 */

type Ctx = Pick<Deps, "db" | "env" | "embedder">;
type Topic = typeof topic.$inferSelect;

const DISCOVER_LIMIT = 5;

const toTopicOut = (
  t: Topic,
  ut: { displayName: string; isCustom: boolean; accentHue: number | null },
  tier: Difficulty,
): TopicOut => ({
  id: t.id,
  // The user's own label, never the canonical name (ADR-0004).
  display_name: ut.displayName,
  slug: t.slug,
  is_custom: ut.isCustom,
  current_difficulty: tier,
  accent_hue: ut.accentHue,
});

async function loadTopic(db: Db | Tx, topicId: string): Promise<Topic | null> {
  const [row] = await db.select().from(topic).where(eq(topic.id, topicId));
  return row ?? null;
}

async function loadSubscription(db: Db | Tx, userId: string, topicId: string) {
  const [row] = await db
    .select()
    .from(userTopic)
    .where(and(eq(userTopic.userId, userId), eq(userTopic.topicId, topicId)));
  return row ?? null;
}

const dropFeedPlan = (db: Db | Tx, userId: string) => db.delete(feedPlan).where(eq(feedPlan.userId, userId));

const bumpSubscribers = (db: Db | Tx, topicId: string, by: 1 | -1) =>
  db
    .update(topic)
    .set({ subscriberCount: sql`greatest(0, ${topic.subscriberCount} + ${by})` })
    .where(eq(topic.id, topicId));

// -- reads ----------------------------------------------------------------------

export async function listSubscribed(db: Db, userId: string): Promise<TopicOut[]> {
  const rows = await db
    .select({ ut: userTopic, t: topic, tier: userTopicProgress.currentDifficulty })
    .from(userTopic)
    .innerJoin(topic, eq(topic.id, userTopic.topicId))
    .leftJoin(
      userTopicProgress,
      and(eq(userTopicProgress.userId, userTopic.userId), eq(userTopicProgress.topicId, userTopic.topicId)),
    )
    .where(eq(userTopic.userId, userId))
    .orderBy(asc(userTopic.createdAt));
  return rows.map((r) => toTopicOut(r.t, r.ut, r.tier ?? "beginner"));
}

/** The latest generate job per topic, in one round trip; repair jobs are not a topic's status. */
async function latestJobs(db: Db, topicIds: string[]) {
  if (topicIds.length === 0) return new Map<string, typeof generationJob.$inferSelect>();
  const rows = await db
    .selectDistinctOn([generationJob.topicId])
    .from(generationJob)
    .where(and(inArray(generationJob.topicId, topicIds), eq(generationJob.kind, "generate")))
    .orderBy(generationJob.topicId, desc(generationJob.createdAt));
  return new Map(rows.map((j) => [j.topicId, j]));
}

/**
 * This user's own requested topics with their latest job's status: without it
 * "still generating", "broken" and "nothing was ever queued" look the same.
 */
export async function listCustom(db: Db, userId: string): Promise<CustomTopicStatusOut[]> {
  const rows = await db
    .select({ ut: userTopic, t: topic })
    .from(userTopic)
    .innerJoin(topic, eq(topic.id, userTopic.topicId))
    .where(and(eq(userTopic.userId, userId), eq(userTopic.isCustom, true)))
    .orderBy(asc(userTopic.createdAt));
  const jobs = await latestJobs(
    db,
    rows.map((r) => r.t.id),
  );
  return rows.map((r) => ({
    topic_id: r.t.id,
    display_name: r.ut.displayName,
    slug: r.t.slug,
    generation_status: jobs.get(r.t.id)?.status ?? null,
    requested_at: iso(r.ut.createdAt),
  }));
}

/**
 * Which topics are browsable: at least TOPIC_LIVE_COVERAGE_FRACTION of their subtopics
 * have reached their own `min_cards` (ADR-0053). Computed from live card counts at
 * read time, so it follows reality when content is later retired.
 */
async function liveTopicIds(ctx: Ctx, topicIds: string[]): Promise<Set<string>> {
  if (topicIds.length === 0) return new Set();
  const per = ctx.db
    .select({
      topicId: subtopic.topicId,
      minCards: subtopic.minCards,
      active: sql<number>`count(${card.id}) filter (where ${card.status} = 'active')`.as("active"),
    })
    .from(subtopic)
    .leftJoin(card, eq(card.subtopicId, subtopic.id))
    .where(inArray(subtopic.topicId, topicIds))
    .groupBy(subtopic.topicId, subtopic.id)
    .as("per");
  const rows = await ctx.db
    .select({
      topicId: per.topicId,
      covered: sql<number>`(count(*) filter (where ${per.active} >= ${per.minCards}))::int`,
      total: sql<number>`count(*)::int`,
    })
    .from(per)
    .groupBy(per.topicId);
  const threshold = ctx.env.TOPIC_LIVE_COVERAGE_FRACTION;
  return new Set(rows.filter((r) => r.total > 0 && r.covered / r.total >= threshold).map((r) => r.topicId));
}

/**
 * Polled by the request-a-topic view while a topic is being built. No ownership
 * check past sign-in: a job carries nothing user-specific.
 */
export async function generationProgress(ctx: Ctx, topicId: string): Promise<GenerationProgressOut> {
  const [job] = await ctx.db
    .select()
    .from(generationJob)
    .where(and(eq(generationJob.topicId, topicId), eq(generationJob.kind, "generate")))
    .orderBy(desc(generationJob.createdAt))
    .limit(1);
  if (!job) throw new HttpError(404, "No generation job for this topic");

  const progress = (job.progress ?? {}) as {
    stage?: GenerationProgressOut["stage"];
    topic_name?: string;
    subtopics?: GenerationProgressOut["subtopics"];
  };
  const status = job.status as GenerationProgressOut["status"];
  return {
    status,
    stage: status === "pending" ? null : (progress.stage ?? "curriculum"),
    topic_name: progress.topic_name ?? null,
    subtopics: progress.subtopics ?? [],
    error: status === "failed" ? job.lastError : null,
    topic_live: (await liveTopicIds(ctx, [topicId])).has(topicId),
  };
}

/**
 * Withdraws this user's own request while its job is still pending: the job, the
 * subscription, and the topic itself if nobody else follows it. The DELETE ...
 * RETURNING is the guard: once a worker has claimed the job it is a concurrent
 * writer, so this refuses rather than racing it.
 */
export async function cancelGeneration(db: Db, userId: string, topicId: string): Promise<void> {
  await db.transaction(async (tx) => {
    const sub = await loadSubscription(tx, userId, topicId);
    if (!sub?.isCustom) throw new HttpError(404, "No custom topic request found");

    const removed = await tx
      .delete(generationJob)
      .where(
        and(
          eq(generationJob.topicId, topicId),
          eq(generationJob.kind, "generate"),
          eq(generationJob.status, "pending"),
        ),
      )
      .returning({ id: generationJob.id });
    if (removed.length === 0)
      throw new HttpError(409, "Generation has already started and can no longer be cancelled");

    await bumpSubscribers(tx, topicId, -1);
    await tx
      .delete(userTopicProgress)
      .where(and(eq(userTopicProgress.userId, userId), eq(userTopicProgress.topicId, topicId)));
    await tx.delete(userTopic).where(eq(userTopic.id, sub.id));

    // A still-pending job generated nothing, so an unfollowed topic is an empty row: remove it.
    const [followers] = await tx
      .select({ n: sql<number>`count(*)::int` })
      .from(userTopic)
      .where(eq(userTopic.topicId, topicId));
    if (!followers?.n) await tx.delete(topic).where(eq(topic.id, topicId));

    await dropFeedPlan(tx, userId);
  });
}

async function followedIds(db: Db, userId: string): Promise<Set<string>> {
  const rows = await db.select({ id: userTopic.topicId }).from(userTopic).where(eq(userTopic.userId, userId));
  return new Set(rows.map((r) => r.id));
}

/**
 * Every live topic, plus everything the user follows whether live yet or not
 * (ADR-0038); `followed` lets the client grey out Follow instead of hiding the row.
 */
export async function listAll(ctx: Ctx, userId: string): Promise<TopicDiscoverOut[]> {
  const followed = await followedIds(ctx.db, userId);
  const rows = await ctx.db
    .select()
    .from(topic)
    .orderBy(desc(topic.subscriberCount), asc(topic.canonicalName));
  const live = await liveTopicIds(
    ctx,
    rows.filter((t) => !followed.has(t.id)).map((t) => t.id),
  );
  return rows
    .filter((t) => followed.has(t.id) || live.has(t.id))
    .map((t) => ({
      topic_id: t.id,
      display_name: t.canonicalName,
      subscriber_count: t.subscriberCount,
      followed: followed.has(t.id),
    }));
}

/**
 * The top live topics the user does not follow, by subscriber count. The limit is
 * applied after the live filter: a just-live topic can outrank an established one,
 * so the top N by count and the top N that are live are not the same slice.
 */
export async function discover(ctx: Ctx, userId: string): Promise<TopicDiscoverOut[]> {
  const followed = await followedIds(ctx.db, userId);
  const candidates = (
    await ctx.db.select().from(topic).orderBy(desc(topic.subscriberCount), asc(topic.canonicalName))
  ).filter((t) => !followed.has(t.id));
  const live = await liveTopicIds(
    ctx,
    candidates.map((t) => t.id),
  );
  return candidates
    .filter((t) => live.has(t.id))
    .slice(0, DISCOVER_LIMIT)
    .map((t) => ({
      topic_id: t.id,
      display_name: t.canonicalName,
      subscriber_count: t.subscriberCount,
      followed: false,
    }));
}

export async function stats(ctx: Ctx, userId: string, topicId: string): Promise<TopicStatsOut> {
  const { db } = ctx;
  const snap = await progressSnapshot(db, ctx.env.COVERAGE_GATE, userId, topicId);
  const countOn = async (t: typeof cardLike | typeof cardBookmark) => {
    const [row] = await db
      .select({ n: sql<number>`count(*)::int` })
      .from(t)
      .innerJoin(card, eq(card.id, t.cardId))
      .where(and(eq(t.userId, userId), eq(card.topicId, topicId)));
    return row?.n ?? 0;
  };
  // Notes and shares have no current-state table, so these two come from the event log.
  const events = await db
    .select({ kind: engagementEvent.kind, n: sql<number>`count(*)::int` })
    .from(engagementEvent)
    .where(
      and(
        eq(engagementEvent.userId, userId),
        eq(engagementEvent.topicId, topicId),
        inArray(engagementEvent.kind, ["note", "share"]),
      ),
    )
    .groupBy(engagementEvent.kind);
  const kinds = new Map(events.map((e) => [e.kind, e.n]));
  return {
    topic_id: topicId,
    current_difficulty: snap.tier,
    coverage: snap.coverage,
    quiz_unlocked: snap.unlocked,
    mastered: snap.mastered,
    tier_quiz_passed: tierQuizPassed(snap.progress),
    likes: await countOn(cardLike),
    saves: await countOn(cardBookmark),
    notes: kinds.get("note") ?? 0,
    shares: kinds.get("share") ?? 0,
  };
}

/**
 * Every subtopic across all three tiers with this user's coverage of each, in
 * authoring order. Only active cards count, on both sides of the ratio.
 */
export async function curriculum(ctx: Ctx, userId: string, topicId: string): Promise<TopicCurriculumOut> {
  const rows = await ctx.db
    .select({
      id: subtopic.id,
      title: subtopic.title,
      difficulty: subtopic.difficulty,
      total: sql<number>`(count(${card.id}) filter (where ${card.status} = 'active'))::int`,
      seen: sql<number>`(count(${userCardState.cardId}) filter (where ${card.status} = 'active' and ${userCardState.state} = 'seen'))::int`,
    })
    .from(subtopic)
    .leftJoin(card, eq(card.subtopicId, subtopic.id))
    .leftJoin(userCardState, and(eq(userCardState.cardId, card.id), eq(userCardState.userId, userId)))
    .where(eq(subtopic.topicId, topicId))
    .groupBy(subtopic.id)
    .orderBy(asc(subtopic.difficulty), asc(subtopic.position));
  const gate = ctx.env.COVERAGE_GATE;
  return {
    topic_id: topicId,
    subtopics: rows.map((r) => ({
      subtopic_id: r.id,
      title: r.title,
      difficulty: r.difficulty,
      total_cards: r.total,
      seen_cards: r.seen,
      coverage: r.total ? r.seen / r.total : 0,
      // The same gate tier unlock uses, per subtopic instead of only at the thinnest.
      covered: r.total > 0 && r.seen / r.total >= gate,
    })),
  };
}

// -- writes ---------------------------------------------------------------------

/**
 * ADR-0075 hues for a run of new subscriptions, each distinct from the user's other
 * topics and from the ones before it in the run. Picked before the write transaction,
 * so no connection is held while the embedder runs.
 */
export async function pickHues(
  db: Db | Tx,
  embedder: Embedder,
  userId: string,
  topics: Topic[],
  excluding?: string,
): Promise<(number | null)[]> {
  const rows = await db
    .select({ topicId: userTopic.topicId, hue: userTopic.accentHue })
    .from(userTopic)
    .where(and(eq(userTopic.userId, userId), excluding ? ne(userTopic.topicId, excluding) : undefined))
    .orderBy(asc(userTopic.createdAt));
  const used = new Set<number>();
  rows.forEach((r, i) => {
    if (r.hue === NO_TOPIC_COLOR) return;
    // A legacy null renders as the client's positional default; dedup against that.
    used.add(r.hue === null ? defaultHuePositional(r.topicId, i) : ((r.hue % 360) + 360) % 360);
  });
  const hues: (number | null)[] = [];
  for (const [i, t] of topics.entries()) {
    const hue = await assignAccentHue(embedder, {
      topicId: t.id,
      topicName: t.canonicalName,
      topicEmbedding: t.embedding,
      usedHues: used,
      subscriptionIndex: rows.length + i,
    });
    if (hue !== null) used.add(hue);
    hues.push(hue);
  }
  return hues;
}

/** The subscription, its progress row and the subscriber count, together. Null if already following. */
export async function followTopic(
  tx: Tx,
  userId: string,
  t: Topic,
  opts: { displayName: string; isCustom: boolean; entry: Difficulty; hue: number | null },
): Promise<TopicOut | null> {
  const [ut] = await tx
    .insert(userTopic)
    .values({
      userId,
      topicId: t.id,
      displayName: opts.displayName,
      isCustom: opts.isCustom,
      accentHue: opts.hue,
    })
    .onConflictDoNothing()
    .returning();
  if (!ut) return null;
  await bumpSubscribers(tx, t.id, 1);
  await tx.insert(userTopicProgress).values({
    userId,
    topicId: t.id,
    currentDifficulty: opts.entry,
    tierUnlocked: entryTierUnlock(opts.entry),
  });
  return toTopicOut(t, ut, opts.entry);
}

export async function subscribe(
  ctx: Ctx,
  userId: string,
  topicId: string,
  entry: Difficulty,
): Promise<TopicOut> {
  const t = await loadTopic(ctx.db, topicId);
  if (!t) throw new HttpError(404, "Unknown topic");
  if (await loadSubscription(ctx.db, userId, topicId)) throw new HttpError(409, "Already subscribed");
  const [hue = null] = await pickHues(ctx.db, ctx.embedder, userId, [t]);
  return ctx.db.transaction(async (tx) => {
    // No rename UI yet, so the label starts as the canonical name.
    const out = await followTopic(tx, userId, t, {
      displayName: t.canonicalName,
      isCustom: false,
      entry,
      hue,
    });
    if (!out) throw new HttpError(409, "Already subscribed");
    await dropFeedPlan(tx, userId);
    return out;
  });
}

/**
 * Drops the subscription and its progress. Likes, saves and notes stay: they are the
 * user's own record of reading those cards, not membership.
 */
export async function unsubscribe(db: Db, userId: string, topicId: string): Promise<void> {
  await db.transaction(async (tx) => {
    const gone = await tx
      .delete(userTopic)
      .where(and(eq(userTopic.userId, userId), eq(userTopic.topicId, topicId)))
      .returning({ id: userTopic.id });
    if (gone.length === 0) throw new HttpError(404, "Not subscribed to this topic");
    await bumpSubscribers(tx, topicId, -1);
    await tx
      .delete(userTopicProgress)
      .where(and(eq(userTopicProgress.userId, userId), eq(userTopicProgress.topicId, topicId)));
    await dropFeedPlan(tx, userId);
  });
}

/**
 * First run: follow the chosen topics, each at its own entry tier, then flip the gate
 * the root route checks. Unknown or already-followed ids are skipped, not fatal: one
 * stale entry in the picker must not strand a new user.
 */
export async function completeOnboarding(
  ctx: Ctx,
  userId: string,
  choices: OnboardingTopicChoice[],
): Promise<TopicOut[]> {
  const already = await followedIds(ctx.db, userId);
  const wanted = new Map<string, Difficulty>();
  for (const c of choices)
    if (!already.has(c.topic_id) && !wanted.has(c.topic_id)) wanted.set(c.topic_id, c.entry_difficulty);
  const found = wanted.size
    ? await ctx.db
        .select()
        .from(topic)
        .where(inArray(topic.id, [...wanted.keys()]))
    : [];
  // In the order the user picked them, which is the order hues are dealt in.
  const ordered = [...wanted.keys()].flatMap((id) => found.filter((t) => t.id === id));
  const hues = await pickHues(ctx.db, ctx.embedder, userId, ordered);

  return ctx.db.transaction(async (tx) => {
    const out: TopicOut[] = [];
    for (const [i, t] of ordered.entries()) {
      const entry = wanted.get(t.id) ?? "beginner";
      const followed = await followTopic(tx, userId, t, {
        displayName: t.canonicalName,
        isCustom: false,
        entry,
        hue: hues[i] ?? null,
      });
      if (followed) out.push(followed);
    }
    await tx.update(appUser).set({ onboardingComplete: true }).where(eq(appUser.id, userId));
    await dropFeedPlan(tx, userId);
    return out;
  });
}

/**
 * Per-subscription accent hue (ADR-0034): two users may colour one topic differently.
 * -1 opts out (ADR-0051); null re-runs the ADR-0075 pick with this topic left out.
 */
export async function setColor(
  ctx: Ctx,
  userId: string,
  topicId: string,
  hue: number | null,
): Promise<TopicOut> {
  const sub = await loadSubscription(ctx.db, userId, topicId);
  const t = sub && (await loadTopic(ctx.db, topicId));
  if (!sub || !t) throw new HttpError(404, "Not subscribed to this topic");
  const accentHue = hue ?? (await pickHues(ctx.db, ctx.embedder, userId, [t], topicId))[0] ?? null;
  const [ut] = await ctx.db.update(userTopic).set({ accentHue }).where(eq(userTopic.id, sub.id)).returning();
  if (!ut) throw notFound("Subscription");
  const progress = await loadProgress(ctx.db, userId, topicId);
  return toTopicOut(t, ut, progress?.currentDifficulty ?? "beginner");
}
