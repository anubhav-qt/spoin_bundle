import type {
  DailyGoalOut,
  PreferencesOut,
  ProfileExportOut,
  ProfileStatsOut,
  UserOut,
  UserProfileUpdateIn,
} from "@spoin/shared";
import { and, asc, desc, eq, sql } from "drizzle-orm";
import type { z } from "zod";
import type { Db } from "../db/client.ts";
import {
  appUser,
  card,
  cardBookmark,
  cardLike,
  cardNote,
  topic,
  userAvatar,
  userTopic,
  userTopicProgress,
} from "../db/schema.ts";
import { notFound } from "../lib/errors.ts";
import { iso } from "../lib/wire.ts";
import { toUserOut } from "../users/out.ts";
import { getPreferences } from "./preferences.ts";

type In<T extends z.ZodType> = z.infer<T>;

/**
 * A card counts as read once, however many completion events it carries: one that
 * trips the dwell threshold AND gets a "Got it" tap writes two (ADR-0060).
 */
const READ = sql`kind IN ('explicit_complete', 'dwell_complete')`;

const DAY_MS = 86_400_000;

async function loadUser(db: Db, userId: string) {
  const [user] = await db.select().from(appUser).where(eq(appUser.id, userId));
  if (!user) throw notFound("User");
  return user;
}

/** `/auth/me` and every profile write answer with this: the user plus their preferences. */
export async function me(db: Db, userId: string, withPreferences = false): Promise<UserOut> {
  const user = await loadUser(db, userId);
  const preferences: PreferencesOut | null = withPreferences ? await getPreferences(db, userId) : null;
  return toUserOut(user, preferences);
}

/** Only the fields sent; a null leaves the value as it was, as before the port. */
export async function updateProfile(
  db: Db,
  userId: string,
  input: In<typeof UserProfileUpdateIn>,
): Promise<UserOut> {
  const set: Partial<typeof appUser.$inferInsert> = {};
  if (input.display_name != null) set.name = input.display_name;
  if (input.age != null) set.age = input.age;
  if (input.gender != null) set.gender = input.gender;
  if (input.avatar_icon != null) set.avatarIcon = input.avatar_icon;
  if (input.daily_card_goal != null) set.dailyCardGoal = input.daily_card_goal;
  if (Object.keys(set).length > 0) {
    await db
      .update(appUser)
      .set({ ...set, updatedAt: new Date() })
      .where(eq(appUser.id, userId));
  }
  return me(db, userId);
}

/** The bytes and `has_avatar_image` always move together: nothing else writes the flag. */
export async function setAvatar(db: Db, userId: string, data: Buffer, mediaType: string): Promise<UserOut> {
  await db.transaction(async (tx) => {
    await tx
      .insert(userAvatar)
      .values({ userId, data, mediaType })
      .onConflictDoUpdate({ target: userAvatar.userId, set: { data, mediaType, updatedAt: new Date() } });
    await tx
      .update(appUser)
      .set({ hasAvatarImage: true, updatedAt: new Date() })
      .where(eq(appUser.id, userId));
  });
  return me(db, userId);
}

export async function deleteAvatar(db: Db, userId: string): Promise<UserOut> {
  await db.transaction(async (tx) => {
    await tx.delete(userAvatar).where(eq(userAvatar.userId, userId));
    await tx
      .update(appUser)
      .set({ hasAvatarImage: false, updatedAt: new Date() })
      .where(eq(appUser.id, userId));
  });
  return me(db, userId);
}

export async function loadAvatar(db: Db, userId: string): Promise<{ data: Buffer; mediaType: string }> {
  const [row] = await db
    .select({ data: userAvatar.data, mediaType: userAvatar.mediaType })
    .from(userAvatar)
    .where(eq(userAvatar.userId, userId));
  if (!row) throw notFound("Avatar image");
  return row;
}

const ymd = (d: Date) => d.toISOString().slice(0, 10);

/** Totals, streaks and one month's heatmap, all in UTC days. */
export async function stats(db: Db, userId: string, year: number, month: number): Promise<ProfileStatsOut> {
  const totals = await db.execute<{ total_cards: number; total_topics: number }>(sql`
    SELECT count(DISTINCT card_id)::int AS total_cards, count(DISTINCT topic_id)::int AS total_topics
    FROM engagement_event WHERE user_id = ${userId} AND ${READ}`);

  const start = new Date(Date.UTC(year, month - 1, 1));
  const end = new Date(Date.UTC(year, month, 1));
  // Days come back as text: a timestamp without zone would be parsed in the process's own zone.
  const monthly = await db.execute<{ day: string; cards_read: number }>(sql`
    SELECT (occurred_at AT TIME ZONE 'UTC')::date::text AS day, count(DISTINCT card_id)::int AS cards_read
    FROM engagement_event
    WHERE user_id = ${userId} AND ${READ} AND occurred_at >= ${start} AND occurred_at < ${end}
    GROUP BY day ORDER BY day`);

  // Gaps-and-islands: consecutive days share `day - rank`.
  const streaks = await db.execute<{ end_day: string; length: number }>(sql`
    WITH days AS (
      SELECT DISTINCT (occurred_at AT TIME ZONE 'UTC')::date AS day
      FROM engagement_event WHERE user_id = ${userId} AND ${READ}
    ), groups AS (
      SELECT day, day - (dense_rank() OVER (ORDER BY day))::int AS grp FROM days
    )
    SELECT max(day)::text AS end_day, count(*)::int AS length
    FROM groups GROUP BY grp ORDER BY max(day) DESC`);

  const longest = streaks.rows.reduce((m, s) => Math.max(m, s.length), 0);
  const today = ymd(new Date());
  const yesterday = ymd(new Date(Date.now() - DAY_MS));
  const last = streaks.rows[0];
  const current = last && (last.end_day === today || last.end_day === yesterday) ? last.length : 0;

  return {
    current_streak: current,
    longest_streak: longest,
    total_cards_read: totals.rows[0]?.total_cards ?? 0,
    total_topics: totals.rows[0]?.total_topics ?? 0,
    monthly_activity: monthly.rows.map((r) => ({ date: r.day, cards_read: r.cards_read })),
  };
}

/**
 * Cards read in the caller's LOCAL day (ADR-0062). The client sends its own UTC offset
 * (`-getTimezoneOffset()`); local midnight is converted back to a UTC range, so this
 * stays a plain `occurred_at` range scan.
 */
export async function today(db: Db, userId: string, tzOffsetMinutes: number): Promise<DailyGoalOut> {
  const offsetMs = tzOffsetMinutes * 60_000;
  const local = new Date(Date.now() + offsetMs);
  const dayStart = new Date(
    Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate()) - offsetMs,
  );
  const dayEnd = new Date(dayStart.getTime() + DAY_MS);
  const res = await db.execute<{ cards_read: number }>(sql`
    SELECT count(DISTINCT card_id)::int AS cards_read FROM engagement_event
    WHERE user_id = ${userId} AND ${READ} AND occurred_at >= ${dayStart} AND occurred_at < ${dayEnd}`);
  const user = await loadUser(db, userId);
  return { cards_read: res.rows[0]?.cards_read ?? 0, goal: user.dailyCardGoal };
}

/**
 * Everything this user has produced: topics, notes, likes, bookmarks, daily activity.
 * No card bodies: the corpus is shared, the user's relationship to it is theirs.
 */
export async function exportData(db: Db, userId: string): Promise<ProfileExportOut> {
  const profile = await me(db, userId);

  const topics = await db
    .select({
      topic_id: userTopic.topicId,
      name: userTopic.displayName,
      is_custom: userTopic.isCustom,
      current_difficulty: userTopicProgress.currentDifficulty,
      followed_at: userTopic.createdAt,
    })
    .from(userTopic)
    .leftJoin(
      userTopicProgress,
      and(eq(userTopicProgress.userId, userTopic.userId), eq(userTopicProgress.topicId, userTopic.topicId)),
    )
    .where(eq(userTopic.userId, userId))
    .orderBy(asc(userTopic.createdAt));

  const notes = await db
    .select({
      card_id: cardNote.cardId,
      card_title: card.title,
      topic: topic.canonicalName,
      body: cardNote.body,
      updated_at: cardNote.updatedAt,
    })
    .from(cardNote)
    .innerJoin(card, eq(card.id, cardNote.cardId))
    .innerJoin(topic, eq(topic.id, card.topicId))
    .where(eq(cardNote.userId, userId))
    .orderBy(desc(cardNote.updatedAt));

  const refs = async (t: typeof cardLike | typeof cardBookmark) => {
    const rows = await db
      .select({
        card_id: card.id,
        title: card.title,
        topic: topic.canonicalName,
        difficulty: card.difficulty,
        at: t.createdAt,
      })
      .from(t)
      .innerJoin(card, eq(card.id, t.cardId))
      .innerJoin(topic, eq(topic.id, card.topicId))
      .where(eq(t.userId, userId))
      .orderBy(desc(t.createdAt));
    return rows.map((r) => ({ ...r, at: iso(r.at) }));
  };

  const activity = await db.execute<{ day: string; cards_read: number }>(sql`
    SELECT (occurred_at AT TIME ZONE 'UTC')::date::text AS day, count(*)::int AS cards_read
    FROM engagement_event WHERE user_id = ${userId} AND ${READ}
    GROUP BY day ORDER BY day`);

  return {
    exported_at: iso(new Date()),
    schema_version: 1,
    profile,
    topics: topics.map((t) => ({ ...t, followed_at: iso(t.followed_at) })),
    notes: notes.map((n) => ({ ...n, updated_at: iso(n.updated_at) })),
    liked_cards: await refs(cardLike),
    saved_cards: await refs(cardBookmark),
    daily_activity: activity.rows.map((r) => ({ date: r.day, cards_read: r.cards_read })),
  };
}
