import { randomUUID } from "node:crypto";
import type { Difficulty } from "@spoin/shared/enums";
import { card, engagementEvent, subtopic, topic, userCardState, userTopic } from "../src/db/schema.ts";
import type { Rng } from "../src/feed/ranking.ts";
import { deps } from "./helpers.ts";

/*
 * Corpus rows inserted directly, the way the tadpoles will write them. Tests that need
 * a topic with cards build one here rather than through the generation path.
 */

const { db } = deps;
let topics = 0;

export async function makeTopic(
  opts: { name?: string; subtopicsPerTier?: number; cardsPerSubtopic?: number } = {},
) {
  topics += 1;
  const name = opts.name ?? `Topic ${topics} ${randomUUID().slice(0, 6)}`;
  const [t] = await db
    .insert(topic)
    .values({ slug: name.toLowerCase().replaceAll(/\W+/g, "-"), canonicalName: name })
    .returning();
  if (!t) throw new Error("topic insert returned nothing");

  const subs: Subtopic[] = [];
  const cards: (typeof card.$inferSelect)[] = [];
  for (const difficulty of ["beginner", "intermediate", "advanced"] as Difficulty[]) {
    for (let i = 0; i < (opts.subtopicsPerTier ?? 1); i++) {
      const [s] = await db
        .insert(subtopic)
        .values({
          topicId: t.id,
          difficulty,
          title: `${difficulty} ${i}`,
          description: `What a ${difficulty} learns, part ${i}.`,
          targetCards: 5,
          minCards: 3,
          position: i,
        })
        .returning();
      if (!s) throw new Error("subtopic insert returned nothing");
      subs.push(s);
      cards.push(...(await addCards(s, opts.cardsPerSubtopic ?? 3)));
    }
  }
  return { topic: t, subtopics: subs, cards };
}

type Subtopic = typeof subtopic.$inferSelect;

/** Active cards in a subtopic, numbered after any it already has. */
export async function addCards(s: Subtopic, n: number, from = 0) {
  if (n === 0) return [];
  return db
    .insert(card)
    .values(
      Array.from({ length: n }, (_, i) => ({
        familyId: randomUUID(),
        status: "active" as const,
        topicId: s.topicId,
        subtopicId: s.id,
        difficulty: s.difficulty,
        title: `${s.title} card ${from + i}`,
        canonicalTitle: `${s.title} concept ${from + i}`,
        summary: "A hook.",
        body: `The body of ${s.title} card ${from + i}.`,
      })),
    )
    .returning();
}

export async function follow(userId: string, topicId: string, displayName = "My topic") {
  await db.insert(userTopic).values({ userId, topicId, displayName });
}

/** A completion event, the fact every "cards read" count is built from. */
export async function read(
  userId: string,
  c: typeof card.$inferSelect,
  at = new Date(),
  kind: "explicit_complete" | "dwell_complete" = "explicit_complete",
) {
  await db.insert(engagementEvent).values({
    id: randomUUID(),
    userId,
    cardId: c.id,
    topicId: c.topicId,
    subtopicId: c.subtopicId,
    kind,
    occurredAt: at,
  });
}

/** The seen-state row the coverage gate counts (ADR-0010). */
export async function markSeen(userId: string, c: typeof card.$inferSelect) {
  await db.insert(userCardState).values({
    userId,
    cardId: c.id,
    topicId: c.topicId,
    subtopicId: c.subtopicId,
    state: "seen",
    seenAt: new Date(),
    completedVia: "explicit_complete",
  });
}

/** mulberry32: a few lines, and the same sequence on every run. */
export function seeded(seed: number): Rng {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
