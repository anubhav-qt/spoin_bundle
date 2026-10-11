import { createRoute, z } from "@hono/zod-openapi";
import { CardOut, CollectionSort, FeedOut, LikedCardOut, SavedCardOut } from "@spoin/shared";
import { collection, getCard, hydrate } from "../cards/service.ts";
import type { Deps } from "../context.ts";
import { page } from "../feed/service.ts";
import { needUser } from "../lib/http.ts";
import { errors, ids, json, router } from "../lib/openapi.ts";

/** The feed and card retrieval. No model call may appear in here or anything it reaches (hard rule 1). */
export function feedRoutes(deps: Deps) {
  const { db, env } = deps;
  const Collection = z.object({ topic_id: z.uuid().optional(), sort: CollectionSort.default("recent") });

  return (
    router()
      .openapi(
        createRoute({
          method: "get",
          path: "/feed",
          tags: ["feed"],
          request: {
            query: z.object({
              // Repeated (`?topics=a&topics=b`), so one value arrives as a string and several as a list.
              topics: z.union([z.uuid(), z.array(z.uuid())]).optional(),
              position: z.coerce.number().int().min(0).optional(),
            }),
          },
          responses: { 200: json(FeedOut), 401: errors[401], 422: errors[422] },
        }),
        async (c) => {
          const userId = needUser(c).id;
          const q = c.req.valid("query");
          const topicFilter = q.topics === undefined ? undefined : [q.topics].flat();
          const p = await page(db, env, userId, { topicFilter, position: q.position });
          // Starved strata would enqueue coalesced fill jobs here (ADR-0006, keyed per
          // subtopic by ADR-0007); that waits for the job queue the tadpoles drain.
          return c.json(
            {
              cards: await hydrate(db, userId, p.cardIds),
              next_position: p.nextPosition,
              degraded: p.degraded,
              exhausted: p.exhausted,
              recycling: p.recycling,
            },
            200,
          );
        },
      )
      // The collections before `/cards/{card_id}`, which would otherwise take their paths.
      .openapi(
        createRoute({
          method: "get",
          path: "/cards/liked",
          tags: ["feed"],
          summary: "Every card this reader has liked",
          request: { query: Collection },
          responses: { 200: json(z.array(LikedCardOut)), 401: errors[401], 422: errors[422] },
        }),
        async (c) => {
          const q = c.req.valid("query");
          const rows = await collection(db, needUser(c).id, "liked", { topicId: q.topic_id, sort: q.sort });
          return c.json(
            rows.map(({ at, ...r }) => ({ ...r, liked_at: at })),
            200,
          );
        },
      )
      .openapi(
        createRoute({
          method: "get",
          path: "/cards/saved",
          tags: ["feed"],
          summary: "Every card this reader has bookmarked",
          request: { query: Collection },
          responses: { 200: json(z.array(SavedCardOut)), 401: errors[401], 422: errors[422] },
        }),
        async (c) => {
          const q = c.req.valid("query");
          const rows = await collection(db, needUser(c).id, "saved", { topicId: q.topic_id, sort: q.sort });
          return c.json(
            rows.map(({ at, ...r }) => ({ ...r, saved_at: at })),
            200,
          );
        },
      )
      .openapi(
        createRoute({
          method: "get",
          path: "/cards/{card_id}",
          tags: ["feed"],
          summary: "One card, for direct links and shares; no session needed",
          request: { params: ids("card_id") },
          responses: { 200: json(CardOut), 404: errors[404], 422: errors[422] },
        }),
        async (c) => c.json(await getCard(db, c.req.valid("param").card_id, c.var.caller?.id ?? null), 200),
      )
  );
}
