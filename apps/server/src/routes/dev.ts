import { createRoute, z } from "@hono/zod-openapi";
import { TopicOut } from "@spoin/shared";
import { eq } from "drizzle-orm";
import type { Deps } from "../context.ts";
import { feedPlan, feedSlate, userCardState, userTopic, userTopicProgress } from "../db/schema.ts";
import { shuffle } from "../feed/ranking.ts";
import { needUser } from "../lib/http.ts";
import { errors, json, router } from "../lib/openapi.ts";
import { listSubscribed, unsubscribe } from "../topics/service.ts";

/** How many followed topics go back to Discover on each reset. */
const UNFOLLOW_COUNT = 2;

const NONE = [false, false, false];

/**
 * Conveniences for exercising a demo account, mounted only outside production and only
 * with `DEV_ROUTES` (app.ts). Each acts on the caller's own state.
 */
export function devRoutes(deps: Deps) {
  const { db } = deps;
  return router().openapi(
    createRoute({
      method: "post",
      path: "/dev/reset",
      tags: ["dev"],
      summary: "Fresh-demo state for the caller: nothing seen, every tier locked, two topics unfollowed",
      responses: { 200: json(z.array(TopicOut)), 401: errors[401] },
    }),
    async (c) => {
      const userId = needUser(c).id;
      await db.transaction(async (tx) => {
        await tx.delete(userCardState).where(eq(userCardState.userId, userId));
        // The feed's cursor too, so it stops reporting "exhausted" from an earlier session.
        await tx.delete(feedSlate).where(eq(feedSlate.userId, userId));
        await tx.delete(feedPlan).where(eq(feedPlan.userId, userId));
        await tx
          .update(userTopicProgress)
          .set({
            currentDifficulty: "beginner",
            tierUnlocked: NONE,
            tierContentComplete: NONE,
            tierQuizPassed: NONE,
            masteredAt: null,
            revisitMode: false,
          })
          .where(eq(userTopicProgress.userId, userId));
      });
      // A few go back to Discover rather than staying followed for good.
      const followed = await db
        .select({ id: userTopic.topicId })
        .from(userTopic)
        .where(eq(userTopic.userId, userId));
      for (const { id } of shuffle(followed).slice(0, UNFOLLOW_COUNT)) await unsubscribe(db, userId, id);
      return c.json(await listSubscribed(db, userId), 200);
    },
  );
}
