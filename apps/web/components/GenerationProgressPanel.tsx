"use client";

/**
 * Live progress visualizer for topic generation:
 * - Overall aggregate progress gauge: (total cards + questions generated / total target).
 * - Stage indicator and metric stat cards.
 * - Interactive, filterable subtopic progress cards (no bulleted text wall).
 */

import { useEffect, useMemo, useState } from "react";

import { ApiError, api, type Difficulty, type GenerationProgress } from "@/lib/api";

const POLL_MS = 1000;

interface Props {
  topicId: string;
  topicDisplayName: string;
  onDismiss: () => void;
  onCancelled: () => void;
}

export function GenerationProgressPanel({
  topicId,
  topicDisplayName,
  onDismiss,
  onCancelled,
}: Props) {
  const [progress, setProgress] = useState<GenerationProgress | null>(null);
  const [pollError, setPollError] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [subtopicFilter, setSubtopicFilter] = useState<"all" | "in-progress" | "done">("all");

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const next = await api.generationProgress(topicId);
        if (cancelled) return;
        setProgress(next);
        setPollError(false);
        if (next.status === "completed" || next.status === "failed") return;
      } catch {
        if (cancelled) return;
        setPollError(true);
      }
      if (!cancelled) timer = setTimeout(() => void poll(), POLL_MS);
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, [topicId]);

  const cancel = async () => {
    if (cancelling) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await api.cancelGeneration(topicId);
      onCancelled();
    } catch (cause) {
      setCancelError(
        cause instanceof ApiError && cause.status === 409
          ? "Generation already started — can't cancel now"
          : "Couldn't cancel — try again",
      );
      setCancelling(false);
    }
  };

  // Compute aggregate progress metrics across all subtopics
  const metrics = useMemo(() => {
    if (!progress || progress.subtopics.length === 0) {
      return {
        cardsDone: 0,
        cardsTarget: 0,
        questionsDone: 0,
        questionsTarget: 0,
        subtopicsDone: 0,
        totalSubtopics: 0,
        overallPct: 0,
      };
    }

    let cardsDone = 0;
    let cardsTarget = 0;
    let questionsDone = 0;
    let questionsTarget = 0;
    let subtopicsDone = 0;

    for (const s of progress.subtopics) {
      cardsDone += s.cards_done;
      cardsTarget += s.cards_target;
      questionsDone += s.questions_done;
      if (s.questions_target !== null) {
        questionsTarget += s.questions_target;
      }
      if (s.cards_done >= s.cards_target && (s.questions_target === null || s.questions_done >= s.questions_target)) {
        subtopicsDone += 1;
      }
    }

    const totalDone = cardsDone + questionsDone;
    const totalTarget = cardsTarget + questionsTarget;
    const overallPct = totalTarget > 0 ? Math.min(Math.round((totalDone / totalTarget) * 100), 100) : 0;

    return {
      cardsDone,
      cardsTarget,
      questionsDone,
      questionsTarget,
      subtopicsDone,
      totalSubtopics: progress.subtopics.length,
      overallPct,
    };
  }, [progress]);

  const filteredSubtopics = useMemo(() => {
    if (!progress || !progress.subtopics) return [];
    if (subtopicFilter === "all") return progress.subtopics;
    if (subtopicFilter === "done") {
      return progress.subtopics.filter(
        (s) => s.cards_done >= s.cards_target && (s.questions_target === null || s.questions_done >= s.questions_target),
      );
    }
    return progress.subtopics.filter(
      (s) => s.cards_done < s.cards_target || (s.questions_target !== null && s.questions_done < s.questions_target),
    );
  }, [progress, subtopicFilter]);

  const terminal = progress?.status === "completed" || progress?.status === "failed";
  const showLiveBanner = progress !== null && progress.topic_live && progress.status !== "failed";

  return (
    <div className="gen-visualizer" role="status" aria-live="polite">
      {/* Header Bar */}
      <div className="gen-visualizer-head">
        <div className="gen-visualizer-title-row">
          <span className="gen-visualizer-name">{progress?.topic_name ?? topicDisplayName}</span>
          <span className="gen-visualizer-stage-badge mono" data-status={progress?.status ?? "pending"}>
            {progress?.status === "running"
              ? "Generating…"
              : progress?.status === "completed"
              ? "Ready"
              : progress?.status === "failed"
              ? "Failed"
              : "Queued"}
          </span>
        </div>
        <button
          type="button"
          className="gen-visualizer-dismiss"
          aria-label="Dismiss"
          onClick={onDismiss}
        >
          ×
        </button>
      </div>

      {showLiveBanner ? (
        <div className="gen-visualizer-live-pill mono">
          ✓ Live in Feed — cards available to read while generation finishes
        </div>
      ) : null}

      {/* Overall Progress Hero Bar */}
      <div className="gen-visualizer-progress-card">
        <div className="gen-progress-card-head">
          <div className="gen-progress-label-col">
            <span className="gen-progress-title mono">Overall Generation Progress</span>
            <span className="gen-progress-subtitle mono">
              {metrics.cardsDone} cards · {metrics.questionsDone} questions
            </span>
          </div>
          <span className="gen-progress-pct mono">{metrics.overallPct}%</span>
        </div>

        <div className="gen-meter-track">
          <div
            className="gen-meter-fill"
            style={{ width: `${metrics.overallPct}%` }}
          />
        </div>

        {/* 3 Metric Stat Cells */}
        <div className="gen-stats-grid">
          <div className="gen-stat-box">
            <span className="gen-stat-label mono">Cards</span>
            <span className="gen-stat-val mono">
              {metrics.cardsDone} <span className="gen-stat-tot">/ {metrics.cardsTarget}</span>
            </span>
          </div>

          <div className="gen-stat-box">
            <span className="gen-stat-label mono">Questions</span>
            <span className="gen-stat-val mono">
              {metrics.questionsDone} <span className="gen-stat-tot">/ {metrics.questionsTarget}</span>
            </span>
          </div>

          <div className="gen-stat-box">
            <span className="gen-stat-label mono">Subtopics</span>
            <span className="gen-stat-val mono">
              {metrics.subtopicsDone} <span className="gen-stat-tot">/ {metrics.totalSubtopics}</span>
            </span>
          </div>
        </div>
      </div>

      {/* Cancel Action if Pending */}
      {progress?.status === "pending" ? (
        <button
          type="button"
          className="gen-cancel-btn mono"
          onClick={() => void cancel()}
          disabled={cancelling}
        >
          {cancelling ? "Cancelling…" : "Cancel Generation"}
        </button>
      ) : null}

      {cancelError ? <p className="gen-error-note">{cancelError}</p> : null}
      {pollError ? <p className="gen-reconnect-note mono">Reconnecting…</p> : null}

      {/* Subtopics List Section */}
      {progress !== null && progress.subtopics.length > 0 ? (
        <div className="gen-subtopics-section">
          <div className="gen-subtopics-filter-row">
            <span className="gen-subtopics-title mono">
              Subtopics Breakdown ({progress.subtopics.length})
            </span>
            <div className="gen-filter-toggle">
              <button
                type="button"
                data-active={subtopicFilter === "all"}
                onClick={() => setSubtopicFilter("all")}
              >
                All
              </button>
              <button
                type="button"
                data-active={subtopicFilter === "in-progress"}
                onClick={() => setSubtopicFilter("in-progress")}
              >
                Active
              </button>
              <button
                type="button"
                data-active={subtopicFilter === "done"}
                onClick={() => setSubtopicFilter("done")}
              >
                Done
              </button>
            </div>
          </div>

          <div className="gen-subtopics-scroll-list">
            {filteredSubtopics.map((subtopic) => {
              const isSubtopicDone =
                subtopic.cards_done >= subtopic.cards_target &&
                (subtopic.questions_target === null || subtopic.questions_done >= subtopic.questions_target);
              const cardPct = fraction(subtopic.cards_done, subtopic.cards_target) * 100;
              const qPct =
                subtopic.questions_target === null
                  ? 0
                  : fraction(subtopic.questions_done, subtopic.questions_target) * 100;

              return (
                <div
                  key={subtopic.subtopic_id}
                  className="gen-subtopic-card"
                  data-complete={isSubtopicDone}
                >
                  <div className="gen-subtopic-card-top">
                    <span className="gen-subtopic-title">{subtopic.group_title}</span>
                    <span className="gen-subtopic-tier-tag mono">{subtopic.difficulty}</span>
                  </div>

                  <div className="gen-subtopic-bars-grid">
                    <div className="gen-subtopic-bar-item">
                      <div className="gen-bar-meta-row">
                        <span className="gen-bar-tag mono">Cards</span>
                        <span className="gen-bar-val mono">
                          {subtopic.cards_done}/{subtopic.cards_target}
                        </span>
                      </div>
                      <div className="gen-mini-track">
                        <div
                          className="gen-mini-fill"
                          data-complete={subtopic.cards_done >= subtopic.cards_target}
                          style={{ width: `${cardPct}%` }}
                        />
                      </div>
                    </div>

                    <div className="gen-subtopic-bar-item">
                      <div className="gen-bar-meta-row">
                        <span className="gen-bar-tag mono">Quiz Qs</span>
                        <span className="gen-bar-val mono">
                          {subtopic.questions_target === null
                            ? "queued"
                            : `${subtopic.questions_done}/${subtopic.questions_target}`}
                        </span>
                      </div>
                      <div className="gen-mini-track">
                        <div
                          className="gen-mini-fill"
                          data-complete={
                            subtopic.questions_target !== null &&
                            subtopic.questions_done >= subtopic.questions_target
                          }
                          style={{ width: `${qPct}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {terminal ? (
        <div className="gen-terminal-note mono">
          {progress?.status === "completed"
            ? "✓ Generation complete! All cards and quizzes are ready."
            : "✕ Generation stopped."}
        </div>
      ) : null}
    </div>
  );
}

function fraction(done: number, target: number): number {
  if (target <= 0) return done > 0 ? 1 : 0;
  return Math.min(done / target, 1);
}
