import { createRoute, z } from "@hono/zod-openapi";
import {
  AsciiSceneActionOut,
  AsciiSceneKeepIn,
  AsciiSceneOut,
  AsciiSceneRejectIn,
  JobStatusOut,
  QueuedTopicOut,
  RepairEnqueuedOut,
  RepairQueueItemOut,
  TopicQueueAddIn,
  TopicQueueMoveIn,
} from "@spoin/shared";
import type { Deps } from "../context.ts";
import { jobStatus } from "../jobs/status.ts";
import { addTopic, cancelTopic, listQueue, moveJob, retryJob } from "../jobs/topic-queue.ts";
import { HttpError } from "../lib/errors.ts";
import { needAdmin } from "../lib/http.ts";
import { body, errors, ids, json, multipart, router } from "../lib/openapi.ts";
import { keep, listScenes, sendToRepairs } from "../moderation/ascii-review.ts";
import * as moderation from "../moderation/service.ts";
import { AVATAR_MAX_BYTES, sniffImage, uploadLimit } from "../profile/uploads.ts";

/*
 * The operator's pages: the repair queue (ADR-0076), ASCII scene review (ADR-0104), the
 * topic queue and job status (task 0045). Behind the admin role (ADR-0106), which closes
 * task 0035: these retire cards, edit live content and queue model work.
 *
 * The card is rendered to a PNG by the admin page, with the same call the share button
 * uses, and uploaded here; nothing on the server renders.
 */

const IMAGE_MAX_BYTES = AVATAR_MAX_BYTES;
const IMAGE_TOO_LARGE = "Image is too large. Maximum size is 5MB.";
const TEXT_MAX = 4000;

async function imageOf(file: unknown): Promise<Buffer> {
  if (!(file instanceof File)) throw new HttpError(422, "file: a file upload is required");
  if (file.size > IMAGE_MAX_BYTES) throw new HttpError(413, IMAGE_TOO_LARGE);
  const data = Buffer.from(await file.arrayBuffer());
  if (data.length === 0) throw new HttpError(400, "Empty upload");
  if (!sniffImage(data))
    throw new HttpError(400, "Invalid image format. Only JPEG, PNG, and WebP are supported.");
  return data;
}

/** A trimmed form field, null when blank. */
function textOf(form: Record<string, unknown>, name: string): string | null {
  const v = form[name];
  if (v === undefined) return null;
  if (typeof v !== "string") throw new HttpError(422, `${name}: must be text`);
  if (v.length > TEXT_MAX) throw new HttpError(422, `${name}: at most ${TEXT_MAX} characters`);
  return v.trim() || null;
}

const done = {
  200: json(RepairEnqueuedOut),
  401: errors[401],
  403: errors[403],
  404: errors[404],
  422: errors[422],
};

const queued = {
  200: json(z.array(QueuedTopicOut)),
  401: errors[401],
  403: errors[403],
  404: errors[404],
  409: errors[409],
  422: errors[422],
};

export function adminRoutes(deps: Deps) {
  const { db } = deps;
  const CardId = ids("card_id");
  const JobId = ids("job_id");
  const r = router();

  r.use("/admin/*", async (c, next) => {
    needAdmin(c);
    await next();
  });
  for (const path of ["/admin/repairs/:card_id/fix", "/admin/repairs/:card_id/remake"]) {
    r.use(path, uploadLimit(IMAGE_MAX_BYTES, IMAGE_TOO_LARGE));
  }

  return r
    .openapi(
      createRoute({
        method: "get",
        path: "/admin/repairs",
        tags: ["admin"],
        summary: "Cards with open reports, then landed repairs awaiting a look",
        responses: { 200: json(z.array(RepairQueueItemOut)), 401: errors[401], 403: errors[403] },
      }),
      async (c) => c.json(await moderation.listQueue(db), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/repairs/{card_id}/delete",
        tags: ["admin"],
        summary: "Retire the card and resolve its reports",
        request: { params: CardId },
        responses: done,
      }),
      async (c) => c.json(await moderation.deleteCard(db, c.req.valid("param").card_id), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/repairs/{card_id}/dismiss",
        tags: ["admin"],
        summary: "Accept the repair and clear its before/after entry",
        request: { params: CardId },
        responses: done,
      }),
      async (c) => c.json(await moderation.dismiss(db, c.req.valid("param").card_id), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/repairs/{card_id}/revert",
        tags: ["admin"],
        summary: "Undo a landed repair: the original goes back live, the repaired version is superseded",
        request: { params: CardId },
        responses: done,
      }),
      async (c) => c.json(await moderation.revert(db, c.req.valid("param").card_id), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/repairs/{card_id}/fix",
        tags: ["admin"],
        summary: "Repair the structure from the rendered card; with guidance, the prose may change too",
        request: { params: CardId, ...multipart({ guidance: { type: "string", maxLength: TEXT_MAX } }) },
        responses: { ...done, 409: errors[409] },
      }),
      async (c) => {
        const form = await c.req.parseBody();
        const image = await imageOf(form.file);
        return c.json(
          await moderation.enqueueFix(db, c.req.valid("param").card_id, image, textOf(form, "guidance")),
          200,
        );
      },
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/repairs/{card_id}/remake",
        tags: ["admin"],
        summary: "Regenerate the card from scratch to the instructions, through the quality gate",
        request: {
          params: CardId,
          ...multipart({ instructions: { type: "string", minLength: 1, maxLength: TEXT_MAX } }, [
            "instructions",
          ]),
        },
        responses: { ...done, 409: errors[409] },
      }),
      async (c) => {
        const form = await c.req.parseBody();
        const instructions = textOf(form, "instructions");
        if (!instructions) throw new HttpError(422, "instructions: required");
        const image = form.file === undefined ? null : await imageOf(form.file);
        return c.json(
          await moderation.enqueueRemake(db, c.req.valid("param").card_id, instructions, image),
          200,
        );
      },
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/admin/ascii/{topic_slug}",
        tags: ["admin"],
        summary: "A topic's ASCII scenes, oldest first; by slug, because the page is reached by typing a URL",
        request: { params: z.object({ topic_slug: z.string() }) },
        responses: {
          200: json(z.array(AsciiSceneOut)),
          401: errors[401],
          403: errors[403],
          404: errors[404],
        },
      }),
      async (c) => c.json(await listScenes(db, c.req.valid("param").topic_slug), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/ascii/scene/{card_id}/keep",
        tags: ["admin"],
        summary: "Accept the scene, writing the operator's edit to the card",
        request: { params: CardId, ...body(AsciiSceneKeepIn) },
        responses: {
          200: json(AsciiSceneActionOut),
          400: errors[422],
          401: errors[401],
          403: errors[403],
          404: errors[404],
        },
      }),
      async (c) => {
        const { art, alt } = c.req.valid("json");
        return c.json(await keep(db, c.req.valid("param").card_id, art, alt), 200);
      },
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/ascii/scene/{card_id}/reject",
        tags: ["admin"],
        summary: "File an `art` report, so the card lands in the repair queue",
        request: { params: CardId, ...body(AsciiSceneRejectIn) },
        responses: {
          200: json(AsciiSceneActionOut),
          400: errors[422],
          401: errors[401],
          403: errors[403],
          404: errors[404],
        },
      }),
      async (c) =>
        c.json(
          await sendToRepairs(db, c.req.valid("param").card_id, needAdmin(c).id, c.req.valid("json").note),
          200,
        ),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/admin/queue",
        tags: ["admin"],
        summary:
          "Topics not live yet with their generate jobs: running, then waiting in run order, then failed",
        responses: { 200: json(z.array(QueuedTopicOut)), 401: errors[401], 403: errors[403] },
      }),
      async (c) => c.json(await listQueue(db), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/queue",
        tags: ["admin"],
        summary: "Add a topic by name: a reader's request without the subscription, at the owner's priority",
        request: body(TopicQueueAddIn),
        responses: queued,
      }),
      async (c) => {
        const { name, description } = c.req.valid("json");
        return c.json(await addTopic(deps, name.trim(), description?.trim() ?? ""), 200);
      },
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/queue/{job_id}/move",
        tags: ["admin"],
        summary: "Run a waiting job just ahead of another, or last",
        request: { params: JobId, ...body(TopicQueueMoveIn) },
        responses: queued,
      }),
      async (c) =>
        c.json(await moveJob(db, c.req.valid("param").job_id, c.req.valid("json").before_job_id), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/queue/{job_id}/retry",
        tags: ["admin"],
        summary: "Put a failed job back in the queue",
        request: { params: JobId },
        responses: queued,
      }),
      async (c) => c.json(await retryJob(db, c.req.valid("param").job_id), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/admin/queue/{job_id}/cancel",
        tags: ["admin"],
        summary: "Cancel a topic that is not live and not being written, with its requesters' subscriptions",
        request: { params: JobId },
        responses: queued,
      }),
      async (c) => c.json(await cancelTopic(db, c.req.valid("param").job_id), 200),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/admin/jobs",
        tags: ["admin"],
        summary: "Each background job's last run, the queues by status, and every failed job",
        responses: { 200: json(JobStatusOut), 401: errors[401], 403: errors[403] },
      }),
      async (c) => c.json(await jobStatus(db), 200),
    );
}
