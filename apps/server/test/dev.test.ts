import { eq } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import { makeApp } from "../src/app.ts";
import { feedPlan, topic, userCardState, userTopicProgress } from "../src/db/schema.ts";
import { makeTopic, markSeen } from "./fixtures.ts";
import { deps, env, signedUp, userIdOf } from "./helpers.ts";

const { db } = deps;

describe("/dev/reset", () => {
  test("clears what was seen, locks every tier, and sends two followed topics back to Discover", async () => {
    const c = await signedUp();
    const userId = await userIdOf(c);
    const made = await Promise.all([makeTopic(), makeTopic(), makeTopic()]);
    for (const m of made)
      expect((await c.post(`/topics/${m.topic.id}/subscribe?entry_difficulty=advanced`)).status).toBe(201);
    const [first] = made;
    await markSeen(userId, first?.cards[0] as (typeof first & object)["cards"][number]);
    expect((await c.get("/feed")).status).toBe(200);
    await db
      .update(userTopicProgress)
      .set({ tierQuizPassed: [true, true, false], masteredAt: new Date() })
      .where(eq(userTopicProgress.userId, userId));

    const r = await c.post("/dev/reset");
    expect(r.status).toBe(200);
    expect(r.body).toHaveLength(1);
    expect(r.body[0].current_difficulty).toBe("beginner");

    expect(await db.select().from(userCardState).where(eq(userCardState.userId, userId))).toEqual([]);
    expect(await db.select().from(feedPlan).where(eq(feedPlan.userId, userId))).toEqual([]);
    const progress = await db.select().from(userTopicProgress).where(eq(userTopicProgress.userId, userId));
    expect(progress).toHaveLength(1);
    expect(progress[0]).toMatchObject({
      currentDifficulty: "beginner",
      tierUnlocked: [false, false, false],
      tierQuizPassed: [false, false, false],
      masteredAt: null,
    });
    // Unfollowing went through the same path as the button, so the counts stay true.
    const counts = await Promise.all(
      made.map(
        async (m) => (await db.select().from(topic).where(eq(topic.id, m.topic.id)))[0]?.subscriberCount,
      ),
    );
    expect(counts.sort()).toEqual([0, 0, 1]);
  });

  test("is not there in production, nor without the flag", async () => {
    for (const over of [{ NODE_ENV: "production" as const, DEV_ROUTES: true }, { DEV_ROUTES: false }]) {
      const res = await makeApp({ ...deps, env: { ...env, ...over } }).request("/dev/reset", {
        method: "POST",
      });
      expect(res.status).toBe(404);
    }
    // Mounted, an anonymous call is refused rather than not found.
    expect((await makeApp(deps).request("/dev/reset", { method: "POST" })).status).toBe(401);
  });
});
