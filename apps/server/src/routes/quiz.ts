import { createRoute } from "@hono/zod-openapi";
import {
  QuizStartIn,
  QuizStartOut,
  QuizSubmitFreeTextIn,
  QuizSubmitFreeTextOut,
  QuizSubmitMcqIn,
  QuizSubmitMcqOut,
} from "@spoin/shared";
import type { Deps } from "../context.ts";
import { needUser } from "../lib/http.ts";
import { body, errors, ids, json, router } from "../lib/openapi.ts";
import { start, submitFreeText, submitMcq } from "../quiz/service.ts";
import { ensureUnlockLatched } from "../topics/progress.ts";

/** Quizzes (ADR-0009, amended by ADR-0027). Free-text grading is the one call here that waits on a model. */
export function quizRoutes(deps: Deps) {
  const { db, env, grader } = deps;
  const AttemptId = ids("attempt_id");

  return router()
    .openapi(
      createRoute({
        method: "post",
        path: "/topics/{topic_id}/quiz/start",
        tags: ["quiz"],
        summary:
          "Open an attempt: placement below the current tier, promotion at it, mastery at advanced; a tierless topic's one quiz is mastery",
        request: { params: ids("topic_id"), ...body(QuizStartIn) },
        responses: {
          201: json(QuizStartOut, "Created"),
          401: errors[401],
          403: errors[403],
          404: errors[404],
          409: errors[409],
          422: errors[422],
        },
      }),
      async (c) => {
        const userId = needUser(c).id;
        const { topic_id } = c.req.valid("param");
        // Read and latched by the topics module first, so the two agree on what is unlocked.
        const snap = await ensureUnlockLatched(db, env.COVERAGE_GATE, userId, topic_id);
        return c.json(await start(db, env, userId, topic_id, c.req.valid("json").difficulty, snap), 201);
      },
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/quiz/attempts/{attempt_id}/submit-mcq",
        tags: ["quiz"],
        request: { params: AttemptId, ...body(QuizSubmitMcqIn) },
        responses: {
          200: json(QuizSubmitMcqOut),
          401: errors[401],
          404: errors[404],
          409: errors[409],
          422: errors[422],
        },
      }),
      async (c) => {
        const answers = new Map(c.req.valid("json").answers.map((a) => [a.question_id, a.selected_index]));
        return c.json(await submitMcq(db, needUser(c).id, c.req.valid("param").attempt_id, answers), 200);
      },
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/quiz/attempts/{attempt_id}/submit-free-text",
        tags: ["quiz"],
        summary: "Grade the written answer, score the attempt, and write progression",
        request: { params: AttemptId, ...body(QuizSubmitFreeTextIn) },
        responses: {
          200: json(QuizSubmitFreeTextOut),
          401: errors[401],
          404: errors[404],
          409: errors[409],
          422: errors[422],
          429: errors[429],
          502: errors[502],
        },
      }),
      async (c) =>
        c.json(
          await submitFreeText(
            db,
            env,
            grader,
            needUser(c).id,
            c.req.valid("param").attempt_id,
            c.req.valid("json").answer,
          ),
          200,
        ),
    );
}
