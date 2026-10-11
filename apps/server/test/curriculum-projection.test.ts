import { randomUUID } from "node:crypto";
import { HashEmbedder } from "@spoin/frog/embeddings";
import { curriculum, curriculumSubtopic } from "@spoin/frog/schema";
import { and, asc, count, eq } from "drizzle-orm";
import { describe, expect, it } from "vitest";
import { minCards, projectCurricula } from "../src/curriculum/projection.ts";
import { card, subtopic, topic, topicAlias } from "../src/db/schema.ts";
import { useCorpus } from "./corpus.ts";
import { addCards } from "./fixtures.ts";
import { deps, env } from "./helpers.ts";

/*
 * The deterministic projection, curricula onto topics and subtopics. Both databases are
 * real: what is under test crosses them, and the CASCADE that drops a removed
 * subtopic's cards is the app database's own.
 */

const corpus = useCorpus();
const project = () =>
  projectCurricula({
    db: deps.db,
    universe: corpus,
    embedder: new HashEmbedder(),
    minCardsFraction: env.MIN_CARDS_FRACTION,
  });

type Unit = {
  title: string;
  tiers: Record<string, { target_cards: number; card_types: Record<string, number>; grounding?: string[] }>;
};

const RUST: Unit[] = [
  {
    title: "Ownership",
    tiers: {
      beginner: { target_cards: 10, card_types: { prose: 7, code: 3 }, grounding: ["cs/x.md#Ownership"] },
      intermediate: { target_cards: 8, card_types: { prose: 5, code: 3 }, grounding: ["cs/x.md#Borrowing"] },
    },
  },
  { title: "Smart Pointers", tiers: { intermediate: { target_cards: 6, card_types: { prose: 6 } } } },
];

/** A curriculum as frog's ingester writes it; a fresh name per test, since the app database is shared by the run. */
async function seed(
  units: Unit[] = RUST,
  name = `Rust ${randomUUID().slice(0, 6)}`,
  scope: "topic" | "survey" | "one_shot" = "topic",
) {
  await corpus.delete(curriculum);
  const [c] = await corpus
    .insert(curriculum)
    .values({
      sourcePath: "rust/curriculum.md",
      contentHash: "hash",
      topicName: name,
      description: "Systems programming",
      scope,
      ingestedAt: new Date(),
    })
    .returning();
  await corpus.insert(curriculumSubtopic).values(
    units.map((u, ordinal) => ({
      curriculumId: (c as { id: string }).id,
      ordinal,
      title: u.title,
      description: `About ${u.title}`,
      sourcePaths: ["cs/x.md"],
      tiers: u.tiers,
    })),
  );
  return name;
}

const slugOf = (name: string) => name.toLowerCase().replaceAll(" ", "-");

describe("projecting curricula", () => {
  it("creates a topic with one subtopic per tier", async () => {
    const name = await seed();
    const report = await project();
    expect(report).toMatchObject({ curricula: 1, topicsCreated: 1, subtopicsUpserted: 3 });

    const [t] = await deps.db
      .select()
      .from(topic)
      .where(eq(topic.slug, slugOf(name)));
    expect(t).toMatchObject({
      canonicalName: name,
      description: "Systems programming",
      scope: "topic",
      embeddingModel: "hash",
    });
    expect(t?.curriculumGeneratedAt).toBeInstanceOf(Date);
    expect(t?.curriculumCorpusVersion).toBe("0@empty");
    // Resolvable by ADR-0025's matching: it has an embedding and an alias.
    expect(t?.embedding).toHaveLength(1024);
    const [alias] = await deps.db
      .select()
      .from(topicAlias)
      .where(eq(topicAlias.topicId, t?.id as string));
    expect(alias?.decidedBy).toBe("projection");

    const subs = await deps.db
      .select()
      .from(subtopic)
      .where(eq(subtopic.topicId, t?.id as string))
      .orderBy(asc(subtopic.position), asc(subtopic.difficulty));
    expect(subs.map((s) => [s.title, s.difficulty, s.position])).toEqual([
      ["Ownership", "beginner", 0],
      ["Ownership", "intermediate", 0],
      ["Smart Pointers", "intermediate", 1],
    ]);
    const [beginner, intermediate, smart] = subs;
    // The tiers of one concept share a group.
    expect(beginner?.subtopicGroupId).toBe(intermediate?.subtopicGroupId);
    expect(smart?.subtopicGroupId).not.toBe(beginner?.subtopicGroupId);
    expect(beginner).toMatchObject({
      targetCards: 10,
      minCards: 6,
      cardTypeQuotas: { prose: 7, code: 3 },
      groundingRefs: ["cs/x.md#Ownership"],
    });
    expect(smart?.groundingRefs).toBeNull();
  });

  it("carries a tierless scope onto the topic", async () => {
    const name = await seed(RUST, undefined, "one_shot");
    await project();
    const [t] = await deps.db
      .select({ scope: topic.scope })
      .from(topic)
      .where(eq(topic.slug, slugOf(name)));
    expect(t?.scope).toBe("one_shot");
  });

  it("is idempotent", async () => {
    const name = await seed();
    await project();
    const [t] = await deps.db
      .select({ id: topic.id })
      .from(topic)
      .where(eq(topic.slug, slugOf(name)));
    const ids = async () =>
      (
        await deps.db
          .select({ id: subtopic.id })
          .from(subtopic)
          .where(eq(subtopic.topicId, t?.id as string))
      )
        .map((r) => r.id)
        .sort();
    const first = await ids();
    expect(await project()).toMatchObject({ topicsCreated: 0, topicsUpdated: 1, subtopicsRemoved: 0 });
    expect(await ids()).toEqual(first);
  });

  it("removes a dropped subtopic, and its cards with it", async () => {
    const name = await seed();
    await project();
    const [t] = await deps.db
      .select({ id: topic.id })
      .from(topic)
      .where(eq(topic.slug, slugOf(name)));
    const [smart] = await deps.db
      .select()
      .from(subtopic)
      .where(and(eq(subtopic.title, "Smart Pointers"), eq(subtopic.topicId, t?.id as string)));
    await addCards(smart as typeof subtopic.$inferSelect, 2);

    await seed(
      [{ title: "Ownership", tiers: { beginner: { target_cards: 10, card_types: { prose: 10 } } } }],
      name,
    );
    // Both Smart Pointers and Ownership's intermediate tier are gone from the file.
    expect(await project()).toMatchObject({ subtopicsRemoved: 2 });
    const left = await deps.db
      .select({ title: subtopic.title, difficulty: subtopic.difficulty })
      .from(subtopic)
      .where(eq(subtopic.topicId, t?.id as string));
    expect(left).toEqual([{ title: "Ownership", difficulty: "beginner" }]);
    const [cards] = await deps.db
      .select({ n: count() })
      .from(card)
      .where(eq(card.topicId, t?.id as string));
    expect(cards?.n).toBe(0);
  });

  it("rounds the coverage threshold half to even, as it always has", () => {
    expect(minCards(10, 0.6)).toBe(6);
    expect(minCards(5, 0.5)).toBe(2);
    expect(minCards(7, 0.5)).toBe(4);
    expect(minCards(1, 0.1)).toBe(1);
  });
});
