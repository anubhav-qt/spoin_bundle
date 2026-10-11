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

/**
 * A tool call the chat got wrong. The harness hands the message back to the chat as the
 * tool's result, so it is one short line saying what was wrong and how to call the tool
 * right: a call that fails once should succeed on the retry (ADR-0106).
 */
export class ToolError extends Error {}

/** Each method throws `ToolError` when called wrong; an empty result is an answer, not an error. */
export interface TopicTools {
  outline(): Promise<TopicOutline>;
  /** A subtopic's active cards, oldest first. */
  cards(subtopicId: string): Promise<CardBrief[]>;
  /** These cards in full. Ids that are not active cards of this topic are left out and named in `note`. */
  read(cardIds: string[]): Promise<{ cards: CardFull[]; note?: string }>;
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

/** A value the model wrote, quoted back without letting a runaway string make the error long. */
const quoted = (value: string) => JSON.stringify(value.length > 40 ? `${value.slice(0, 40)}...` : value);

/** A few of `values`, so a long list of bad ids still makes a one-line error. */
const listed = (values: string[]) =>
  values.length > 3
    ? `${values.slice(0, 3).map(quoted).join(", ")} and ${values.length - 3} more`
    : values.map(quoted).join(", ");

/** Active cards of this topic among `ids`, in full; anything else is silently absent. */
export async function activeCards(db: Db, topicId: string, ids: string[]): Promise<CardFull[]> {
  const valid = ids.filter(isUuid);
  if (valid.length === 0) return [];
  return db
    .select({ ...brief, body: card.body })
    .from(card)
    .where(and(eq(card.topicId, topicId), eq(card.status, "active"), inArray(card.id, valid)));
}

/** The tools for one topic. `searchLimit` is how many cards a search returns. */
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
      if (!t) throw new ToolError("This topic no longer exists.");
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
      if (!isUuid(subtopicId)) {
        throw new ToolError(
          `${quoted(subtopicId)} is not a subtopic id. outline() lists this topic's subtopics.`,
        );
      }
      const [own] = await db
        .select({ id: subtopic.id })
        .from(subtopic)
        .where(and(eq(subtopic.id, subtopicId), eq(subtopic.topicId, topicId)));
      if (!own) throw new ToolError(`No subtopic ${subtopicId} in this topic. outline() lists them.`);
      return db
        .select(brief)
        .from(card)
        .where(and(live, eq(card.subtopicId, subtopicId)))
        .orderBy(asc(card.createdAt), asc(card.id));
    },

    async read(cardIds) {
      const asked = [...new Set(cardIds)];
      if (asked.length === 0)
        throw new ToolError("Give at least one card id. search() and cards() list them.");
      const cards = await activeCards(db, topicId, asked);
      const found = new Set(cards.map((c) => c.id));
      const missing = asked.filter((id) => !found.has(id));
      if (missing.length === 0) return { cards };
      if (cards.length === 0) {
        throw new ToolError(
          `No active card in this topic has id ${listed(missing)}. search() and cards() list them.`,
        );
      }
      return { cards, note: `Left out, not active cards in this topic: ${listed(missing)}.` };
    },

    async search(query) {
      if (!query.trim()) throw new ToolError("Give a query: what to look for, in words.");
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
