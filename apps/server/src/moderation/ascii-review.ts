import type { AsciiSceneActionOut, AsciiSceneOut } from "@spoin/shared";
import { and, asc, eq } from "drizzle-orm";
import { ASCII_MAX_WIDTH, entryById } from "../content/ascii-library.ts";
import type { Db } from "../db/client.ts";
import { card, subtopic, topic } from "../db/schema.ts";
import { HttpError } from "../lib/errors.ts";
import { reportCard } from "./service.ts";

/*
 * Review of one topic's ASCII scenes (ADR-0104). The drawing is copied byte for byte
 * from a verified library entry, so the only thing left to judge is taste: does this
 * scene carry this card's idea. That is a call on a rendered picture, so it gets a page,
 * and its two verdicts reuse what exists: keeping writes the art back to the card,
 * rejecting files an `art` report, which the repair queue handles (ADR-0076).
 */

/**
 * Every ASCII-carrying live card in the topic, oldest first: a run that went wrong went
 * wrong in a streak, and seeing those cards side by side is what shows the streak.
 */
export async function listScenes(db: Db, slug: string): Promise<AsciiSceneOut[]> {
  const [t] = await db.select({ id: topic.id }).from(topic).where(eq(topic.slug, slug));
  if (!t) throw new HttpError(404, `No topic '${slug}'`);
  const rows = await db
    .select({ card, subtopicTitle: subtopic.title })
    .from(card)
    .leftJoin(subtopic, eq(subtopic.id, card.subtopicId))
    .where(and(eq(card.topicId, t.id), eq(card.status, "active"), eq(card.visualKind, "ascii")))
    .orderBy(asc(card.createdAt));
  return rows.map(({ card: c, subtopicTitle }) => {
    const slots = c.visualSlots ?? {};
    const art = slots.art ?? "";
    const srcId = slots.src_id || null;
    // What the drawing was before anyone edited it, which answers "was it always like this".
    const entry = srcId ? entryById(srcId) : null;
    return {
      card_id: c.id,
      title: c.title,
      canonical_title: c.canonicalTitle,
      summary: c.summary,
      difficulty: c.difficulty,
      subtopic_title: subtopicTitle,
      art,
      alt: slots.alt ?? "",
      src_id: srcId,
      library_title: entry?.title ?? null,
      library_art: entry?.art ?? null,
      widest_line: Math.max(0, ...art.split("\n").map((line) => line.length)),
      max_width: ASCII_MAX_WIDTH,
    };
  });
}

async function requireAsciiCard(db: Db, cardId: string) {
  const [c] = await db.select().from(card).where(eq(card.id, cardId));
  if (c?.status !== "active") throw new HttpError(404, "No such card");
  if (c.visualKind !== "ascii") throw new HttpError(400, "That card carries no ASCII scene");
  return c;
}

/**
 * Writes the operator's art VERBATIM, a line over the column budget included. The
 * budget binds the model, which cannot judge its own output; an operator looking at the
 * rendered scene can, so the width is reported to them rather than reflowed.
 */
export async function keep(db: Db, cardId: string, art: string, alt: string): Promise<AsciiSceneActionOut> {
  const c = await requireAsciiCard(db, cardId);
  // `edited_by_operator` lets a later regeneration or audit leave a deliberate edit alone.
  const slots = { ...c.visualSlots, art, alt, edited_by_operator: "true" };
  await db.update(card).set({ visualSlots: slots }).where(eq(card.id, cardId));
  return { card_id: cardId, action: "kept" };
}

/**
 * Rejects the scene by filing an `art` report, through the same queue as a reader's:
 * the operator's judgement is evidence about the card, and one repair history per card
 * beats two.
 */
export async function sendToRepairs(
  db: Db,
  cardId: string,
  userId: string,
  note: string | null | undefined,
): Promise<AsciiSceneActionOut> {
  await requireAsciiCard(db, cardId);
  await reportCard(db, userId, cardId, "art", note || "Scene rejected in ASCII review");
  return { card_id: cardId, action: "sent_to_repairs" };
}
