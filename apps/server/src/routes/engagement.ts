import { createRoute } from "@hono/zod-openapi";
import { EngagementAck, EngagementBatchIn } from "@spoin/shared";
import type { Deps } from "../context.ts";
import { ingest } from "../engagement/service.ts";
import { needUser } from "../lib/http.ts";
import { body, errors, json, router } from "../lib/openapi.ts";

/** Engagement ingest. */
export function engagementRoutes(deps: Deps) {
  const { db, env } = deps;
  return router().openapi(
    createRoute({
      method: "post",
      path: "/engagement/events",
      tags: ["engagement"],
      // 202: eventually consistent by design; the client must not read its own writes back for anything that matters.
      summary: "A buffered batch from the client, deduplicated on each event's own id",
      request: body(EngagementBatchIn),
      responses: { 202: json(EngagementAck, "Accepted"), 401: errors[401], 422: errors[422] },
    }),
    async (c) => c.json(await ingest(db, env, needUser(c).id, c.req.valid("json").events), 202),
  );
}
