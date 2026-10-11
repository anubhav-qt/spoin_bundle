import { randomUUID } from "node:crypto";
import type { EngagementKind } from "@spoin/shared/enums";
import { and, eq, inArray } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import {
  card,
  feedPlan,
  userSessionTopicSignal,
  userTopicCycle,
  userTopicDifficultyProgress,
} from "../src/db/schema.ts";
import { ingest } from "../src/engagement/service.ts";
import { buildSlate, page } from "../src/feed/service.ts";
import { addCards, follow, makeTopic, seeded } from "./fixtures.ts";
import { client, deps, env, signedUp, userIdOf } from "./helpers.ts";

/*
 * ADR-0010: deferred-card cycling "is genuinely fiddly and needs real test coverage. A
 * bug here shows as 'I keep seeing the same cards', which is the most damaging feed
 * bug there is." So it is covered here, against the real database.
 */

const { db } = deps;
const knobs = (o: Partial<typeof env> = {}) => ({ ...env, RANK_EPSILON: 0, ...o });

/**
 * One followed topic, uneven on purpose: 12 beginner cards and an intermediate pool
 * thinner than the mix asks for, which is the normal case at launch.
 */
async function corpus() {
  const c = await signedUp();
  const userId = await userIdOf(c);
  const made = await makeTopic({ cardsPerSubtopic: 0 });
  const [beginner, intermediate] = made.subtopics as [(typeof made.subtopics)[0], (typeof made.subtopics)[0]];
  const beginners = await addCards(beginner, 12);
  const intermediates = await addCards(intermediate, 2);
  await follow(userId, made.topic.id, "Testing");
  return { c, userId, topic: made.topic, beginners, intermediates };
}

const engage = (userId: string, cardIds: string[], kind: EngagementKind) =>
  ingest(
    db,
    env,
    userId,
    cardIds.map((id) => ({ id: randomUUID(), card_id: id, kind })),
  );

async function difficulties(cardIds: string[]) {
  const rows = await db
    .select({ id: card.id, d: card.difficulty })
    .from(card)
    .where(inArray(card.id, cardIds));
  const by = new Map(rows.map((r) => [r.id, r.d]));
  return cardIds.map((id) => by.get(id));
}
const count = <T>(xs: T[], x: T) => xs.filter((y) => y === x).length;

const cycleOf = async (userId: string, topicId: string) =>
  (
    await db
      .select({ cycle: userTopicCycle.cycle })
      .from(userTopicCycle)
      .where(
        and(
          eq(userTopicCycle.userId, userId),
          eq(userTopicCycle.topicId, topicId),
          eq(userTopicCycle.difficulty, "beginner"),
        ),
      )
  )[0]?.cycle;

async function readFraction(userId: string, topicId: string, seen: number, total: number) {
  await db
    .insert(userTopicDifficultyProgress)
    .values({ userId, topicId, difficulty: "beginner", seenCount: seen, totalCount: total });
}

describe("building a slate", () => {
  test("a fresh tier is entirely the current difficulty", async () => {
    const { userId, topic } = await corpus();
    const slate = await buildSlate(db, knobs({ SLATE_SIZE: 10 }), userId, topic.id, { rng: seeded(1) });
    const d = await difficulties(slate?.cardIds ?? []);
    expect([count(d, "beginner"), count(d, "intermediate")]).toEqual([10, 0]);
  });

  test("past the ramp the mix is the configured 80/20, exactly", async () => {
    const { userId, topic } = await corpus();
    await readFraction(userId, topic.id, 8, 12);
    const slate = await buildSlate(db, knobs({ SLATE_SIZE: 10 }), userId, topic.id, { rng: seeded(1) });
    const d = await difficulties(slate?.cardIds ?? []);
    expect([count(d, "beginner"), count(d, "intermediate")]).toEqual([8, 2]);
  });

  test("a short pool serves short rather than wrong", async () => {
    const { userId, topic } = await corpus();
    await readFraction(userId, topic.id, 8, 12);
    // 25 slots want 5 intermediate; there are 2, and no beginner card wears an intermediate slot.
    const slate = await buildSlate(db, knobs({ SLATE_SIZE: 25 }), userId, topic.id, { rng: seeded(1) });
    const d = await difficulties(slate?.cardIds ?? []);
    expect([count(d, "beginner"), count(d, "intermediate")]).toEqual([12, 2]);
    expect(slate?.degraded).toBe(false);
  });

  test("a SEEN card never returns", async () => {
    const { userId, topic } = await corpus();
    const k = knobs({ SLATE_SIZE: 10 });
    const first = await buildSlate(db, k, userId, topic.id, { rng: seeded(1) });
    const done = first?.cardIds[0] as string;
    await engage(userId, [done], "explicit_complete");
    expect((await buildSlate(db, k, userId, topic.id, { rng: seeded(1) }))?.cardIds).not.toContain(done);
  });

  test("a deferred card waits while anything unseen remains", async () => {
    const { userId, topic, beginners } = await corpus();
    const skipped = beginners[0]?.id as string;
    await engage(userId, [skipped], "skip");
    const slate = await buildSlate(db, knobs({ SLATE_SIZE: 10 }), userId, topic.id, { rng: seeded(1) });
    expect(slate?.cardIds).not.toContain(skipped);
    expect(await cycleOf(userId, topic.id)).toBeUndefined();
  });

  test("the difficulty turns over once everything has been shown", async () => {
    const { userId, topic, beginners } = await corpus();
    const [skipped, ...rest] = beginners.map((b) => b.id) as [string, ...string[]];
    await engage(userId, [skipped], "skip");
    // Everything else read, so the deferred card is the only one that could appear.
    await engage(userId, rest, "explicit_complete");
    const slate = await buildSlate(db, knobs({ SLATE_SIZE: 10 }), userId, topic.id, { rng: seeded(1) });
    expect(slate?.cardIds).toContain(skipped);
    expect(await cycleOf(userId, topic.id)).toBe(1);
  });

  test("an empty difficulty does not turn over: nothing deferred means nothing to release", async () => {
    const { userId, topic, beginners } = await corpus();
    await engage(
      userId,
      beginners.map((b) => b.id),
      "explicit_complete",
    );
    await buildSlate(db, knobs({ SLATE_SIZE: 10 }), userId, topic.id, { rng: seeded(1) });
    expect(await cycleOf(userId, topic.id)).toBeUndefined();
  });
});

describe("paging", () => {
  test("a page is the page size, with no card twice", async () => {
    const { userId } = await corpus();
    const p = await page(db, knobs({ PAGE_SIZE: 5, SLATE_SIZE: 10 }), userId, { rng: seeded(1) });
    expect(p.cardIds).toHaveLength(5);
    expect(new Set(p.cardIds).size).toBe(5);
  });

  test("a slate running dry mid-page never repeats a card", async () => {
    const { userId } = await corpus();
    const p = await page(db, knobs({ PAGE_SIZE: 10, SLATE_SIZE: 3 }), userId, { rng: seeded(1) });
    expect(new Set(p.cardIds).size).toBe(p.cardIds.length);
  });

  test("the next page does not repeat the last", async () => {
    const { userId } = await corpus();
    const k = knobs({ PAGE_SIZE: 4, SLATE_SIZE: 14 });
    const first = await page(db, k, userId, { rng: seeded(1) });
    const second = await page(db, k, userId, { rng: seeded(1) });
    expect(first.cardIds.filter((id) => second.cardIds.includes(id))).toEqual([]);
  });

  test("no subscriptions is an empty, exhausted feed, not an error", async () => {
    const userId = await userIdOf(await signedUp());
    expect(await page(db, env, userId)).toMatchObject({ cardIds: [], exhausted: true });
  });

  test("a followed topic with nothing written yet is exhausted", async () => {
    const userId = await userIdOf(await signedUp());
    const { topic } = await makeTopic({ cardsPerSubtopic: 0 });
    await follow(userId, topic.id);
    expect(await page(db, env, userId)).toMatchObject({ cardIds: [], exhausted: true, recycling: false });
  });

  test("a repeat pass says so", async () => {
    const userId = await userIdOf(await signedUp());
    const { topic, subtopics } = await makeTopic({ cardsPerSubtopic: 0 });
    const beginners = await addCards(subtopics[0] as (typeof subtopics)[0], 3);
    await follow(userId, topic.id);
    // All shown, none read: the whole tier is deferred, so the cycle turns over.
    await engage(
      userId,
      beginners.map((b) => b.id),
      "impression",
    );
    const p = await page(db, knobs({ PAGE_SIZE: 3 }), userId, { rng: seeded(1) });
    expect(new Set(p.cardIds)).toEqual(new Set(beginners.map((b) => b.id)));
    expect(p.recycling).toBe(true);
  });
});

describe("session shares in the plan (ADR-0055)", () => {
  /** Equally stocked topics, so any difference in the plan comes from the session signal. */
  async function topics(n: number) {
    const userId = await userIdOf(await signedUp());
    const made: { id: string; cards: string[] }[] = [];
    for (let i = 0; i < n; i++) {
      const { topic, subtopics } = await makeTopic({ cardsPerSubtopic: 0 });
      const cards = await addCards(subtopics[0] as (typeof subtopics)[0], 30);
      await follow(userId, topic.id);
      made.push({ id: topic.id, cards: cards.map((c) => c.id) });
    }
    return { userId, topics: made };
  }

  async function planCounts(userId: string) {
    await page(db, env, userId);
    const [plan] = await db.select().from(feedPlan).where(eq(feedPlan.userId, userId));
    const out = new Map<string, number>();
    for (const t of plan?.topicOrder ?? []) out.set(t, (out.get(t) ?? 0) + 1);
    return out;
  }
  const spread = (m: Map<string, number>) => Math.max(...m.values()) - Math.min(...m.values());

  test("a fresh session is uniform", async () => {
    const { userId } = await topics(4);
    const c = await planCounts(userId);
    expect(c.size).toBe(4);
    expect(spread(c)).toBeLessThanOrEqual(1);
  });

  test("engagement shifts the feed toward that topic", async () => {
    const {
      userId,
      topics: [fav, ignored],
    } = await topics(4);
    const before = await planCounts(userId);
    await engage(userId, fav?.cards.slice(0, 6) ?? [], "explicit_complete");
    const after = await planCounts(userId);
    expect(after.get(fav?.id as string)).toBeGreaterThan(before.get(fav?.id as string) ?? 0);
    expect(after.get(ignored?.id as string)).toBeLessThan(before.get(ignored?.id as string) ?? 0);
  });

  test("a dominant topic never takes more than half, and an ignored one keeps its floor", async () => {
    const { userId, topics: ts } = await topics(4);
    const [fav, ...others] = ts as [(typeof ts)[0], ...typeof ts];
    for (const kind of ["explicit_complete", "like", "bookmark", "share"] as const)
      await engage(userId, fav.cards.slice(0, 20), kind);
    for (const t of others.slice(0, 2)) await engage(userId, t.cards.slice(0, 20), "explicit_complete");
    const disliked = others[2] as (typeof ts)[0];
    await engage(userId, disliked.cards.slice(0, 20), "skip");

    const c = await planCounts(userId);
    const total = [...c.values()].reduce((x, y) => x + y, 0);
    // One slot of slack: the plan is whole slots.
    expect(c.get(fav.id)).toBeLessThanOrEqual(env.SESSION_SHARE_CEILING * total + 1);
    expect(c.get(disliked.id)).toBeGreaterThanOrEqual(env.SESSION_SHARE_FLOOR * total - 1);
  });

  test("a stale profile reads as uniform before any new event", async () => {
    const {
      userId,
      topics: [fav, other],
    } = await topics(4);
    await engage(userId, fav?.cards.slice(0, 10) ?? [], "explicit_complete");
    const skewed = await planCounts(userId);
    expect(skewed.get(fav?.id as string)).toBeGreaterThan(skewed.get(other?.id as string) ?? 0);

    await db
      .update(userSessionTopicSignal)
      .set({ lastEventAt: new Date(Date.now() - (env.SESSION_WINDOW_SECONDS + 3600) * 1000) })
      .where(eq(userSessionTopicSignal.userId, userId));
    expect(spread(await planCounts(userId))).toBeLessThanOrEqual(1);
  });

  test("the plan is reused while the profile holds, and rebuilt once it moves", async () => {
    const {
      userId,
      topics: [fav],
    } = await topics(4);
    const planOf = async () => (await db.select().from(feedPlan).where(eq(feedPlan.userId, userId)))[0];
    await planCounts(userId);
    const first = await planOf();
    await planCounts(userId);
    const second = await planOf();
    expect(second?.shareFingerprint).toBe(first?.shareFingerprint);
    expect(second?.topicOrder).toEqual(first?.topicOrder);

    await engage(userId, fav?.cards.slice(0, 8) ?? [], "explicit_complete");
    await planCounts(userId);
    expect((await planOf())?.shareFingerprint).not.toBe(first?.shareFingerprint);
  });
});

describe("GET /feed", () => {
  test("cards come with their subtopic's title and the reader's own note", async () => {
    const { c, beginners } = await corpus();
    const first = await c.get("/feed");
    expect(first.status).toBe(200);
    expect(first.body).toMatchObject({ degraded: false, exhausted: false, recycling: false });
    expect(first.body.cards).toHaveLength(env.PAGE_SIZE);
    expect(first.body.cards[0]).toMatchObject({ subtopic_title: "beginner 0", note: null, seen: false });

    const target = beginners.find((b) => !first.body.cards.some((x: { id: string }) => x.id === b.id));
    expect(target).toBeDefined();
    await c.put(`/cards/${target?.id}/note`, { body: "remember this" });
    const second = await c.get(`/feed?position=${first.body.next_position}`);
    expect(second.body.cards.find((x: { id: string }) => x.id === target?.id)?.note).toBe("remember this");
  });

  test("one topic or several, as repeated parameters", async () => {
    const { c, userId, topic } = await corpus();
    const { topic: other } = await makeTopic();
    await follow(userId, other.id);
    const one = await c.get(`/feed?topics=${other.id}`);
    expect(one.status).toBe(200);
    expect(new Set(one.body.cards.map((x: { topic_id: string }) => x.topic_id))).toEqual(new Set([other.id]));
    const both = await c.get(`/feed?topics=${other.id}&topics=${topic.id}`);
    expect(both.status).toBe(200);
    expect(new Set(both.body.cards.map((x: { topic_id: string }) => x.topic_id))).toEqual(
      new Set([other.id, topic.id]),
    );
  });

  test("a malformed filter or position is a 422, and no session is a 401", async () => {
    const { c } = await corpus();
    expect((await c.get("/feed?topics=nope")).status).toBe(422);
    expect((await c.get("/feed?position=-1")).status).toBe(422);
    expect((await client().get("/feed")).status).toBe(401);
  });
});

describe("cards and collections", () => {
  test("a single card needs no session; the note shows only to its author", async () => {
    const { c, beginners } = await corpus();
    const id = beginners[0]?.id as string;
    await c.put(`/cards/${id}/note`, { body: "mine" });
    expect((await c.get(`/cards/${id}`)).body).toMatchObject({
      id,
      note: "mine",
      subtopic_title: "beginner 0",
    });
    const anon = await client().get(`/cards/${id}`);
    expect(anon.status).toBe(200);
    expect(anon.body.note).toBeNull();
    expect((await client().get(`/cards/${randomUUID()}`)).status).toBe(404);
    expect((await client().get("/cards/not-a-uuid")).status).toBe(422);
  });

  test("liked and saved, in each order, filtered by topic, with seen and the topic's label", async () => {
    const { c, userId, topic, beginners, intermediates } = await corpus();
    const [b0, b1] = beginners as [(typeof beginners)[0], (typeof beginners)[0]];
    const i0 = intermediates[0] as (typeof intermediates)[0];
    const { topic: other, cards: otherCards } = await makeTopic();
    const o0 = otherCards[0] as (typeof otherCards)[0];

    for (const k of [b1, i0, b0, o0]) await engage(userId, [k.id], "like");
    await engage(userId, [b0.id], "explicit_complete");
    await engage(userId, [i0.id], "bookmark");

    const recent = await c.get("/cards/liked");
    expect(recent.status).toBe(200);
    expect(recent.body.map((x: { card: { id: string } }) => x.card.id)).toEqual([o0.id, b0.id, i0.id, b1.id]);
    expect(recent.body[1]).toMatchObject({ topic_name: "Testing", card: { seen: true } });
    // Not followed, so the canonical name.
    expect(recent.body[0].topic_name).toBe(other.canonicalName);
    expect(recent.body[0].liked_at).toEqual(expect.any(String));

    const oldest = await c.get("/cards/liked?sort=oldest");
    expect(oldest.body.map((x: { card: { id: string } }) => x.card.id)).toEqual([b1.id, i0.id, b0.id, o0.id]);
    const byDifficulty = await c.get(`/cards/liked?sort=difficulty&topic_id=${topic.id}`);
    expect(byDifficulty.body.map((x: { card: { id: string } }) => x.card.id)).toEqual([b0.id, b1.id, i0.id]);

    const saved = await c.get("/cards/saved");
    expect(saved.body).toEqual([
      expect.objectContaining({ card: expect.objectContaining({ id: i0.id }), saved_at: expect.any(String) }),
    ]);
    expect((await c.get("/cards/liked?sort=sideways")).status).toBe(422);
  });
});
