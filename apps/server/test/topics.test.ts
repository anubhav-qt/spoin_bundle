import { randomUUID } from "node:crypto";
import { and, eq } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import {
  cardLike,
  engagementEvent,
  generationJob,
  topic,
  userTopic,
  userTopicProgress,
} from "../src/db/schema.ts";
import { entryTierUnlock } from "../src/topics/progress.ts";
import { addCards, makeTopic, markSeen } from "./fixtures.ts";
import { type Client, client, deps, guest, signedUp, userIdOf } from "./helpers.ts";

const { db } = deps;

async function reader() {
  const c = await signedUp();
  return { c, id: await userIdOf(c) };
}

const progressRow = async (userId: string, topicId: string) =>
  (
    await db
      .select()
      .from(userTopicProgress)
      .where(and(eq(userTopicProgress.userId, userId), eq(userTopicProgress.topicId, topicId)))
  )[0];

const subscribers = async (topicId: string) =>
  (await db.select({ n: topic.subscriberCount }).from(topic).where(eq(topic.id, topicId)))[0]?.n;

/** A topic the user asked for by name, as the request route will leave it. */
async function requested(userId: string, status = "pending") {
  const made = await makeTopic({ cardsPerSubtopic: 0 });
  await db
    .insert(userTopic)
    .values({ userId, topicId: made.topic.id, displayName: "My ask", isCustom: true });
  await db.update(topic).set({ subscriberCount: 1 }).where(eq(topic.id, made.topic.id));
  await db.insert(generationJob).values({ topicId: made.topic.id, status });
  return made;
}

describe("entry tiers (ADR-0032)", () => {
  test("only tiers strictly below the entry start unlocked", () => {
    expect(entryTierUnlock("beginner")).toEqual([false, false, false]);
    expect(entryTierUnlock("intermediate")).toEqual([true, false, false]);
    expect(entryTierUnlock("advanced")).toEqual([true, true, false]);
  });
});

describe("subscriptions", () => {
  test("subscribe, list, refuse a second, unsubscribe", async () => {
    const { c, id } = await reader();
    const { topic: t } = await makeTopic();

    const r = await c.post(`/topics/${t.id}/subscribe?entry_difficulty=intermediate`);
    expect(r.status).toBe(201);
    expect(r.body).toMatchObject({
      id: t.id,
      display_name: t.canonicalName,
      is_custom: false,
      current_difficulty: "intermediate",
      accent_hue: null,
    });
    expect((await progressRow(id, t.id))?.tierUnlocked).toEqual([true, false, false]);
    expect(await subscribers(t.id)).toBe(1);
    expect((await c.get("/topics")).body.map((x: { id: string }) => x.id)).toEqual([t.id]);

    expect((await c.post(`/topics/${t.id}/subscribe`)).status).toBe(409);

    expect((await c.delete(`/topics/${t.id}/subscribe`)).status).toBe(204);
    expect(await progressRow(id, t.id)).toBeUndefined();
    expect(await subscribers(t.id)).toBe(0);
    expect((await c.delete(`/topics/${t.id}/subscribe`)).status).toBe(404);
  });

  test("an unknown topic is a 404, a malformed id a 422, no session a 401", async () => {
    const { c } = await reader();
    expect((await c.post(`/topics/${randomUUID()}/subscribe`)).status).toBe(404);
    expect((await c.post("/topics/nope/subscribe")).status).toBe(422);
    expect((await c.post(`/topics/${randomUUID()}/subscribe?entry_difficulty=expert`)).status).toBe(422);
    expect((await client().get("/topics")).status).toBe(401);
  });

  test("onboarding follows the known topics once each and flips the gate", async () => {
    const c = await guest();
    const a = await makeTopic();
    const b = await makeTopic();
    const r = await c.post("/topics/onboarding/complete", {
      topics: [
        { topic_id: a.topic.id, entry_difficulty: "advanced" },
        { topic_id: randomUUID() },
        { topic_id: b.topic.id },
        { topic_id: a.topic.id },
      ],
    });
    expect(r.status).toBe(200);
    expect(
      r.body.map((t: { id: string; current_difficulty: string }) => [t.id, t.current_difficulty]),
    ).toEqual([
      [a.topic.id, "advanced"],
      [b.topic.id, "beginner"],
    ]);
    expect((await c.get("/auth/me")).body.onboarding_complete).toBe(true);
  });
});

describe("colour (ADR-0034, ADR-0051, ADR-0075)", () => {
  test("a chosen hue, the opt-out, and a reset", async () => {
    const { c } = await reader();
    const { topic: t } = await makeTopic();
    await c.post(`/topics/${t.id}/subscribe`);

    expect((await c.patch(`/topics/${t.id}/color`, { hue: 200 })).body.accent_hue).toBe(200);
    expect((await c.patch(`/topics/${t.id}/color`, { hue: -1 })).body.accent_hue).toBe(-1);
    // The hash stand-in has no meaning to pick by, so a reset hands back to the client default.
    expect((await c.patch(`/topics/${t.id}/color`, { hue: null })).body.accent_hue).toBeNull();
    expect((await c.patch(`/topics/${t.id}/color`, { hue: 360 })).status).toBe(422);
  });

  test("only a subscription can be coloured", async () => {
    const { c } = await reader();
    const { topic: t } = await makeTopic();
    expect((await c.patch(`/topics/${t.id}/color`, { hue: 10 })).status).toBe(404);
  });
});

describe("progression (ADR-0009)", () => {
  test("coverage is the weakest subtopic's, and reaching the gate unlocks and latches", async () => {
    const { c, id } = await reader();
    const { topic: t, subtopics, cards } = await makeTopic({ subtopicsPerTier: 2, cardsPerSubtopic: 5 });
    await c.post(`/topics/${t.id}/subscribe`);
    const [a, b] = subtopics as [(typeof subtopics)[0], (typeof subtopics)[0]];
    const inA = cards.filter((k) => k.subtopicId === a.id);
    const inB = cards.filter((k) => k.subtopicId === b.id);

    for (const k of inA) await markSeen(id, k);
    for (const k of inB.slice(0, 2)) await markSeen(id, k);
    expect((await c.get(`/topics/${t.id}/progress`)).body).toMatchObject({
      coverage: 0.4,
      quiz_unlocked: false,
    });

    for (const k of inB.slice(2, 4)) await markSeen(id, k);
    // Stats reads the snapshot: unlocked, but the latch is the progress endpoint's to write.
    expect((await c.get(`/topics/${t.id}/stats`)).body).toMatchObject({ coverage: 0.8, quiz_unlocked: true });
    expect((await progressRow(id, t.id))?.tierUnlocked).toEqual([false, false, false]);

    expect((await c.get(`/topics/${t.id}/progress`)).body).toMatchObject({
      current_difficulty: "beginner",
      coverage: 0.8,
      quiz_unlocked: true,
      tier_quiz_passed: [false, false, false],
      mastered: false,
    });
    expect((await progressRow(id, t.id))?.tierUnlocked).toEqual([true, false, false]);

    // Ten more cards land in b: coverage falls, the unlock does not.
    await addCards(b, 10, 5);
    const after = (await c.get(`/topics/${t.id}/progress`)).body;
    expect(after.coverage).toBeCloseTo(4 / 15);
    expect(after.quiz_unlocked).toBe(true);
  });

  test("a tierless topic ignores the entry tier and gates on every subtopic at every difficulty", async () => {
    const { c, id } = await reader();
    const { topic: t, subtopics, cards } = await makeTopic({ scope: "one_shot", cardsPerSubtopic: 5 });
    const r = await c.post(`/topics/${t.id}/subscribe?entry_difficulty=advanced`);
    expect(r.body).toMatchObject({ scope: "one_shot", current_difficulty: "beginner" });
    expect(await progressRow(id, t.id)).toMatchObject({
      currentDifficulty: "beginner",
      tierUnlocked: [false, false, false],
    });

    // Every beginner and intermediate card read, three of five advanced: the advanced subtopic governs.
    for (const s of subtopics) {
      const inS = cards.filter((k) => k.subtopicId === s.id);
      for (const k of inS.slice(0, s.difficulty === "advanced" ? 3 : 5)) await markSeen(id, k);
    }
    expect((await c.get(`/topics/${t.id}/progress`)).body).toMatchObject({
      scope: "one_shot",
      current_difficulty: "beginner",
      coverage: 0.6,
      quiz_unlocked: false,
    });

    const fourth = cards.filter((k) => k.difficulty === "advanced")[3];
    if (!fourth) throw new Error("the fixture has five advanced cards");
    await markSeen(id, fourth);
    expect((await c.get(`/topics/${t.id}/progress`)).body).toMatchObject({
      coverage: 0.8,
      quiz_unlocked: true,
    });
    // The one quiz is the advanced slot's.
    expect((await progressRow(id, t.id))?.tierUnlocked).toEqual([false, false, true]);
    expect((await c.get(`/topics/${t.id}/stats`)).body).toMatchObject({ scope: "one_shot", coverage: 0.8 });
  });

  test("a topic made tierless after it was followed shows no tier", async () => {
    const { c } = await reader();
    const { topic: t } = await makeTopic();
    await c.post(`/topics/${t.id}/subscribe?entry_difficulty=intermediate`);
    // A requested topic is followed at the requester's entry tier before the harness picks its scope.
    await db.update(topic).set({ scope: "survey" }).where(eq(topic.id, t.id));
    expect((await c.get("/topics")).body[0]).toMatchObject({
      scope: "survey",
      current_difficulty: "beginner",
    });
    expect((await c.get(`/topics/${t.id}/progress`)).body.current_difficulty).toBe("beginner");
  });

  test("the curriculum lists every subtopic in authoring order with its own coverage", async () => {
    const { c, id } = await reader();
    const { topic: t, cards } = await makeTopic({ cardsPerSubtopic: 5 });
    await c.post(`/topics/${t.id}/subscribe`);
    for (const k of cards.slice(0, 4)) await markSeen(id, k);

    const r = await c.get(`/topics/${t.id}/curriculum`);
    expect(r.body.subtopics.map((s: { difficulty: string }) => s.difficulty)).toEqual([
      "beginner",
      "intermediate",
      "advanced",
    ]);
    expect(r.body.subtopics[0]).toMatchObject({
      total_cards: 5,
      seen_cards: 4,
      coverage: 0.8,
      covered: true,
    });
    expect(r.body.subtopics[1]).toMatchObject({ seen_cards: 0, covered: false });
  });

  test("stats count this user's likes on the topic and its note and share events", async () => {
    const { c, id } = await reader();
    const { topic: t, cards } = await makeTopic();
    await c.post(`/topics/${t.id}/subscribe`);
    const [k] = cards as [(typeof cards)[0]];
    await db.insert(cardLike).values({ userId: id, cardId: k.id });
    for (const kind of ["note", "share", "share"] as const) {
      await db.insert(engagementEvent).values({
        id: randomUUID(),
        userId: id,
        cardId: k.id,
        topicId: t.id,
        subtopicId: k.subtopicId,
        kind,
      });
    }
    expect((await c.get(`/topics/${t.id}/stats`)).body).toMatchObject({
      likes: 1,
      saves: 0,
      notes: 1,
      shares: 2,
    });
  });
});

describe("discovery (ADR-0038, ADR-0053)", () => {
  test("topics below the live threshold show only to their followers", async () => {
    const { c } = await reader();
    const live = await makeTopic();
    const thin = await makeTopic({ cardsPerSubtopic: 1 });
    const mine = await makeTopic({ cardsPerSubtopic: 1 });
    await c.post(`/topics/${mine.topic.id}/subscribe`);

    const all = new Map(
      (await c.get("/topics/all")).body.map((t: { topic_id: string; followed: boolean }) => [
        t.topic_id,
        t.followed,
      ]),
    );
    expect(all.get(live.topic.id)).toBe(false);
    expect(all.has(thin.topic.id)).toBe(false);
    expect(all.get(mine.topic.id)).toBe(true);
  });

  test("discover is the top live unfollowed topics, five at most", async () => {
    const { c } = await reader();
    const popular = await makeTopic();
    const thin = await makeTopic({ cardsPerSubtopic: 1 });
    const followed = await makeTopic();
    for (const t of [popular, thin, followed])
      await db.update(topic).set({ subscriberCount: 1_000_000 }).where(eq(topic.id, t.topic.id));
    await c.post(`/topics/${followed.topic.id}/subscribe`);

    const r = await c.get("/topics/discover?mode=for_you");
    const ids = r.body.map((t: { topic_id: string }) => t.topic_id);
    expect(ids).toContain(popular.topic.id);
    expect(ids).not.toContain(thin.topic.id);
    expect(ids).not.toContain(followed.topic.id);
    expect(ids.length).toBeLessThanOrEqual(5);
    expect((await c.get("/topics/discover?mode=sideways")).status).toBe(422);
  });
});

describe("requested topics", () => {
  test("the custom list carries the latest job's status", async () => {
    const { c, id } = await reader();
    const { topic: t } = await requested(id, "failed");
    await db.insert(generationJob).values({ topicId: t.id, status: "running" });
    const r = await c.get("/topics/custom");
    expect(r.body).toEqual([
      expect.objectContaining({ topic_id: t.id, display_name: "My ask", generation_status: "running" }),
    ]);
  });

  test("generation progress reports the job and whether the topic is live yet", async () => {
    const { c, id } = await reader();
    const { topic: t } = await requested(id);
    expect((await c.get(`/topics/${t.id}/generation-progress`)).body).toEqual({
      status: "pending",
      stage: null,
      topic_name: null,
      subtopics: [],
      error: null,
      topic_live: false,
    });

    await db
      .update(generationJob)
      .set({
        status: "failed",
        lastError: "the tadpole gave up",
        progress: { stage: "cards", topic_name: "Ask" },
      })
      .where(eq(generationJob.topicId, t.id));
    expect((await c.get(`/topics/${t.id}/generation-progress`)).body).toMatchObject({
      status: "failed",
      stage: "cards",
      topic_name: "Ask",
      error: "the tadpole gave up",
    });

    const live = await makeTopic();
    await db.insert(generationJob).values({ topicId: live.topic.id, status: "completed" });
    expect((await c.get(`/topics/${live.topic.id}/generation-progress`)).body.topic_live).toBe(true);
    expect((await c.get(`/topics/${randomUUID()}/generation-progress`)).status).toBe(404);
  });

  test("cancelling a pending request removes the job, the subscription and the orphaned topic", async () => {
    const { c, id } = await reader();
    const { topic: t } = await requested(id);
    expect((await c.delete(`/topics/${t.id}/generation-job`)).status).toBe(204);
    expect(await db.select().from(generationJob).where(eq(generationJob.topicId, t.id))).toEqual([]);
    expect(await db.select().from(topic).where(eq(topic.id, t.id))).toEqual([]);
    expect((await c.get("/topics/custom")).body).toEqual([]);
  });

  test("once the job is running it can no longer be cancelled", async () => {
    const { c, id } = await reader();
    const { topic: t } = await requested(id, "running");
    expect((await c.delete(`/topics/${t.id}/generation-job`)).status).toBe(409);
    expect((await c.get("/topics/custom")).body).toHaveLength(1);
  });

  test("another follower keeps the topic alive, and only the requester may cancel", async () => {
    const { c, id } = await reader();
    const { topic: t } = await requested(id);
    const other: Client = await signedUp();
    expect((await other.delete(`/topics/${t.id}/generation-job`)).status).toBe(404);
    await other.post(`/topics/${t.id}/subscribe`);

    expect((await c.delete(`/topics/${t.id}/generation-job`)).status).toBe(204);
    expect(await subscribers(t.id)).toBe(1);
    expect((await other.get("/topics")).body.map((x: { id: string }) => x.id)).toEqual([t.id]);
  });
});
