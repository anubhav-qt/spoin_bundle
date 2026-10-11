import type { CardOut, CollectionSort } from "@spoin/shared";
import { and, asc, desc, eq, inArray, sql } from "drizzle-orm";
import type { Db } from "../db/client.ts";
import { card, cardBookmark, cardLike, subtopic, topic, userCardState, userTopic } from "../db/schema.ts";
import { notFound } from "../lib/errors.ts";
import { iso } from "../lib/wire.ts";
import { notesFor } from "../notes/service.ts";
import { toCardOut } from "./out.ts";

/*
 * Cards by id: a feed page's hydration, a single shared card, and the liked and saved
 * collections. Pure retrieval, no ranking. Notes always come from their own query:
 * they are private state and never ride in a card query.
 */

/**
 * The page's cards in its ranked order (`IN` keeps none), joined to their subtopic's
 * title because the client groups cards under station headers.
 */
export async function hydrate(db: Db, userId: string, cardIds: string[]): Promise<CardOut[]> {
  if (cardIds.length === 0) return [];
  const rows = await db
    .select({ card, subtopicTitle: subtopic.title })
    .from(card)
    .innerJoin(subtopic, eq(subtopic.id, card.subtopicId))
    .where(inArray(card.id, cardIds));
  const byId = new Map(rows.map((r) => [r.card.id, r]));
  const notes = await notesFor(db, userId, cardIds);
  return cardIds.flatMap((id) => {
    const r = byId.get(id);
    return r ? [toCardOut(r.card, r.subtopicTitle, { note: notes.get(id) })] : [];
  });
}

/** One card for a direct link or a share; the note only when someone is signed in. */
export async function getCard(db: Db, cardId: string, userId: string | null): Promise<CardOut> {
  const [row] = await db
    .select({ card, subtopicTitle: subtopic.title })
    .from(card)
    .innerJoin(subtopic, eq(subtopic.id, card.subtopicId))
    .where(eq(card.id, cardId));
  if (!row) throw notFound("Card");
  const note = userId ? (await notesFor(db, userId, [cardId])).get(cardId) : null;
  return toCardOut(row.card, row.subtopicTitle, { note });
}

export type Collected = { card: CardOut; topic_name: string; at: string };

/**
 * One of the reader's collections, in the requested order so a large one is never
 * re-sorted on the client. The topic's label is the reader's own when they still
 * follow it, its canonical name when not.
 */
export async function collection(
  db: Db,
  userId: string,
  which: "liked" | "saved",
  opts: { topicId?: string; sort: CollectionSort },
): Promise<Collected[]> {
  const t = which === "liked" ? cardLike : cardBookmark;
  const label = sql<string>`coalesce(${userTopic.displayName}, ${topic.canonicalName})`;
  const order = {
    recent: [desc(t.createdAt)],
    oldest: [asc(t.createdAt)],
    topic: [asc(label), desc(t.createdAt)],
    difficulty: [asc(card.difficulty), desc(t.createdAt)],
  }[opts.sort];

  const rows = await db
    .select({ at: t.createdAt, card, subtopicTitle: subtopic.title, label, state: userCardState.state })
    .from(t)
    .innerJoin(card, eq(card.id, t.cardId))
    .innerJoin(subtopic, eq(subtopic.id, card.subtopicId))
    .innerJoin(topic, eq(topic.id, card.topicId))
    .leftJoin(userTopic, and(eq(userTopic.userId, t.userId), eq(userTopic.topicId, card.topicId)))
    // Left: a card can be collected without ever being read, and shows as unread rather than vanishing.
    .leftJoin(userCardState, and(eq(userCardState.userId, t.userId), eq(userCardState.cardId, card.id)))
    .where(and(eq(t.userId, userId), opts.topicId ? eq(card.topicId, opts.topicId) : undefined))
    .orderBy(...order);

  const notes = await notesFor(
    db,
    userId,
    rows.map((r) => r.card.id),
  );
  return rows.map((r) => ({
    card: toCardOut(r.card, r.subtopicTitle, { note: notes.get(r.card.id), seen: r.state === "seen" }),
    topic_name: r.label,
    at: iso(r.at),
  }));
}
