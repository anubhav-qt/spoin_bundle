import { createRoute } from "@hono/zod-openapi";
import { AskConversationOut, AskEventOut, AskIn } from "@spoin/shared";
import { streamSSE } from "hono/streaming";
import { answer, askedTopic, conversation, reset } from "../ask/service.ts";
import type { Deps } from "../context.ts";
import { HttpError } from "../lib/errors.ts";
import { needUser } from "../lib/http.ts";
import { body, errors, ids, json, router } from "../lib/openapi.ts";
import { log } from "../log.ts";

/**
 * AskAI (ADR-0077, amended by ADR-0106). The turn is the codebase's one streaming
 * endpoint: anything that needs a status (signed out, unknown topic, empty question)
 * is answered before the stream opens, and everything after is an event.
 */
export function askRoutes(deps: Deps) {
  const { db } = deps;
  const TopicId = ids("topic_id");

  return router()
    .openapi(
      createRoute({
        method: "get",
        path: "/topics/{topic_id}/ask",
        tags: ["ask"],
        summary: "The active thread on this topic (no messages before the first turn) and today's count",
        request: { params: TopicId },
        responses: { 200: json(AskConversationOut), 401: errors[401], 422: errors[422] },
      }),
      async (c) => c.json(await conversation(deps, needUser(c).id, c.req.valid("param").topic_id), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/topics/{topic_id}/ask",
        tags: ["ask"],
        summary: "One turn, streamed as server-sent events: delta, then done; or off_topic, limit or error",
        request: { params: TopicId, ...body(AskIn) },
        responses: {
          200: {
            description: "`event:` names each event and `data:` is the rest of it as JSON",
            content: { "text/event-stream": { schema: AskEventOut } },
          },
          401: errors[401],
          404: errors[404],
          422: errors[422],
        },
      }),
      async (c) => {
        const userId = needUser(c).id;
        const { question, card_id } = c.req.valid("json");
        if (!question.trim()) throw new HttpError(422, "Empty question");
        const t = await askedTopic(db, c.req.valid("param").topic_id);
        const requestId = c.var.requestId;
        const res = streamSSE(c, async (stream) => {
          try {
            for await (const { event, ...data } of answer(deps, userId, t, question, card_id)) {
              await stream.writeSSE({ event, data: JSON.stringify(data) });
            }
          } catch (err) {
            log.error({ err, requestId }, "ask stream failed");
            await stream.writeSSE({ event: "error", data: JSON.stringify({ cause: "internal" }) });
          }
        });
        // Never cached, and never buffered by a proxy: the point is to see it arrive.
        c.header("Cache-Control", "no-store");
        c.header("X-Accel-Buffering", "no");
        return res;
      },
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/topics/{topic_id}/ask/reset",
        tags: ["ask"],
        summary: "Start over: archive the active thread, so the next turn opens a fresh one",
        request: { params: TopicId },
        responses: {
          204: { description: "Archived, or there was none" },
          401: errors[401],
          422: errors[422],
        },
      }),
      async (c) => {
        await reset(db, needUser(c).id, c.req.valid("param").topic_id);
        return c.body(null, 204);
      },
    );
}
