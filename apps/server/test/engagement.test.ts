import { randomUUID } from "node:crypto";
import { and, eq } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import {
  cardLike,
  engagementEvent,
  userCardState,
  userSessionTopicSignal,
  userSubtopicProgress,
  userTopicCycle,
  userTopicDifficultyProgress,
} from "../src/db/schema.ts";
import { makeTopic } from "./fixtures.ts";
import { client, deps, signedUp, userIdOf } from "./helpers.ts";

const { db } = deps;

async function reader() {
  const c = await signedUp();
  const id = await userIdOf(c);
  const { topic, cards } = await makeTopic({ cardsPerSubtopic: 5 });
  return { c, id, topic, cards };
}

const event = (cardId: string, kind: string, extra: Record<string, unknown> = {}) => ({
  id: randomUUID(),
  card_id: cardId,
  kind,
  ...extra,
});

const stateOf = async (userId: string, cardId: string) =>
  (
    await db
      .select()
      .from(userCardState)
      .where(and(eq(userCardState.userId, userId), eq(userCardState.cardId, cardId)))
  )[0];

describe("engagement ingest (ADR-0011)", () => {
  test("a retried event collides instead of counting twice", async () => {
    const { c, cards } = await reader();
    const e = event(cards[0]?.id as string, "impression");
    expect((await c.post("/engagement/events", { events: [e] })).body).toEqual({
      accepted: 1,
      duplicates: 0,
      rejected: 0,
    });
    const again = await c.post("/engagement/events", { events: [e] });
    expect(again.status).toBe(202);
    expect(again.body).toEqual({ accepted: 0, duplicates: 1, rejected: 0 });
  });

  test("both completion paths mark SEEN, and each is recorded as itself", async () => {
    const { c, id, cards } = await reader();
    const [a, b] = cards as [(typeof cards)[0], (typeof cards)[0]];
    await c.post("/engagement/events", {
      events: [event(a.id, "explicit_complete"), event(b.id, "dwell_complete", { dwell_ms: 12_000 })],
    });
    expect(await stateOf(id, a.id)).toMatchObject({ state: "seen", completedVia: "explicit_complete" });
    expect(await stateOf(id, b.id)).toMatchObject({ state: "seen", completedVia: "dwell_complete" });

    const [sub] = await db
      .select()
      .from(userSubtopicProgress)
      .where(eq(userSubtopicProgress.subtopicId, a.subtopicId));
    expect(sub).toMatchObject({ seenCount: 2, totalCount: 5 });
    const [tier] = await db
      .select()
      .from(userTopicDifficultyProgress)
      .where(
        and(
          eq(userTopicDifficultyProgress.userId, id),
          eq(userTopicDifficultyProgress.difficulty, "beginner"),
        ),
      );
    expect(tier).toMatchObject({ seenCount: 2, totalCount: 5 });
  });

  test("an impression means shown, never read: DEFERRED at the current cycle", async () => {
    const { c, id, topic, cards } = await reader();
    const k = cards[0] as (typeof cards)[0];
    await db
      .insert(userTopicCycle)
      .values({ userId: id, topicId: topic.id, difficulty: "beginner", cycle: 3 });
    await c.post("/engagement/events", { events: [event(k.id, "impression")] });
    expect(await stateOf(id, k.id)).toMatchObject({ state: "deferred", deferredCycle: 3 });
    expect(await db.select().from(userSubtopicProgress).where(eq(userSubtopicProgress.userId, id))).toEqual(
      [],
    );
  });

  test("SEEN is terminal: a skip after a completion does not walk it back", async () => {
    const { c, id, cards } = await reader();
    const k = cards[0] as (typeof cards)[0];
    await c.post("/engagement/events", { events: [event(k.id, "explicit_complete"), event(k.id, "skip")] });
    expect((await stateOf(id, k.id))?.state).toBe("seen");
  });

  test("an implausible dwell and an unknown card are rejected without sinking the batch", async () => {
    const { c, cards } = await reader();
    const k = cards[0] as (typeof cards)[0];
    const r = await c.post("/engagement/events", {
      events: [
        event(k.id, "dwell_complete", { dwell_ms: 9 * 60 * 60 * 1000 }),
        event(randomUUID(), "impression"),
        event(k.id, "expand"),
      ],
    });
    expect(r.body).toEqual({ accepted: 1, duplicates: 0, rejected: 2 });
    expect(
      (await c.post("/engagement/events", { events: [event(k.id, "expand", { dwell_ms: -1 })] })).status,
    ).toBe(422);
  });

  test("occurred_at is the server's, whatever the client's clock says", async () => {
    const { c, cards } = await reader();
    const e = event(cards[0]?.id as string, "impression", { client_occurred_at: "1999-01-01T00:00:00Z" });
    const before = Date.now();
    await c.post("/engagement/events", { events: [e] });
    const [row] = await db.select().from(engagementEvent).where(eq(engagementEvent.id, e.id));
    expect(row?.occurredAt.getTime()).toBeGreaterThanOrEqual(before - 1000);
    expect(row?.clientOccurredAt?.toISOString()).toBe("1999-01-01T00:00:00.000Z");
  });

  test("like and unlike round-trip", async () => {
    const { c, id, cards } = await reader();
    const k = cards[0] as (typeof cards)[0];
    const likes = () =>
      db
        .select()
        .from(cardLike)
        .where(and(eq(cardLike.userId, id), eq(cardLike.cardId, k.id)));
    await c.post("/engagement/events", { events: [event(k.id, "like")] });
    expect(await likes()).toHaveLength(1);
    await c.post("/engagement/events", { events: [event(k.id, "unlike")] });
    expect(await likes()).toHaveLength(0);
  });

  test("the session signal accumulates, an undo cancels, and a lapsed session starts over", async () => {
    const { c, id, topic, cards } = await reader();
    const k = cards[0] as (typeof cards)[0];
    const score = async () =>
      (
        await db
          .select()
          .from(userSessionTopicSignal)
          .where(and(eq(userSessionTopicSignal.userId, id), eq(userSessionTopicSignal.topicId, topic.id)))
      )[0]?.score;

    await c.post("/engagement/events", {
      events: [event(k.id, "like"), event(k.id, "expand", { dwell_ms: 4000 })],
    });
    expect(await score()).toBeCloseTo(3 + 0.5 + 4 * 0.05);
    await c.post("/engagement/events", { events: [event(k.id, "unlike")] });
    expect(await score()).toBeCloseTo(0.7);

    await db
      .update(userSessionTopicSignal)
      .set({ lastEventAt: new Date(Date.now() - 2 * 3600 * 1000) })
      .where(eq(userSessionTopicSignal.userId, id));
    await c.post("/engagement/events", { events: [event(k.id, "skip")] });
    expect(await score()).toBeCloseTo(-1.5);
  });

  test("a batch is capped at 200 and needs a session", async () => {
    const { c, cards } = await reader();
    const many = Array.from({ length: 201 }, () => event(cards[0]?.id as string, "impression"));
    expect((await c.post("/engagement/events", { events: many })).status).toBe(422);
    expect((await client().post("/engagement/events", { events: [] })).status).toBe(401);
  });
});
