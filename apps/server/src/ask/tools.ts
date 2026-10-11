import type { Embedder } from "@spoin/frog/embeddings";
import { resolveGrounding, search as searchCorpus } from "@spoin/frog/retrieval";
import type { Difficulty, TopicScope } from "@spoin/shared/enums";
import { and, asc, cosineDistance, eq, inArray, isNotNull, or } from "drizzle-orm";
import type { Db, UniverseDb } from "../db/client.ts";
import { card, subtopic, topic, topicEdge } from "../db/schema.ts";
import { isUuid } from "../lib/wire.ts";

/*
 * What AskAI's chat may read: one topic's public material, read-only. No user rows, no
 * other topic, nothing retired. The scoping lives here, in server code, rather than in
 * the chat's configuration, so it holds whatever the chat is told (ADR-0077's invariant).
 * The corpus is public material too: the sections this topic and its related topics
 * were written from.
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

/** A corpus section. `text` opens with its document's title and heading, as it was embedded. */
export interface Passage {
  text: string;
  /** Where the document came from, a URL or an origin, so the chat can cite it. */
  source: string;
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
  /**
   * The corpus sections this topic and its related topics were written from (their
   * subtopics' grounding), nearest a query by meaning. Related topics are those joined
   * to this one by a `topic_edge` either way, which toad_sage decides. Absent when the
   * server has no corpus database.
   */
  passages?(query: string): Promise<Passage[]>;
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

/** Every grounding reference of this topic and the topics joined to it by an edge, either way. */
async function groundingOf(db: Db, topicId: string): Promise<string[]> {
  const edges = await db
    .select({ from: topicEdge.fromTopicId, to: topicEdge.toTopicId })
    .from(topicEdge)
    .where(or(eq(topicEdge.fromTopicId, topicId), eq(topicEdge.toTopicId, topicId)));
  const topicIds = [topicId, ...edges.map((e) => (e.from === topicId ? e.to : e.from))];
  const rows = await db
    .select({ refs: subtopic.groundingRefs })
    .from(subtopic)
    .where(and(inArray(subtopic.topicId, topicIds), isNotNull(subtopic.groundingRefs)));
  return [...new Set(rows.flatMap((r) => r.refs ?? []))];
}

/** The tools for one topic. `searchLimit` is how many results a search returns. */
export function topicTools(
  ctx: { db: Db; universe: UniverseDb | null; embedder: Embedder },
  topicId: string,
  opts: { searchLimit: number },
): TopicTools {
  const { db, universe, embedder } = ctx;
  const live = and(eq(card.topicId, topicId), eq(card.status, "active"));
  const noQuery = "Give a query: what to look for, in words.";
  const tools: TopicTools = {
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
      if (!query.trim()) throw new ToolError(noQuery);
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
  if (!universe) return tools;
  return {
    ...tools,
    async passages(query) {
      if (!query.trim()) throw new ToolError(noQuery);
      const refs = await groundingOf(db, topicId);
      if (refs.length === 0) return [];
      // A reference that no longer resolves just narrows the scope; an empty scope finds nothing.
      const { chunkIds } = await resolveGrounding(universe, refs);
      const hits = await searchCorpus(universe, embedder, query, {
        k: opts.searchLimit,
        includeChunkIds: chunkIds,
      });
      return hits.map((h) => ({ text: h.text, source: h.source }));
    },
  };
}
