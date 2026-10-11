import type { NoteOut, NoteWithCardOut } from "@spoin/shared";
import { and, desc, eq, inArray, sql } from "drizzle-orm";
import { toCardOut } from "../cards/out.ts";
import type { Db } from "../db/client.ts";
import { card, cardNote, subtopic, userCardState, userTopic } from "../db/schema.ts";
import { notFound } from "../lib/errors.ts";
import { iso } from "../lib/wire.ts";

/*
 * Private notes, per user and per card, never fed to ranking. `GET /notes` and the
 * feed's bulk lookup share this module, the one place that joins a note back to its card.
 */

/** Creates or replaces; an edit moves the note to the front of the list. */
export async function upsertNote(db: Db, userId: string, cardId: string, body: string): Promise<NoteOut> {
  const [exists] = await db.select({ id: card.id }).from(card).where(eq(card.id, cardId));
  if (!exists) throw notFound("Card");
  const [note] = await db
    .insert(cardNote)
    .values({ userId, cardId, body })
    // statement_timestamp(), not now(): now() is fixed for the whole transaction, so two
    // edits in one would tie on updated_at and the newest-first order would be arbitrary.
    .onConflictDoUpdate({
      target: [cardNote.userId, cardNote.cardId],
      set: { body, updatedAt: sql`statement_timestamp()` },
    })
    .returning();
  if (!note) throw new Error("note upsert returned nothing");
  return { card_id: note.cardId, body: note.body, updated_at: iso(note.updatedAt) };
}

/** Idempotent: the caller wanted no note, and now there is none. */
export async function deleteNote(db: Db, userId: string, cardId: string): Promise<void> {
  await db.delete(cardNote).where(and(eq(cardNote.userId, userId), eq(cardNote.cardId, cardId)));
}

/** The feed's bulk lookup: body by card id. */
export async function notesFor(db: Db, userId: string, cardIds: string[]): Promise<Map<string, string>> {
  if (cardIds.length === 0) return new Map();
  const rows = await db
    .select({ cardId: cardNote.cardId, body: cardNote.body })
    .from(cardNote)
    .where(and(eq(cardNote.userId, userId), inArray(cardNote.cardId, cardIds)));
  return new Map(rows.map((r) => [r.cardId, r.body]));
}

/**
 * Every note, newest edit first, with enough of the card and topic for the "all my
 * notes" view to render without a request per card (task 0004). Only notes on topics
 * the user still follows: the topic's name is the user's own label for it.
 */
export async function listNotes(db: Db, userId: string): Promise<NoteWithCardOut[]> {
  const rows = await db
    .select({
      note: cardNote,
      card,
      subtopicTitle: subtopic.title,
      topicName: userTopic.displayName,
      state: userCardState.state,
    })
    .from(cardNote)
    .innerJoin(card, eq(card.id, cardNote.cardId))
    .innerJoin(subtopic, eq(subtopic.id, card.subtopicId))
    .innerJoin(userTopic, and(eq(userTopic.userId, cardNote.userId), eq(userTopic.topicId, card.topicId)))
    // Left: a note can sit on a card the user never finished.
    .leftJoin(
      userCardState,
      and(eq(userCardState.userId, cardNote.userId), eq(userCardState.cardId, card.id)),
    )
    .where(eq(cardNote.userId, userId))
    .orderBy(desc(cardNote.updatedAt));

  return rows.map((r) => ({
    note: { card_id: r.card.id, body: r.note.body, updated_at: iso(r.note.updatedAt) },
    card: toCardOut(r.card, r.subtopicTitle, { note: r.note.body, seen: r.state === "seen" }),
    topic_name: r.topicName,
  }));
}
