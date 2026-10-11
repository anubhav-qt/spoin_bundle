import { normalizeTopicText } from "@spoin/frog/normalize";
import { eq } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import { generationJob, topic, topicAlias } from "../src/db/schema.ts";
import { makeTopic } from "./fixtures.ts";
import { deps, guest, signedUp } from "./helpers.ts";

const { db } = deps;
const unique = () => Math.random().toString(36).slice(2, 8);

const jobsFor = (topicId: string) =>
  db.select().from(generationJob).where(eq(generationJob.topicId, topicId));

/** An authored topic, reachable by name the way the curriculum projection leaves it. */
async function authored(name: string) {
  const made = await makeTopic({ name });
  await db.insert(topicAlias).values({
    normalizedText: normalizeTopicText(name),
    rawText: name,
    topicId: made.topic.id,
    decidedBy: "projection",
  });
  return made;
}

describe("asking for a topic by name", () => {
  test("a new name is queued for toad_sage: a pending topic, a custom subscription, one job", async () => {
    const c = await signedUp();
    const name = `Tidepool Ecology ${unique()}`;
    const r = await c.post("/topics", {
      name: `  ${name} `,
      description: "rock pools",
      entry_difficulty: "intermediate",
    });
    expect(r.status).toBe(201);
    expect(r.body).toMatchObject({
      status: "generating",
      topic: { display_name: name, is_custom: true, current_difficulty: "intermediate" },
    });

    const [t] = await db.select().from(topic).where(eq(topic.id, r.body.topic.id));
    expect(t).toMatchObject({ canonicalName: name, description: "rock pools", subscriberCount: 1 });
    const jobs = await jobsFor(r.body.topic.id);
    expect(jobs).toEqual([
      expect.objectContaining({
        kind: "generate",
        status: "pending",
        priority: 10,
        progress: { topic_name: name },
      }),
    ]);
    expect((await c.get("/topics/custom")).body[0]).toMatchObject({
      topic_id: t?.id,
      generation_status: "pending",
    });

    // Nothing to read yet, so nobody else sees it.
    const other = await signedUp();
    const all = (await other.get("/topics/all")).body.map((x: { topic_id: string }) => x.topic_id);
    expect(all).not.toContain(t?.id);
  });

  test("the same name from someone else joins the same topic, with their own label and no second job", async () => {
    const name = `Glass Sponges ${unique()}`;
    const first = await (await signedUp()).post("/topics", { name });
    const second = await (await signedUp()).post("/topics", { name: `${name.toUpperCase()}!` });
    expect(second.status).toBe(201);
    expect(second.body).toMatchObject({
      status: "subscribed",
      topic: { id: first.body.topic.id, display_name: `${name.toUpperCase()}!` },
    });
    expect(await jobsFor(first.body.topic.id)).toHaveLength(1);
  });

  test("an exact match on an authored topic subscribes at once", async () => {
    const tag = unique();
    const { topic: t } = await authored(`stellar nurseries ${tag}`);
    const r = await (await signedUp()).post("/topics", { name: `Stellar  Nurseries ${tag}` });
    expect(r.body).toMatchObject({ status: "subscribed", topic: { id: t.id } });
    expect(await jobsFor(t.id)).toEqual([]);
  });

  test("asking twice is a conflict", async () => {
    const c = await signedUp();
    const name = `Bog Bodies ${unique()}`;
    await c.post("/topics", { name });
    const again = await c.post("/topics", { name });
    expect(again.status).toBe(409);
    expect(again.body.detail).toBe("Already subscribed");
  });

  test("the name rules are code's: blank and too long are refused before anything is written", async () => {
    const c = await signedUp();
    const blank = await c.post("/topics", { name: "   " });
    expect(blank.status).toBe(422);
    expect(blank.body.detail).toBe("Topic name is required");
    const long = await c.post("/topics", { name: "one two three four five six" });
    expect(long.status).toBe(422);
    expect(long.body.detail).toBe("Keep it short: 5 words or fewer");
    expect((await c.get("/topics/custom")).body).toEqual([]);
  });

  test("a guest is asked to sign up", async () => {
    const g = await guest();
    const r = await g.post("/topics", { name: "Anything" });
    expect(r.status).toBe(403);
    expect(r.body.detail).toBe("Sign up to request a custom topic");
    expect((await g.post("/topics/batch", { items: [{ name: "Anything" }] })).status).toBe(403);
  });

  test("a slug taken by a different name gets a suffix rather than a merge", async () => {
    const tag = unique();
    const { topic: taken } = await makeTopic({ name: `Rust Lang ${tag}` });
    const r = await (await signedUp()).post("/topics", { name: `Rust-Lang ${tag}` });
    expect(r.body.status).toBe("generating");
    expect(r.body.topic.id).not.toBe(taken.id);
    expect(r.body.topic.slug).toMatch(new RegExp(`^rust-lang-${tag}-[0-9a-f]{6}$`));
  });

  test("two people asking for the same new name at once end up on one topic", async () => {
    const name = `Hydrothermal Vents ${unique()}`;
    const [a, b] = await Promise.all([signedUp(), signedUp()]);
    const [ra, rb] = await Promise.all([a.post("/topics", { name }), b.post("/topics", { name })]);
    expect([ra.status, rb.status]).toEqual([201, 201]);
    expect(ra.body.topic.id).toBe(rb.body.topic.id);
    expect([ra.body.status, rb.body.status].sort()).toEqual(["generating", "subscribed"]);
    expect(await db.select().from(topic).where(eq(topic.canonicalName, name))).toHaveLength(1);
    expect(await jobsFor(ra.body.topic.id)).toHaveLength(1);
  });
});

describe("asking for several at once (task 0032)", () => {
  test("each row reports its own outcome", async () => {
    const c = await signedUp();
    const tag = unique();
    const { topic: known } = await authored(`known ${tag}`);
    const r = await c.post("/topics/batch", {
      items: [
        { name: `Fresh One ${tag}` },
        { name: "far too many words in this one" },
        { name: `fresh one ${tag}` },
        { name: `Known ${tag}`, entry_difficulty: "advanced" },
      ],
    });
    expect(r.status).toBe(201);
    expect(r.body.results.map((x: { status: string }) => x.status)).toEqual([
      "generating",
      "rejected",
      "already_subscribed",
      "subscribed",
    ]);
    expect(r.body.results[1].detail).toBe("Keep it short: 5 words or fewer");
    expect(r.body.results[3].topic).toMatchObject({ id: known.id, current_difficulty: "advanced" });
    expect(await jobsFor(r.body.results[0].topic.id)).toHaveLength(1);
  });

  test("an empty batch is a 422", async () => {
    expect((await (await signedUp()).post("/topics/batch", { items: [] })).status).toBe(422);
  });
});
