"use client";

/**
 * The quiz-taking flow: 9 MCQ + 1 free text, submitted as one action from the
 * user's side (ADR-0009's shape). The two API calls underneath stay separate
 * on purpose — `submit-mcq` grades deterministically and returns instantly,
 * `submit-free-text` is the one call in the whole API that blocks on an LLM —
 * so this fires them back to back and renders MCQ results the instant they
 * land while the written answer is still "Grading…". No client-side grading
 * of any kind: `correct_index` never reaches the browser until the server
 * hands back a per-question result.
 *
 * Portal + Escape-to-close + body-scroll-lock, matching TopicStatsModal /
 * Card.tsx's BlockModal idiom (ADR-0015).
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import {
  ApiError,
  api,
  type Difficulty,
  type McqResult,
  type QuizFreeTextSubmitResult,
  type QuizStart,
} from "@/lib/api";
import { invalidate } from "@/lib/refresh";
import { CheckIcon, CloseIcon } from "./icons";
import { SpoinWave } from "./SpoinWave";

interface Props {
  topicId: string;
  topicName: string;
  /** Omitted on a tierless topic, whose one quiz is a mastery quiz across the whole topic. */
  difficulty?: Difficulty;
  onClose: () => void;
  /** Fired once an attempt is fully graded, so the caller can refresh stats
   *  (tier badges, mastery, unlock state) without a full page reload. */
  onGraded: () => void;
}

const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  beginner: "Beginner",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

type Phase = "loading" | "blocked" | "answering" | "submitting" | "grading" | "done";

export function QuizModal({ topicId, topicName, difficulty, onClose, onGraded }: Props) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [blockedMessage, setBlockedMessage] = useState("");
  const [quiz, setQuiz] = useState<QuizStart | null>(null);
  const [mcqAnswers, setMcqAnswers] = useState<Record<string, number>>({});
  const [freeTextAnswer, setFreeTextAnswer] = useState("");
  const [mcqResults, setMcqResults] = useState<McqResult[] | null>(null);
  const [final, setFinal] = useState<QuizFreeTextSubmitResult | null>(null);
  const [submitError, setSubmitError] = useState("");

  const startQuiz = () => {
    setPhase("loading");
    setBlockedMessage("");
    setQuiz(null);
    setMcqAnswers({});
    setFreeTextAnswer("");
    setMcqResults(null);
    setFinal(null);
    setSubmitError("");
    api
      .startQuiz(topicId, difficulty)
      .then((started) => {
        setQuiz(started);
        setPhase("answering");
      })
      .catch((cause) => {
        setBlockedMessage(
          cause instanceof ApiError
            ? cause.message
            : "Couldn't start the quiz — try again in a moment",
        );
        setPhase("blocked");
      });
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(startQuiz, [topicId, difficulty]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  const allAnswered =
    quiz !== null &&
    quiz.mcq.every((q) => mcqAnswers[q.question_id] !== undefined) &&
    freeTextAnswer.trim().length > 0;

  const gradeFreeText = async (attemptId: string) => {
    setSubmitError("");
    setPhase("grading");
    try {
      const result = await api.submitFreeText(attemptId, freeTextAnswer.trim());
      setFinal(result);
      setPhase("done");
      onGraded();
      // A passed quiz can move the streak/momentum figures on Profile.
      invalidate("profile");
    } catch (cause) {
      setSubmitError(
        cause instanceof ApiError ? cause.message : "Couldn't grade your written answer",
      );
      setPhase("grading");
    }
  };

  const submit = async () => {
    if (quiz === null || !allAnswered) return;
    setSubmitError("");
    setPhase("submitting");
    try {
      const mcqResult = await api.submitMcq(
        quiz.attempt_id,
        quiz.mcq.map((q) => ({ question_id: q.question_id, selected_index: mcqAnswers[q.question_id] })),
      );
      setMcqResults(mcqResult.results);
    } catch (cause) {
      setSubmitError(cause instanceof ApiError ? cause.message : "Couldn't submit your answers");
      setPhase("answering");
      return;
    }

    await gradeFreeText(quiz.attempt_id);
  };

  const title =
    difficulty === undefined
      ? `Mastery quiz · ${topicName}`
      : `${DIFFICULTY_LABEL[difficulty]} quiz · ${topicName}`;

  return createPortal(
    <div
      className="modal-overlay"
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
    >
      <div
        className="modal-panel modal-panel-wide quiz-panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title">{title}</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>

        {phase === "loading" ? (
          <div className="modal-loading">
            <SpoinWave variant="inline" caption="Loading questions…" />
          </div>
        ) : null}

        {phase === "blocked" ? (
          <div className="quiz-blocked">
            <p className="mono">{blockedMessage}</p>
          </div>
        ) : null}

        {quiz !== null && phase !== "blocked" ? (
          <QuizBody
            quiz={quiz}
            phase={phase}
            mcqAnswers={mcqAnswers}
            onAnswer={(questionId, index) =>
              setMcqAnswers((current) => ({ ...current, [questionId]: index }))
            }
            freeTextAnswer={freeTextAnswer}
            onFreeTextChange={setFreeTextAnswer}
            mcqResults={mcqResults}
            final={final}
            allAnswered={allAnswered}
            submitError={submitError}
            onSubmit={() => void submit()}
            onRetryGrading={() => void gradeFreeText(quiz.attempt_id)}
            onRetry={startQuiz}
            onClose={onClose}
            progressedNote={
              difficulty === undefined
                ? "Progress saved — this topic is recorded as mastered."
                : "Progress saved — this tier is recorded as passed."
            }
          />
        ) : null}
      </div>
    </div>,
    document.body,
  );
}

function QuizBody({
  quiz,
  phase,
  mcqAnswers,
  onAnswer,
  freeTextAnswer,
  onFreeTextChange,
  mcqResults,
  final,
  allAnswered,
  submitError,
  onSubmit,
  onRetryGrading,
  onRetry,
  onClose,
  progressedNote,
}: {
  quiz: QuizStart;
  phase: Phase;
  mcqAnswers: Record<string, number>;
  onAnswer: (questionId: string, index: number) => void;
  freeTextAnswer: string;
  onFreeTextChange: (value: string) => void;
  mcqResults: McqResult[] | null;
  final: QuizFreeTextSubmitResult | null;
  allAnswered: boolean;
  submitError: string;
  onSubmit: () => void;
  onRetryGrading: () => void;
  onRetry: () => void;
  onClose: () => void;
  progressedNote: string;
}) {
  const locked = mcqResults !== null;

  if (phase === "done" && final !== null) {
    return (
      <div className="quiz-results">
        <div className="quiz-score" data-passed={final.passed}>
          <span className="quiz-score-value mono">{Math.round(final.score * 100)}%</span>
          <span className="quiz-score-label mono">{final.passed ? "Passed" : "Not this time"}</span>
        </div>

        {final.progressed ? (
          <p className="quiz-progressed mono">{progressedNote}</p>
        ) : null}

        <div className="quiz-freetext-result" data-correct={final.free_text.correct}>
          <div className="quiz-freetext-result-head">
            {final.free_text.correct ? <CheckIcon /> : <CloseIcon />}
            <span className="mono">Written answer · level {final.free_text.rubric_level}/3</span>
          </div>
          <p>{final.free_text.justification}</p>
        </div>

        {!final.passed && final.remediation.length > 0 ? (
          <div className="quiz-remediation">
            <h3 className="mono">Review these before your next attempt</h3>
            <ul>
              {final.remediation.map((card) => (
                <li key={card.card_id}>
                  <span className="quiz-remediation-title">{card.title}</span>
                  <span className="quiz-remediation-subtopic mono">{card.subtopic_title}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="quiz-actions">
          <button type="button" className="modal-follow" onClick={onRetry}>
            Try again
          </button>
          <button type="button" className="modal-quiz" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="quiz-body">
      {mcqResults !== null ? (
        <p className="quiz-mcq-tally mono">
          {mcqResults.filter((r) => r.correct).length}/{mcqResults.length} multiple choice correct
        </p>
      ) : null}
      <ol className="quiz-questions">
        {quiz.mcq.map((question, i) => {
          const result = mcqResults?.find((r) => r.question_id === question.question_id) ?? null;
          const selected = mcqAnswers[question.question_id];
          return (
            <li key={question.question_id} className="quiz-question">
              <p className="quiz-question-stem">
                <span className="quiz-question-index mono">{i + 1}</span>
                {question.stem}
              </p>
              <div className="quiz-options" role="radiogroup">
                {question.options.map((option, optionIndex) => {
                  const isSelected = selected === optionIndex;
                  const isCorrectAnswer = result !== null && optionIndex === result.correct_index;
                  const isWrongSelected = result !== null && isSelected && !result.correct;
                  return (
                    <button
                      key={optionIndex}
                      type="button"
                      role="radio"
                      aria-checked={isSelected}
                      className="quiz-option"
                      data-selected={isSelected}
                      data-correct={result !== null ? isCorrectAnswer : undefined}
                      data-wrong={result !== null ? isWrongSelected : undefined}
                      disabled={locked}
                      onClick={() => onAnswer(question.question_id, optionIndex)}
                    >
                      {option}
                    </button>
                  );
                })}
              </div>
              {result !== null ? (
                <p className="quiz-explanation mono" data-correct={result.correct}>
                  {result.correct ? "Correct" : "Incorrect"} — {result.explanation}
                </p>
              ) : null}
            </li>
          );
        })}

        <li className="quiz-question quiz-question-freetext">
          <p className="quiz-question-stem">
            <span className="quiz-question-index mono">{quiz.mcq.length + 1}</span>
            {quiz.free_text.stem}
          </p>
          <textarea
            className="quiz-freetext-input"
            value={freeTextAnswer}
            onChange={(e) => onFreeTextChange(e.target.value)}
            placeholder="Your answer…"
            rows={5}
            disabled={locked}
            maxLength={12000}
          />
          {phase === "grading" && !submitError ? (
            <p className="quiz-grading mono">Grading your written answer…</p>
          ) : null}
        </li>
      </ol>

      {submitError ? <p className="quiz-error mono">{submitError}</p> : null}

      {!locked ? (
        <button
          type="button"
          className="modal-quiz"
          disabled={!allAnswered || phase === "submitting"}
          onClick={onSubmit}
        >
          {phase === "submitting" ? "Submitting…" : "Submit quiz"}
        </button>
      ) : null}

      {locked && submitError ? (
        <button type="button" className="modal-quiz" onClick={onRetryGrading}>
          Retry grading
        </button>
      ) : null}
    </div>
  );
}
