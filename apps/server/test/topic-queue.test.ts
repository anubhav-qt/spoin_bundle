import { normalizeTopicText } from "@spoin/frog/normalize";
import { eq } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import { feedPlan, generationJob, jobRuns, topic, topicAlias, userTopic } from "../src/db/schema.ts";
import { reprioritize, type Waiting } from "../src/jobs/order.ts";
import { makeTopic } from "./fixtures.ts";
import { admin, client, deps, signedUp, userIdOf } from "./helpers.ts";

/*
 * The topic queue and job status pages (task 0045, Phase 7). Other test files leave
 * jobs in the queue, so these assert on the order of their own jobs, never on the
 * whole queue.
 */

const { db } = deps;
const unique = () => Math.random().toString(36).slice(2, 8);
type Row = { job_id: string; name: string; status: string; priority: number; requesters: number };

/** Claim order, as the server sorts: priority desc, then the queue's own order for ties. */
function claimOrder(queue: Waiting[], changed: Map<string, number>) {
  const rank = new Map(queue.map((j, i) => [j.id, i]));
  const p = (j: Waiting) => changed.get(j.id) ?? j.priority;
  return [...queue]
    .sort((a, b) => p(b) - p(a) || (rank.get(a.id) as number) - (rank.get(b.id) as number))
    .map((j) => j.id);
}

/** The order the move asked for. */
function wanted(queue: Waiting[], moved: string, before: string | null) {
  if (before === moved) return queue.map((j) => j.id);
  const rest = queue.map((j) => j.id).filter((id) => id !== moved);
  rest.splice(before === null ? rest.length : rest.indexOf(before), 0, moved);
  return rest;
}

describe("reprioritize", () => {
  const q = (...ps: number[]): Waiting[] => ps.map((priority, i) => ({ id: `j${i}`, priority }));

  test("a move that already fits changes nothing", () => {
    expect(reprioritize(q(10, 10, 0), "j1", "j2").size).toBe(0);
    expect(reprioritize(q(10, 10, 0), "j2", null).size).toBe(0);
    expect(reprioritize(q(10, 0), "j0", "j0").size).toBe(0);
  });

  test("to the top takes one more than the old top", () => {
    expect([...reprioritize(q(10, 10, 0), "j2", "j0")]).toEqual([["j2", 11]]);
  });

  test("between two ties lifts the tie above, together", () => {
    // j0 j1 j2 all at 10; j3 (0) dropped between j1 and j2 runs at 11, and so do j0 and j1,
    // which stay ahead of it by age.
    const changed = reprioritize(q(10, 10, 10, 0), "j3", "j2");
    expect(Object.fromEntries(changed)).toEqual({ j0: 11, j1: 11, j3: 11 });
  });

  test("down past a lower tier joins it", () => {
    // j0 (10) dropped between j1 (0) and j2 (0): it takes 0, older than j2, and j1 is lifted.
    expect(Object.fromEntries(reprioritize(q(10, 0, 0), "j0", "j2"))).toEqual({ j0: 0, j1: 1 });
  });

  test("last goes below the old last when it is older", () => {
    expect(Object.fromEntries(reprioritize(q(5, 5), "j0", null))).toEqual({ j0: 4 });
  });

  test("every move on every small queue lands exactly where it was dropped", () => {
    let seed = 7;
    const rand = (n: number) => {
      seed = (seed * 1103515245 + 12345) % 2 ** 31;
      return seed % n;
    };
    for (let trial = 0; trial < 3000; trial++) {
      const size = 1 + rand(7);
      const priorities = Array.from({ length: size }, () => [10, 10, 5, 1, 0, 0, -10][rand(7)] as number);
      priorities.sort((a, b) => b - a);
      const queue = q(...priorities);
      const moved = `j${rand(size)}`;
      const target = rand(size + 1);
      const before = target === size ? null : `j${target}`;
      const changed = reprioritize(queue, moved, before);
      expect(claimOrder(queue, changed), JSON.stringify({ priorities, moved, before })).toEqual(
        wanted(queue, moved, before),
      );
      // Nothing below the drop point changes.
      const order = wanted(queue, moved, before);
      for (const id of order.slice(order.indexOf(moved) + 1)) expect(changed.has(id)).toBe(false);
    }
  });
});

describe("the topic queue", () => {
  const mine = (rows: Row[], ...ids: string[]) =>
    rows.filter((r) => ids.includes(r.job_id)).map((r) => r.job_id);

  async function add(a: Awaited<ReturnType<typeof admin>>, name = `Queued ${unique()}`) {
    const r = await a.post("/admin/queue", { name });
    expect(r.status).toBe(200);
    const row = (r.body as Row[]).find((x) => x.name === name);
    if (!row) throw new Error(`${name} not in the queue`);
    return row;
  }

  test("is the owner's alone", async () => {
    expect((await client().get("/admin/queue")).status).toBe(401);
    const reader = await signedUp();
    expect((await reader.get("/admin/queue")).status).toBe(403);
    expect((await reader.post("/admin/queue", { name: "Anything" })).status).toBe(403);
    expect((await reader.get("/admin/jobs")).status).toBe(403);
  });

  test("adds a topic by name at priority 0, with an alias and no subscription", async () => {
    const a = await admin();
    const name = `Glacier Physics ${unique()}`;
    const row = await add(a, name);
    expect(row).toMatchObject({ status: "pending", priority: 0, requesters: 0 });

    const [alias] = await db
      .select()
      .from(topicAlias)
      .where(eq(topicAlias.normalizedText, normalizeTopicText(name)));
    expect(alias?.decidedBy).toBe("admin");
    const subs = await db
      .select()
      .from(userTopic)
      .where(eq(userTopic.userId, await userIdOf(a)));
    expect(subs).toHaveLength(0);
  });

  test("refuses a name that is already a topic, and one that is too long", async () => {
    const a = await admin();
    const name = `Salt Marshes ${unique()}`;
    await add(a, name);
    const again = await a.post("/admin/queue", { name: `  ${name.toUpperCase()} ` });
    expect(again.status).toBe(409);
    expect(again.body.detail).toBe(`Already a topic: ${name}`);

    const long = await a.post("/admin/queue", {
      name: "one two three four five six seven eight nine ten eleven",
    });
    expect(long.status).toBe(422);
  });

  test("lists readers' requests ahead of the owner's, with their requesters", async () => {
    const a = await admin();
    const ours = await add(a);
    const reader = await signedUp();
    const name = `Kelp Forests ${unique()}`;
    expect((await reader.post("/topics", { name })).status).toBe(201);

    const rows = (await a.get("/admin/queue")).body as Row[];
    const theirs = rows.find((r) => r.name === name);
    expect(theirs).toMatchObject({ priority: 10, requesters: 1, status: "pending" });
    expect(mine(rows, ours.job_id, theirs?.job_id as string)).toEqual([theirs?.job_id, ours.job_id]);
  });

  test("moves a waiting topic to the top, between two, and last", async () => {
    const a = await admin();
    const x = await add(a);
    const y = await add(a);
    const z = await add(a);

    let rows = (await a.post(`/admin/queue/${z.job_id}/move`, { before_job_id: null })).body as Row[];
    const waiting = () => rows.filter((r) => r.status === "pending").map((r) => r.job_id);
    expect(mine(rows, x.job_id, y.job_id, z.job_id)).toEqual([x.job_id, y.job_id, z.job_id]);

    const top = waiting()[0] as string;
    rows = (await a.post(`/admin/queue/${z.job_id}/move`, { before_job_id: top })).body as Row[];
    expect(waiting()[0]).toBe(z.job_id);

    rows = (await a.post(`/admin/queue/${x.job_id}/move`, { before_job_id: null })).body as Row[];
    expect(waiting().at(-1)).toBe(x.job_id);
    expect(mine(rows, x.job_id, y.job_id, z.job_id)).toEqual([z.job_id, y.job_id, x.job_id]);

    rows = (await a.post(`/admin/queue/${x.job_id}/move`, { before_job_id: y.job_id })).body as Row[];
    expect(mine(rows, x.job_id, y.job_id, z.job_id)).toEqual([z.job_id, x.job_id, y.job_id]);
  });

  test("moves only waiting jobs", async () => {
    const a = await admin();
    const x = await add(a);
    const y = await add(a);
    await db.update(generationJob).set({ status: "running" }).where(eq(generationJob.id, y.job_id));

    const running = await a.post(`/admin/queue/${y.job_id}/move`, { before_job_id: null });
    expect(running.status).toBe(409);
    expect(running.body.detail).toBe("Only a waiting job can move; this one is running");
    const ontoRunning = await a.post(`/admin/queue/${x.job_id}/move`, { before_job_id: y.job_id });
    expect(ontoRunning.status).toBe(409);
    const missing = await a.post(`/admin/queue/${crypto.randomUUID()}/move`, { before_job_id: null });
    expect(missing.status).toBe(404);

    const rows = (await a.get("/admin/queue")).body as Row[];
    expect(rows.findIndex((r) => r.job_id === y.job_id)).toBeLessThan(
      rows.findIndex((r) => r.status === "pending"),
    );
  });

  test("retries a failed job, keeping its priority and error", async () => {
    const a = await admin();
    const x = await add(a);
    await db
      .update(generationJob)
      .set({ status: "failed", lastError: "Not a topic: too vague", attempts: 1 })
      .where(eq(generationJob.id, x.job_id));

    let rows = (await a.get("/admin/queue")).body as Row[];
    expect(rows.find((row) => row.job_id === x.job_id)).toMatchObject({ status: "failed" });
    expect(rows.findIndex((row) => row.job_id === x.job_id)).toBeGreaterThan(
      rows.findLastIndex((row) => row.status === "pending"),
    );

    const r = await a.post(`/admin/queue/${x.job_id}/retry`);
    expect(r.status).toBe(200);
    rows = r.body as Row[];
    expect(rows.find((row) => row.job_id === x.job_id)).toMatchObject({
      status: "pending",
      priority: 0,
      last_error: "Not a topic: too vague",
    });
    expect((await a.post(`/admin/queue/${x.job_id}/retry`)).status).toBe(409);
  });

  test("cancels a waiting topic with its alias, job and requesters' subscriptions", async () => {
    const a = await admin();
    const reader = await signedUp();
    const name = `Coral Spawning ${unique()}`;
    const req = await reader.post("/topics", { name });
    const topicId = req.body.topic.id as string;
    await db.insert(feedPlan).values({ userId: await userIdOf(reader), topicOrder: [topicId] });
    const job = ((await a.get("/admin/queue")).body as Row[]).find((r) => r.name === name) as Row;

    const r = await a.post(`/admin/queue/${job.job_id}/cancel`);
    expect(r.status).toBe(200);
    expect((r.body as Row[]).some((row) => row.job_id === job.job_id)).toBe(false);
    expect(await db.select().from(topic).where(eq(topic.id, topicId))).toHaveLength(0);
    expect(await db.select().from(topicAlias).where(eq(topicAlias.topicId, topicId))).toHaveLength(0);
    expect(
      await db
        .select()
        .from(feedPlan)
        .where(eq(feedPlan.userId, await userIdOf(reader))),
    ).toHaveLength(0);
    expect((await reader.get("/topics/custom")).body).toEqual([]);

    // The name is free again.
    expect((await a.post("/admin/queue", { name })).status).toBe(200);
  });

  test("won't cancel a topic being written or one with content", async () => {
    const a = await admin();
    const x = await add(a);
    await db.update(generationJob).set({ status: "running" }).where(eq(generationJob.id, x.job_id));
    expect((await a.post(`/admin/queue/${x.job_id}/cancel`)).status).toBe(409);

    const made = await makeTopic();
    const [job] = await db
      .insert(generationJob)
      .values({ topicId: made.topic.id, kind: "generate", status: "failed" })
      .returning();
    const r = await a.post(`/admin/queue/${job?.id}/cancel`);
    expect(r.status).toBe(409);
    expect(r.body.detail).toBe("This topic already has content, so it can't be cancelled");
  });
});

describe("job status", () => {
  test("shows each job's last run, the queues by status, and every failed job", async () => {
    const a = await admin();
    const name = `status-check-${unique()}`;
    await db
      .insert(jobRuns)
      .values({ name, lastOkAt: new Date(), lastError: "boom", lastErrorAt: new Date() });
    const made = await makeTopic();
    const [failed] = await db
      .insert(generationJob)
      .values({
        topicId: made.topic.id,
        kind: "repair",
        cardId: made.cards[0]?.id,
        status: "failed",
        lastError: "no model",
      })
      .returning();

    const r = await a.get("/admin/jobs");
    expect(r.status).toBe(200);
    expect(r.body.runs.find((run: { name: string }) => run.name === name)).toMatchObject({
      last_error: "boom",
    });
    expect(r.body.queues.map((q: { kind: string }) => q.kind)).toEqual(["generate", "repair"]);
    expect(r.body.queues[1].failed).toBeGreaterThanOrEqual(1);
    expect(r.body.failed.find((f: { job_id: string }) => f.job_id === failed?.id)).toMatchObject({
      kind: "repair",
      topic_name: made.topic.canonicalName,
      card_id: made.cards[0]?.id,
      last_error: "no model",
    });
  });
});
