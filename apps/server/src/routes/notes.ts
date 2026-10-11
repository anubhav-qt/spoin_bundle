import { createRoute, z } from "@hono/zod-openapi";
import { NoteIn, NoteOut, NoteWithCardOut } from "@spoin/shared";
import type { Deps } from "../context.ts";
import { needUser } from "../lib/http.ts";
import { body, errors, ids, json, router } from "../lib/openapi.ts";
import { deleteNote, listNotes, upsertNote } from "../notes/service.ts";

/** Private note-taking on a card. */
export function notesRoutes(deps: Deps) {
  const { db } = deps;
  return router()
    .openapi(
      createRoute({
        method: "put",
        path: "/cards/{card_id}/note",
        tags: ["notes"],
        request: { params: ids("card_id"), ...body(NoteIn) },
        responses: { 200: json(NoteOut), 401: errors[401], 404: errors[404], 422: errors[422] },
      }),
      async (c) => {
        const { card_id } = c.req.valid("param");
        return c.json(await upsertNote(db, needUser(c).id, card_id, c.req.valid("json").body), 200);
      },
    )
    .openapi(
      createRoute({
        method: "delete",
        path: "/cards/{card_id}/note",
        tags: ["notes"],
        request: { params: ids("card_id") },
        responses: { 204: { description: "Deleted, or there was none" }, 401: errors[401], 422: errors[422] },
      }),
      async (c) => {
        await deleteNote(db, needUser(c).id, c.req.valid("param").card_id);
        return c.body(null, 204);
      },
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/notes",
        tags: ["notes"],
        summary: "Every note, newest edit first, with its card",
        responses: { 200: json(z.array(NoteWithCardOut)), 401: errors[401] },
      }),
      async (c) => c.json(await listNotes(db, needUser(c).id), 200),
    );
}
