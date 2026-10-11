import { createRoute, z } from "@hono/zod-openapi";
import {
  CustomTopicStatusOut,
  Difficulty,
  GenerationProgressOut,
  OnboardingCompleteIn,
  ProgressOut,
  TopicBatchIn,
  TopicBatchOut,
  TopicColorIn,
  TopicCurriculumOut,
  TopicDiscoverOut,
  TopicOut,
  TopicRequestIn,
  TopicRequestOut,
  TopicStatsOut,
} from "@spoin/shared";
import type { Deps } from "../context.ts";
import { needUser } from "../lib/http.ts";
import { body, errors, ids, json, router } from "../lib/openapi.ts";
import { ensureUnlockLatched, toProgressOut } from "../topics/progress.ts";
import { requestTopic, requestTopics } from "../topics/request.ts";
import * as topics from "../topics/service.ts";

const TopicId = ids("topic_id");

/** Subscriptions, discovery and per-topic progress. */
export function topicsRoutes(deps: Deps) {
  const { db, env } = deps;
  return router()
    .openapi(
      createRoute({
        method: "post",
        path: "/topics",
        tags: ["topics"],
        summary: "Ask for a topic by name: an exact match subscribes, a new name is queued for toad_sage",
        request: body(TopicRequestIn),
        responses: {
          201: json(TopicRequestOut, "Subscribed, or queued"),
          401: errors[401],
          403: errors[403],
          409: errors[409],
          422: errors[422],
        },
      }),
      async (c) => {
        const caller = needUser(c);
        return c.json(await requestTopic(deps, caller.id, c.req.valid("json"), caller.isGuest), 201);
      },
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/topics/batch",
        tags: ["topics"],
        summary: "Several names at once; each row reports its own outcome (task 0032)",
        request: body(TopicBatchIn),
        responses: {
          201: json(TopicBatchOut, "Per-row outcomes"),
          401: errors[401],
          403: errors[403],
          422: errors[422],
        },
      }),
      async (c) => {
        const caller = needUser(c);
        const results = await requestTopics(deps, caller.id, c.req.valid("json").items, caller.isGuest);
        return c.json({ results }, 201);
      },
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/topics",
        tags: ["topics"],
        responses: { 200: json(z.array(TopicOut)), 401: errors[401] },
      }),
      async (c) => c.json(await topics.listSubscribed(db, needUser(c).id), 200),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/topics/custom",
        tags: ["topics"],
        summary: "This user's requested topics, with their latest job's status",
        responses: { 200: json(z.array(CustomTopicStatusOut)), 401: errors[401] },
      }),
      async (c) => c.json(await topics.listCustom(db, needUser(c).id), 200),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/topics/all",
        tags: ["topics"],
        summary: "Every live topic, plus the ones this user follows (ADR-0038)",
        responses: { 200: json(z.array(TopicDiscoverOut)), 401: errors[401] },
      }),
      async (c) => c.json(await topics.listAll(deps, needUser(c).id), 200),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/topics/discover",
        tags: ["topics"],
        // `for_you` runs the same query until there is a signal to personalise from (ADR-0015).
        summary: "The top live topics this user does not follow",
        request: { query: z.object({ mode: z.enum(["popular", "for_you"]).default("popular") }) },
        responses: { 200: json(z.array(TopicDiscoverOut)), 401: errors[401], 422: errors[422] },
      }),
      async (c) => c.json(await topics.discover(deps, needUser(c).id), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/topics/onboarding/complete",
        tags: ["topics"],
        request: body(OnboardingCompleteIn),
        responses: { 200: json(z.array(TopicOut)), 401: errors[401], 422: errors[422] },
      }),
      async (c) =>
        c.json(await topics.completeOnboarding(deps, needUser(c).id, c.req.valid("json").topics), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/topics/{topic_id}/subscribe",
        tags: ["topics"],
        request: { params: TopicId, query: z.object({ entry_difficulty: Difficulty.default("beginner") }) },
        responses: {
          201: json(TopicOut, "Subscribed"),
          401: errors[401],
          404: errors[404],
          409: errors[409],
        },
      }),
      async (c) => {
        const { topic_id } = c.req.valid("param");
        const { entry_difficulty } = c.req.valid("query");
        return c.json(await topics.subscribe(deps, needUser(c).id, topic_id, entry_difficulty), 201);
      },
    )
    .openapi(
      createRoute({
        method: "delete",
        path: "/topics/{topic_id}/subscribe",
        tags: ["topics"],
        request: { params: TopicId },
        responses: { 204: { description: "Unsubscribed" }, 401: errors[401], 404: errors[404] },
      }),
      async (c) => {
        await topics.unsubscribe(db, needUser(c).id, c.req.valid("param").topic_id);
        return c.body(null, 204);
      },
    )
    .openapi(
      createRoute({
        method: "patch",
        path: "/topics/{topic_id}/color",
        tags: ["topics"],
        request: { params: TopicId, ...body(TopicColorIn) },
        responses: { 200: json(TopicOut), 401: errors[401], 404: errors[404], 422: errors[422] },
      }),
      async (c) => {
        const { topic_id } = c.req.valid("param");
        return c.json(await topics.setColor(deps, needUser(c).id, topic_id, c.req.valid("json").hue), 200);
      },
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/topics/{topic_id}/generation-progress",
        tags: ["topics"],
        request: { params: TopicId },
        responses: { 200: json(GenerationProgressOut), 401: errors[401], 404: errors[404] },
      }),
      async (c) => {
        needUser(c);
        return c.json(await topics.generationProgress(deps, c.req.valid("param").topic_id), 200);
      },
    )
    .openapi(
      createRoute({
        method: "delete",
        path: "/topics/{topic_id}/generation-job",
        tags: ["topics"],
        summary: "Withdraw a request while its job is still pending",
        request: { params: TopicId },
        responses: {
          204: { description: "Cancelled" },
          401: errors[401],
          404: errors[404],
          409: errors[409],
        },
      }),
      async (c) => {
        await topics.cancelGeneration(db, needUser(c).id, c.req.valid("param").topic_id);
        return c.body(null, 204);
      },
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/topics/{topic_id}/stats",
        tags: ["topics"],
        request: { params: TopicId },
        responses: { 200: json(TopicStatsOut), 401: errors[401], 422: errors[422] },
      }),
      async (c) => c.json(await topics.stats(deps, needUser(c).id, c.req.valid("param").topic_id), 200),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/topics/{topic_id}/curriculum",
        tags: ["topics"],
        request: { params: TopicId },
        responses: { 200: json(TopicCurriculumOut), 401: errors[401], 422: errors[422] },
      }),
      async (c) => c.json(await topics.curriculum(deps, needUser(c).id, c.req.valid("param").topic_id), 200),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/topics/{topic_id}/progress",
        tags: ["topics"],
        summary: "Coverage of the current tier; writes the unlock latch the first time it is earned",
        request: { params: TopicId },
        responses: { 200: json(ProgressOut), 401: errors[401], 422: errors[422] },
      }),
      async (c) => {
        const { topic_id } = c.req.valid("param");
        return c.json(
          toProgressOut(topic_id, await ensureUnlockLatched(db, env.COVERAGE_GATE, needUser(c).id, topic_id)),
          200,
        );
      },
    );
}
