import { randomUUID } from "node:crypto";
import type { Difficulty } from "@spoin/shared/enums";
import { card, engagementEvent, subtopic, topic, userTopic } from "../src/db/schema.ts";
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

  const subs: (typeof subtopic.$inferSelect)[] = [];
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
      for (let k = 0; k < (opts.cardsPerSubtopic ?? 3); k++) {
        const [c] = await db
          .insert(card)
          .values({
            familyId: randomUUID(),
            status: "active",
            topicId: t.id,
            subtopicId: s.id,
            difficulty,
            title: `${s.title} card ${k}`,
            canonicalTitle: `${s.title} concept ${k}`,
            summary: "A hook.",
            body: `The body of ${s.title} card ${k}.`,
          })
          .returning();
        if (!c) throw new Error("card insert returned nothing");
        cards.push(c);
      }
    }
  }
  return { topic: t, subtopics: subs, cards };
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
