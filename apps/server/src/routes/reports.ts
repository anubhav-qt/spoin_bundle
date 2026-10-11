import { createRoute } from "@hono/zod-openapi";
import { CardReportIn } from "@spoin/shared";
import type { Deps } from "../context.ts";
import { needUser } from "../lib/http.ts";
import { body, errors, ids, router } from "../lib/openapi.ts";
import { reportCard } from "../moderation/service.ts";

/** A reader flags a card as broken (ADR-0076). A database write; no model, no job. */
export function reportsRoutes(deps: Deps) {
  const { db } = deps;
  return router().openapi(
    createRoute({
      method: "post",
      path: "/cards/{card_id}/report",
      tags: ["reports"],
      summary: "Flag a live card; a repeat from the same reader updates their report",
      request: { params: ids("card_id"), ...body(CardReportIn) },
      responses: { 204: { description: "Reported" }, 401: errors[401], 404: errors[404], 422: errors[422] },
    }),
    async (c) => {
      const { reason, note } = c.req.valid("json");
      await reportCard(db, needUser(c).id, c.req.valid("param").card_id, reason, note ?? null);
      return c.body(null, 204);
    },
  );
}
