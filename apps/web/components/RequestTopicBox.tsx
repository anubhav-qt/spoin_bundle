"use client";

/**
 * A user typing a topic by name, rather than picking one from Discover.
 * POST /topics (api/routers/topics.py) either matches onto an existing topic
 * (subscribes immediately, done) or mints a new one and enqueues generation —
 * generation is never synchronous on free tier (ADR-0003), so a "generating"
 * response gets an honest "building this" message instead of cards.
 *
 * The form stays visible alongside any in-flight generations (not swapped
 * out for a single progress panel) — a reader can queue several custom
 * topics while earlier ones are still generating (no per-user cap right now,
 * see task 0024). Which topics are still being watched lives in
 * GenerationTrackerProvider, not local state, so switching tabs in
 * TopicDiscoveryModal or closing and reopening it doesn't lose them.
 *
 * Mirrors `.discover-box`'s look (see that file's header comment on why) —
 * this is one more "titled box in the right rail," not a bespoke form.
 */

import { useEffect, useRef, useState } from "react";

import { ApiError, api, type Topic } from "@/lib/api";
import { useGenerationTracker } from "./GenerationTrackerProvider";
import { GenerationProgressPanel } from "./GenerationProgressPanel";

interface Props {
  onFollowed: (topic: Topic) => void;
  /** A pending request was cancelled from one of the panels below -- see
   *  RightRail's docstring on the same prop. */
  onTopicRemoved: (topicId: string) => void;
}

// `POST /topics` is one synchronous request that can genuinely take the
// better part of a minute (it runs an LLM name-validation call, then a
// dedupe/embedding match against existing topics -- see topics/service.py's
// `request_topic`). There's no server-sent progress for this leg, so rather
// than sit on a static "Adding…" label the whole time (which reads as frozen
// -- exactly the complaint this replaced), the copy below advances on a
// timer to honestly narrate what's plausibly happening and to set the
// expectation that a long wait is normal, not broken.
const SUBMIT_STAGES: ReadonlyArray<{ afterMs: number; text: string }> = [
  { afterMs: 0, text: "Checking your topic…" },
  { afterMs: 2500, text: "Matching against existing topics…" },
  { afterMs: 9000, text: "Still working — this can take up to a minute…" },
];

export function RequestTopicBox({ onFollowed, onTopicRemoved }: Props) {
  const { generations, track, dismiss } = useGenerationTracker();
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitStage, setSubmitStage] = useState(0);
  const [notice, setNotice] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const stageTimers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    return () => {
      for (const timer of stageTimers.current) clearTimeout(timer);
    };
  }, []);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed || submitting) return;

    setSubmitting(true);
    setSubmitStage(0);
    setNotice(null);
    stageTimers.current = SUBMIT_STAGES.slice(1).map((stage, index) =>
      setTimeout(() => setSubmitStage(index + 1), stage.afterMs),
    );
    try {
      const result = await api.requestTopic(trimmed);
      onFollowed(result.topic);
      setName("");
      if (result.status === "generating") {
        track({ topicId: result.topic.id, displayName: result.topic.display_name });
      } else {
        setNotice({ tone: "info", text: `Following "${result.topic.display_name}"` });
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setNotice({ tone: "error", text: "Already following that topic" });
      } else if (cause instanceof ApiError) {
        setNotice({ tone: "error", text: cause.message });
      } else {
        setNotice({ tone: "error", text: "Something went wrong" });
      }
    } finally {
      for (const timer of stageTimers.current) clearTimeout(timer);
      stageTimers.current = [];
      setSubmitting(false);
    }
  };

  return (
    <div className="discover-box request-topic-box">
      <div className="discover-head">
        <h3 className="discover-title mono">Request a topic</h3>
      </div>

      <form
        className="request-topic-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <input
          type="text"
          className="request-topic-input"
          placeholder="e.g. Quantum computing"
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          disabled={submitting}
        />
        <button
          type="submit"
          className="discover-follow"
          disabled={submitting || name.trim().length === 0}
          aria-label={submitting ? "Adding…" : "Add"}
        >
          {submitting ? <span className="btn-spinner" aria-hidden="true" /> : "Add"}
        </button>
      </form>

      {submitting ? (
        <p className="request-topic-notice mono" role="status" aria-live="polite">
          {SUBMIT_STAGES[submitStage].text}
        </p>
      ) : notice ? (
        <p className={`request-topic-notice mono${notice.tone === "error" ? " error" : ""}`}>
          {notice.text}
        </p>
      ) : (
        <p className="discover-note request-topic-hint">New topics take a while to generate.</p>
      )}

      {generations.length > 0 ? (
        <div className="generation-progress-list">
          {generations.map((generation) => (
            <GenerationProgressPanel
              key={generation.topicId}
              topicId={generation.topicId}
              topicDisplayName={generation.displayName}
              onDismiss={() => dismiss(generation.topicId)}
              onCancelled={() => {
                dismiss(generation.topicId);
                onTopicRemoved(generation.topicId);
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
