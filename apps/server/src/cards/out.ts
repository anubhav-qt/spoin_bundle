import type { CardOut } from "@spoin/shared";
import type { card } from "../db/schema.ts";
import { iso } from "../lib/wire.ts";

type Card = typeof card.$inferSelect;

/**
 * The wire shape every card leaves the API in, from the feed and from the notes list
 * alike. `note` and `seen` are this user's, looked up separately: neither feeds ranking.
 */
export function toCardOut(
  c: Card,
  subtopicTitle: string,
  mine: { note?: string | null; seen?: boolean } = {},
): CardOut {
  return {
    id: c.id,
    topic_id: c.topicId,
    subtopic_id: c.subtopicId,
    subtopic_title: subtopicTitle,
    difficulty: c.difficulty,
    title: c.title,
    summary: c.summary,
    body: c.body,
    archetype: c.archetype,
    is_hero: c.isHero,
    visual_id: c.visualId,
    visual_kind: c.visualKind,
    visual_slots: c.visualSlots,
    created_at: iso(c.createdAt),
    note: mine.note ?? null,
    seen: mine.seen ?? false,
  };
}
