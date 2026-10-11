import type { Embedder } from "@spoin/frog/embeddings";
import type { Difficulty, TopicScope } from "@spoin/shared/enums";
import { and, asc, cosineDistance, eq, inArray } from "drizzle-orm";
import type { Db } from "../db/client.ts";
import { card, subtopic, topic } from "../db/schema.ts";
import { isUuid } from "../lib/wire.ts";

/*
 * What AskAI's chat may read: one topic's public material, read-only. No user rows, no
 * other topic, nothing retired. The scoping lives here, in server code, rather than in
 * the chat's configuration, so it holds whatever the chat is told (ADR-0077's invariant).
 * The corpus joins through frog retrieval once Phase 6 ports it.
 */

export interface TopicOutline {
  name: string;
  description: string | null;
  scope: TopicScope;
  /** In reading order: easy to advanced, then as authored. */
  subtopics: { id: string; difficulty: Difficulty; title: string; description: string }[];
}

/** A card as the feed lists it: enough to decide whether to read it. */
export interface CardBrief {
  id: string;
  subtopicId: string;
  difficulty: Difficulty;
  /** The playful title the reader sees (ADR-0022). */
  title: string;
  /** The plain one, saying what the card is about. */
  canonicalTitle: string;
  summary: string;
}

export interface CardFull extends CardBrief {
  body: string;
}

export interface TopicTools {
  outline(): Promise<TopicOutline>;
  /** A subtopic's active cards, oldest first; none for another topic's subtopic. */
  cards(subtopicId: string): Promise<CardBrief[]>;
  /** These cards in full, leaving out any that is not an active card of this topic. */
  read(cardIds: string[]): Promise<CardFull[]>;
  /** The active cards nearest a query by meaning, nearest first. */
  search(query: string): Promise<CardBrief[]>;
}

const brief = {
  id: card.id,
  subtopicId: card.subtopicId,
  difficulty: card.difficulty,
  title: card.title,
  canonicalTitle: card.canonicalTitle,
  summary: card.summary,
};

/**
 * The tools for one topic. `searchLimit` is how many cards a search returns. A model
 * writes the ids these take, so a malformed one is no match rather than a cast error.
 */
export function topicTools(
  db: Db,
  embedder: Embedder,
  topicId: string,
  opts: { searchLimit: number },
): TopicTools {
  const live = and(eq(card.topicId, topicId), eq(card.status, "active"));
  return {
    async outline() {
      const [t] = await db
        .select({ name: topic.canonicalName, description: topic.description, scope: topic.scope })
        .from(topic)
        .where(eq(topic.id, topicId));
      if (!t) throw new Error(`no topic ${topicId}`);
      const subtopics = await db
        .select({
          id: subtopic.id,
          difficulty: subtopic.difficulty,
          title: subtopic.title,
          description: subtopic.description,
        })
        .from(subtopic)
        .where(eq(subtopic.topicId, topicId))
        .orderBy(asc(subtopic.difficulty), asc(subtopic.position));
      return { ...t, subtopics };
    },

    async cards(subtopicId) {
      if (!isUuid(subtopicId)) return [];
      return db
        .select(brief)
        .from(card)
        .where(and(live, eq(card.subtopicId, subtopicId)))
        .orderBy(asc(card.createdAt), asc(card.id));
    },

    async read(cardIds) {
      const valid = cardIds.filter(isUuid);
      if (valid.length === 0) return [];
      return db
        .select({ ...brief, body: card.body })
        .from(card)
        .where(and(live, inArray(card.id, valid)));
    },

    async search(query) {
      const [vector] = await embedder.embedQuery([query]);
      if (!vector) return [];
      return (
        db
          .select(brief)
          .from(card)
          // A vector from another model is in another space: comparing them means nothing.
          .where(and(live, eq(card.embeddingModel, embedder.modelName)))
          .orderBy(cosineDistance(card.contentEmbedding, vector))
          .limit(opts.searchLimit)
      );
    },
  };
}
