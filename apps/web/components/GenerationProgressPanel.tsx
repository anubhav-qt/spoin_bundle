"use client";

/**
 * Live progress for a just-requested custom topic (RequestTopicBox). Polls
 * `GET /topics/{id}/generation-progress` (docs/adr) once a second while the
 * job is pending/running, rendering exactly what the backend is doing right
 * now rather than a single opaque "building this" notice: curriculum first,
 * then the resulting subtopics, each with its own card-generation bar and
 * (once the card count for that tier is known) its own question-generation
 * bar. Stops polling the moment the job reaches a terminal status.
 */

import { useEffect, useRef, useState } from "react";

import { api, type GenerationProgress } from "@/lib/api";

const POLL_MS = 1000;

interface Props {
  topicId: string;
  topicDisplayName: string;
  onRequestAnother: () => void;
}

export function GenerationProgressPanel({ topicId, topicDisplayName, onRequestAnother }: Props) {
  const [progress, setProgress] = useState<GenerationProgress | null>(null);
  const [pollError, setPollError] = useState(false);

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
        // A blip (the job row briefly not existing yet, a dropped request) --
        // shown as a quiet "reconnecting" note, not a hard failure. The next
        // tick tries again on its own.
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

  const message = loaderMessage(progress, topicDisplayName);
  const groupTitles = curriculumGroupTitles(progress);
  const terminal = progress?.status === "completed" || progress?.status === "failed";

  return (
    <div className="generation-progress" role="status" aria-live="polite">
      <p className="generation-progress-message mono" data-tone={progress?.status === "failed" ? "error" : "info"}>
        {message}
      </p>

      {pollError ? <p className="generation-progress-note mono">Reconnecting…</p> : null}

      {progress?.status === "failed" && progress.error ? (
        <p className="generation-progress-error">{progress.error}</p>
      ) : null}

      {groupTitles.length > 0 ? (
        <ul className="generation-curriculum">
          {groupTitles.map((title) => (
            <li key={title}>{title}</li>
          ))}
        </ul>
      ) : null}

      {progress !== null && progress.subtopics.length > 0 ? (
        <div className="generation-subtopics">
          {progress.subtopics.map((subtopic) => (
            <div key={subtopic.subtopic_id} className="generation-subtopic-row">
              <div className="generation-subtopic-head">
                <span className="generation-subtopic-name">{subtopic.group_title}</span>
                <span className="generation-subtopic-difficulty mono">{subtopic.difficulty}</span>
              </div>

              <div className="generation-bar-row">
                <span className="generation-bar-label mono">Cards</span>
                <span className="meter">
                  <span
                    className="meter-fill"
                    data-complete={subtopic.cards_done >= subtopic.cards_target}
                    style={{ width: `${fraction(subtopic.cards_done, subtopic.cards_target) * 100}%` }}
                  />
                </span>
                <span className="generation-bar-count mono">
                  {subtopic.cards_done}/{subtopic.cards_target}
                </span>
              </div>

              <div className="generation-bar-row">
                <span className="generation-bar-label mono">Questions</span>
                <span className="meter">
                  <span
                    className="meter-fill"
                    data-complete={
                      subtopic.questions_target !== null &&
                      subtopic.questions_done >= subtopic.questions_target
                    }
                    style={{
                      width:
                        subtopic.questions_target === null
                          ? "0%"
                          : `${fraction(subtopic.questions_done, subtopic.questions_target) * 100}%`,
                    }}
                  />
                </span>
                <span className="generation-bar-count mono">
                  {subtopic.questions_target === null
                    ? "waiting on cards"
                    : `${subtopic.questions_done}/${subtopic.questions_target}`}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {terminal ? (
        <button type="button" className="generation-request-another mono" onClick={onRequestAnother}>
          Request another topic
        </button>
      ) : null}
    </div>
  );
}

function fraction(done: number, target: number): number {
  if (target <= 0) return done > 0 ? 1 : 0;
  return Math.min(done / target, 1);
}

function curriculumGroupTitles(progress: GenerationProgress | null): string[] {
  if (progress === null) return [];
  const seen = new Set<string>();
  const titles: string[] = [];
  for (const subtopic of progress.subtopics) {
    if (seen.has(subtopic.group_title)) continue;
    seen.add(subtopic.group_title);
    titles.push(subtopic.group_title);
  }
  return titles;
}

function loaderMessage(progress: GenerationProgress | null, topicDisplayName: string): string {
  if (progress === null) return `Queuing "${topicDisplayName}"…`;

  if (progress.status === "pending") return "Waiting for the generator…";
  if (progress.status === "failed") return "Generation failed";
  if (progress.status === "completed") {
    return `Card generation done — "${progress.topic_name ?? topicDisplayName}" is available in the feed`;
  }

  // status === "running"
  const name = progress.topic_name ?? topicDisplayName;
  if (progress.stage === "curriculum" || progress.subtopics.length === 0) {
    return `Designing the curriculum for "${name}"…`;
  }

  const cardsRemaining = progress.subtopics.filter((s) => s.cards_done < s.cards_target);
  if (cardsRemaining.length > 0) {
    return `Writing cards — ${cardsRemaining.length} subtopic${cardsRemaining.length === 1 ? "" : "s"} left…`;
  }

  const questionsRemaining = progress.subtopics.filter(
    (s) => s.questions_target === null || s.questions_done < s.questions_target,
  );
  if (questionsRemaining.length > 0) {
    return `Writing quiz questions — ${questionsRemaining.length} subtopic${
      questionsRemaining.length === 1 ? "" : "s"
    } left…`;
  }

  return "Finishing up…";
}
