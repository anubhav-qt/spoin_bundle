import type { QuizStartOut, QuizSubmitFreeTextOut, QuizSubmitMcqOut } from "@spoin/shared";
import {
  DIFFICULTIES,
  type Difficulty,
  difficultyRank,
  isTierless,
  nextTier,
  type QuestionKind,
  type QuizKind,
} from "@spoin/shared/enums";
import { and, count, eq, gte, inArray, notInArray, sql } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import {
  card,
  question,
  quizAttempt,
  quizAttemptQuestion,
  subtopic,
  userQuestionSeen,
  userTopicProgress,
} from "../db/schema.ts";
import type { Env } from "../env.ts";
import { HttpError } from "../lib/errors.ts";
import type { Snapshot } from "../topics/progress.ts";
import type { Grader } from "./grader.ts";
import { combinedScore, referencesQuestion } from "./grading.ts";

/*
 * The quiz lifecycle (ADR-0009, amended by ADR-0027): sampling, the attempt, grading
 * and the tier state machine. Two calls submit an attempt: the MCQ half is graded at
 * once, and the free-text half is the one call that waits on a model, and the one that
 * writes progression, once both halves of the score are known.
 *
 * A tierless topic (ADR-0106) has one quiz: mastery across every difficulty, behind
 * the same coverage gate, recorded in the advanced slot (see topics/progress.ts).
 */

type Progress = NonNullable<Snapshot["progress"]>;

/**
 * content-model.md: mastered = tier_content_complete[advanced] AND
 * tier_quiz_passed[advanced]. Opening a mastery quiz is the one place that coverage is
 * checked, so it latches here, the same pattern `ensureUnlockLatched` uses.
 */
async function latchContentComplete(db: Db, progress: Progress, rank: number) {
  if (progress.tierContentComplete[rank]) return;
  const complete = [...progress.tierContentComplete];
  complete[rank] = true;
  await db
    .update(userTopicProgress)
    .set({ tierContentComplete: complete })
    .where(
      and(eq(userTopicProgress.userId, progress.userId), eq(userTopicProgress.topicId, progress.topicId)),
    );
}

/** Which of the three attempt kinds this request is, or a 403. */
async function resolveKind(db: Db, difficulty: Difficulty, snap: Snapshot & { progress: Progress }) {
  if (isTierless(snap.scope)) {
    if (!snap.unlocked) throw new HttpError(403, "Not enough coverage yet");
    await latchContentComplete(db, snap.progress, difficultyRank(snap.quizTier));
    return "mastery" satisfies QuizKind;
  }

  const rank = difficultyRank(difficulty);
  const tierRank = difficultyRank(snap.tier);
  if (rank > tierRank) throw new HttpError(403, "Tier not reached yet");

  if (rank < tierRank) {
    // ADR-0027: practice below the current tier. Unlocked at subscribe time or by a
    // later promotion past it; promotion never re-locks a tier already passed through.
    if (!snap.progress.tierUnlocked[rank]) throw new HttpError(403, "Tier not unlocked yet");
    return "placement" satisfies QuizKind;
  }

  if (difficulty === "advanced") {
    if (!snap.unlocked) throw new HttpError(403, "Not enough advanced-tier coverage yet");
    await latchContentComplete(db, snap.progress, rank);
    return "mastery" satisfies QuizKind;
  }

  if (!snap.unlocked) throw new HttpError(403, "Tier not unlocked yet");
  return "promotion" satisfies QuizKind;
}

/**
 * Questions this reader hasn't seen first, then repeats when the bank is thin (task
 * 0011): never fail a quiz because everything available was asked before. A null
 * `difficulty` samples the whole topic.
 */
const sample = (
  tx: Tx,
  userId: string,
  topicId: string,
  difficulty: Difficulty | null,
  kind: QuestionKind,
  n: number,
  exclude: string[] = [],
) =>
  tx
    .select({
      id: question.id,
      stem: question.stem,
      options: question.options,
      difficulty: question.difficulty,
    })
    .from(question)
    .innerJoin(subtopic, eq(subtopic.id, question.subtopicId))
    .where(
      and(
        eq(subtopic.topicId, topicId),
        difficulty ? eq(question.difficulty, difficulty) : undefined,
        exclude.length ? notInArray(question.id, exclude) : undefined,
        eq(question.kind, kind),
        eq(question.status, "active"),
      ),
    )
    .orderBy(
      inArray(
        question.id,
        tx
          .select({ id: userQuestionSeen.questionId })
          .from(userQuestionSeen)
          .where(eq(userQuestionSeen.userId, userId)),
      ),
      sql`random()`,
    )
    .limit(n);

/** `n` split evenly across difficulties, any remainder to the hardest first: a mastery quiz leans hard. */
const evenSplit = (n: number): [Difficulty, number][] => {
  const k = DIFFICULTIES.length;
  return DIFFICULTIES.map((d, i) => [d, Math.floor(n / k) + (i >= k - (n % k) ? 1 : 0)]);
};

/**
 * A tierless topic's MCQs: an even split across difficulties, a short stratum topped
 * up from the rest, so a bank heavy in one difficulty cannot decide what a mastery
 * quiz tests. Asked easy to advanced, the order the feed served them in.
 */
async function sampleAcrossDifficulties(tx: Tx, userId: string, topicId: string, n: number) {
  const picked = [];
  for (const [d, share] of evenSplit(n)) picked.push(...(await sample(tx, userId, topicId, d, "mcq", share)));
  if (picked.length < n) {
    const ids = picked.map((q) => q.id);
    picked.push(...(await sample(tx, userId, topicId, null, "mcq", n - picked.length, ids)));
  }
  return picked.sort((a, b) => difficultyRank(a.difficulty) - difficultyRank(b.difficulty));
}

/** Gate, sample, and open an attempt. `snap` comes from `ensureUnlockLatched`, already latched. */
export async function start(
  db: Db,
  env: Env,
  userId: string,
  topicId: string,
  requested: Difficulty | undefined,
  snap: Snapshot,
): Promise<QuizStartOut> {
  const { progress } = snap;
  if (!progress) throw new HttpError(404, "Not subscribed to this topic");
  const tierless = isTierless(snap.scope);
  const difficulty = tierless ? snap.quizTier : requested;
  if (!difficulty) throw new HttpError(422, "Pick a difficulty: this topic has tiers");
  const kind = await resolveKind(db, difficulty, { ...snap, progress });

  return db.transaction(async (tx) => {
    const mcq = tierless
      ? await sampleAcrossDifficulties(tx, userId, topicId, env.QUIZ_MCQ_COUNT)
      : await sample(tx, userId, topicId, difficulty, "mcq", env.QUIZ_MCQ_COUNT);
    const [freeText] = await sample(
      tx,
      userId,
      topicId,
      tierless ? null : difficulty,
      "free_text",
      env.QUIZ_FREE_TEXT_COUNT,
    );
    if (mcq.length < env.QUIZ_MCQ_COUNT || !freeText) {
      const what = tierless ? "this topic" : "this tier";
      throw new HttpError(409, `Not enough questions generated yet for ${what} — check back soon`);
    }
    const asked = [...mcq, freeText];
    await tx
      .insert(userQuestionSeen)
      .values(asked.map((q) => ({ userId, questionId: q.id })))
      .onConflictDoNothing();
    const [attempt] = await tx
      .insert(quizAttempt)
      .values({ userId, topicId, difficulty, kind, startedAt: new Date() })
      .returning({ id: quizAttempt.id });
    if (!attempt) throw new Error("quiz attempt insert returned nothing");
    await tx
      .insert(quizAttemptQuestion)
      .values(asked.map((q) => ({ attemptId: attempt.id, questionId: q.id })));
    return {
      attempt_id: attempt.id,
      topic_id: topicId,
      difficulty,
      kind,
      mcq: mcq.map((q) => ({ question_id: q.id, stem: q.stem, options: q.options ?? [] })),
      free_text: { question_id: freeText.id, stem: freeText.stem },
    };
  });
}

/** 404, not 403, for someone else's attempt: don't confirm it exists. */
async function loadAttempt(db: Db | Tx, userId: string, attemptId: string, opts: { lock?: boolean } = {}) {
  const q = db.select().from(quizAttempt).where(eq(quizAttempt.id, attemptId));
  const [attempt] = await (opts.lock ? q.for("update") : q);
  if (!attempt || attempt.userId !== userId) throw new HttpError(404, "Unknown quiz attempt");
  return attempt;
}

const attemptQuestions = (tx: Db | Tx, attemptId: string, kind: QuestionKind) =>
  tx
    .select({
      questionId: question.id,
      correct: quizAttemptQuestion.correct,
      stem: question.stem,
      correctIndex: question.correctIndex,
      explanation: question.explanation,
      rubric: question.rubric,
      referenceAnswer: question.referenceAnswer,
    })
    .from(quizAttemptQuestion)
    .innerJoin(question, eq(question.id, quizAttemptQuestion.questionId))
    .where(and(eq(quizAttemptQuestion.attemptId, attemptId), eq(question.kind, kind)));

const answerOf = (attemptId: string, questionId: string) =>
  and(eq(quizAttemptQuestion.attemptId, attemptId), eq(quizAttemptQuestion.questionId, questionId));

/** Deterministic and immediate: nothing here waits on a model. */
export async function submitMcq(
  db: Db,
  userId: string,
  attemptId: string,
  answers: Map<string, number>,
): Promise<QuizSubmitMcqOut> {
  return db.transaction(async (tx) => {
    const attempt = await loadAttempt(tx, userId, attemptId, { lock: true });
    if (attempt.submittedAt) throw new HttpError(409, "MCQ answers already submitted");

    const questions = await attemptQuestions(tx, attemptId, "mcq");
    if (questions.length !== answers.size || questions.some((q) => !answers.has(q.questionId))) {
      throw new HttpError(422, "Answers must cover exactly this attempt's MCQ questions");
    }

    const results = [];
    for (const q of questions) {
      const selected = answers.get(q.questionId) as number;
      const correct = selected === q.correctIndex;
      await tx
        .update(quizAttemptQuestion)
        .set({ userAnswer: String(selected), correct })
        .where(answerOf(attemptId, q.questionId));
      results.push({
        question_id: q.questionId,
        correct,
        correct_index: q.correctIndex ?? 0,
        explanation: q.explanation ?? "",
      });
    }
    await tx.update(quizAttempt).set({ submittedAt: new Date() }).where(eq(quizAttempt.id, attemptId));

    const right = results.filter((r) => r.correct).length;
    return { attempt_id: attemptId, results, mcq_score: results.length ? right / results.length : 0 };
  });
}

/**
 * The per-user daily cap on graded submissions (overview.md: the one cost axis that
 * scales with what readers do rather than with the corpus).
 */
async function assertDailyGradeBudget(db: Db, env: Env, userId: string) {
  const dayStart = new Date();
  dayStart.setUTCHours(0, 0, 0, 0);
  const [row] = await db
    .select({ n: count() })
    .from(quizAttempt)
    .where(and(eq(quizAttempt.userId, userId), gte(quizAttempt.gradedAt, dayStart)));
  if ((row?.n ?? 0) >= env.QUIZ_FREE_TEXT_GRADES_PER_USER_PER_DAY) {
    throw new HttpError(429, "Daily quiz-grading limit reached, try again tomorrow");
  }
}

/** The model call, plus ADR-0009's check on what it returned. */
async function grade(
  grader: Grader,
  q: Awaited<ReturnType<typeof attemptQuestions>>[number],
  answer: string,
  signal?: AbortSignal,
) {
  const [graded] = await grader.gradeFreeText(
    [
      {
        index: 0,
        stem: q.stem,
        rubric: q.rubric ?? "",
        referenceAnswer: q.referenceAnswer ?? "",
        userAnswer: answer,
      },
    ],
    signal,
  );
  if (!graded) throw new HttpError(502, "Grading failed, try again");
  if (referencesQuestion(graded.justification, q.stem, q.referenceAnswer ?? "", answer)) {
    return { rubricLevel: graded.rubricLevel, justification: graded.justification };
  }
  return {
    rubricLevel: 0,
    justification: `[flagged: grader response did not clearly reference this question — treated as level 0] ${graded.justification}`,
  };
}

/** The tier state machine. Placement attempts never progress (ADR-0027). */
async function applyProgression(tx: Tx, userId: string, attempt: typeof quizAttempt.$inferSelect) {
  if (attempt.kind === "placement") return false;
  const where = and(eq(userTopicProgress.userId, userId), eq(userTopicProgress.topicId, attempt.topicId));
  const [progress] = await tx.select().from(userTopicProgress).where(where).for("update");
  if (!progress) return false;

  const passed = [...progress.tierQuizPassed];
  passed[difficultyRank(attempt.difficulty)] = true;
  const next = attempt.kind === "promotion" ? nextTier(attempt.difficulty) : null;
  await tx
    .update(userTopicProgress)
    .set({
      tierQuizPassed: passed,
      ...(next ? { currentDifficulty: next } : {}),
      ...(attempt.kind === "mastery" && !progress.masteredAt ? { masteredAt: new Date() } : {}),
    })
    .where(where);
  return true;
}

/** The cards behind every question answered wrong, once each. */
async function remediation(tx: Tx, attemptId: string) {
  const rows = await tx
    .select({ cardId: card.id, title: card.title, subtopicTitle: subtopic.title })
    .from(quizAttemptQuestion)
    .innerJoin(question, eq(question.id, quizAttemptQuestion.questionId))
    .innerJoin(card, eq(card.id, question.cardId))
    .innerJoin(subtopic, eq(subtopic.id, card.subtopicId))
    .where(and(eq(quizAttemptQuestion.attemptId, attemptId), eq(quizAttemptQuestion.correct, false)));
  const out = new Map<string, { card_id: string; title: string; subtopic_title: string }>();
  for (const r of rows) {
    if (!out.has(r.cardId))
      out.set(r.cardId, { card_id: r.cardId, title: r.title, subtopic_title: r.subtopicTitle });
  }
  return [...out.values()];
}

/** Grades the written answer, scores the attempt, and writes progression. */
export async function submitFreeText(
  db: Db,
  env: Env,
  grader: Grader,
  userId: string,
  attemptId: string,
  raw: string,
  signal?: AbortSignal,
): Promise<QuizSubmitFreeTextOut> {
  const attempt = await loadAttempt(db, userId, attemptId);
  if (!attempt.submittedAt) throw new HttpError(409, "Submit MCQ answers first");
  if (attempt.gradedAt) throw new HttpError(409, "Already graded");

  // Capped in characters, not UTF-16 units, so the cut never splits one; the slice
  // before the spread bounds the work on a huge paste.
  const answer = [...raw.slice(0, 2 * env.QUIZ_FREE_TEXT_ANSWER_MAX_CHARS)]
    .slice(0, env.QUIZ_FREE_TEXT_ANSWER_MAX_CHARS)
    .join("");
  await assertDailyGradeBudget(db, env, userId);

  const [q] = await attemptQuestions(db, attemptId, "free_text");
  if (!q) throw new HttpError(404, "No free-text question on this attempt");

  // No transaction is open across the model call; the lock below settles a race.
  const { rubricLevel, justification } = await grade(grader, q, answer, signal);
  const correct = rubricLevel >= env.QUIZ_FREE_TEXT_PASS_LEVEL;

  return db.transaction(async (tx) => {
    const locked = await loadAttempt(tx, userId, attemptId, { lock: true });
    if (locked.gradedAt) throw new HttpError(409, "Already graded");

    await tx
      .update(quizAttemptQuestion)
      .set({ userAnswer: answer, correct, rubricLevel, justification })
      .where(answerOf(attemptId, q.questionId));

    const mcq = await attemptQuestions(tx, attemptId, "mcq");
    const mcqFraction = mcq.length ? mcq.filter((m) => m.correct).length / mcq.length : 0;
    const score = combinedScore({
      mcqFraction,
      rubricLevel,
      mcqWeight: env.QUIZ_MCQ_WEIGHT,
      freeTextWeight: env.QUIZ_FREE_TEXT_WEIGHT,
    });
    const passed = score >= env.QUIZ_PASS_THRESHOLD;
    await tx
      .update(quizAttempt)
      .set({ score, passed, gradedAt: new Date() })
      .where(eq(quizAttempt.id, attemptId));

    return {
      attempt_id: attemptId,
      free_text: { question_id: q.questionId, rubric_level: rubricLevel, correct, justification },
      score,
      passed,
      remediation: passed ? [] : await remediation(tx, attemptId),
      progressed: passed ? await applyProgression(tx, userId, locked) : false,
    };
  });
}
