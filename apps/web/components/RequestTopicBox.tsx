"use client";

/**
 * Request one or more topics by name, rather than picking from Discover.
 *
 * B2/B8 (task 0032): the box is a list of rows — a name plus an optional 1–2
 * sentence description each, `+` up to `MAX_ROWS` — and one submit that sends
 * the whole list as ONE batched call (`POST /topics/batch`). N sequential
 * `POST /topics` calls would spend N times the quota (ADR-0005: the free tier
 * meters requests). ADR-0025's matcher decides per row whether a name
 * canonicalises onto an existing topic or mints a new one; the caller never
 * chooses which.
 *
 * A batch can partly fail — a rejected name, an already-followed topic and a
 * freshly-minted one all from the same call — so after submit each row shows
 * its own outcome, not one blanket toast. The form stays in the rail alongside
 * any in-flight generations (tracked in `GenerationTrackerProvider`, not local
 * state, so switching tabs doesn't lose them).
 *
 * Mirrors `.discover-box`'s look — one more titled box in the right rail.
 */

import { useEffect, useRef, useState } from "react";

import { ApiError, api, type Topic, type TopicBatchItemResult } from "@/lib/api";
import { useGenerationTracker } from "./GenerationTrackerProvider";
import { GenerationProgressPanel } from "./GenerationProgressPanel";

interface Props {
  /** `hasCards` (default true) is false for a freshly-minted topic
   *  (`status === "generating"`) — see AppShell's `onFollowed` docstring on
   *  why the feed must not be invalidated until that topic actually has
   *  cards (task F9). Called once per row that produced a subscription. */
  onFollowed: (topic: Topic, hasCards?: boolean) => void;
  /** A pending request was cancelled from one of the panels below — see
   *  RightRail's docstring on the same prop. */
  onTopicRemoved: (topicId: string) => void;
}

/** Client courtesy mirror of `Settings.custom_topic_batch_max` — the server is
 *  the authority and 422s a longer list. */
const MAX_ROWS = 5;

interface Row {
  name: string;
  description: string;
}

// The batched call runs an LLM name-validation pass then a dedupe/embedding
// match — it can take the better part of a minute with no server-sent
// progress, so the copy advances on a timer rather than sitting on a static
// "Adding…" that reads as frozen.
const SUBMIT_STAGES: ReadonlyArray<{ afterMs: number; text: string }> = [
  { afterMs: 0, text: "Checking your topics…" },
  { afterMs: 2500, text: "Matching against existing topics…" },
  { afterMs: 9000, text: "Still working — this can take up to a minute…" },
];

const RESULT_COPY: Record<TopicBatchItemResult["status"], string> = {
  generating: "Generating — a few minutes",
  subscribed: "Added — cards ready",
  already_subscribed: "Already following this",
  rejected: "",
};

export function RequestTopicBox({ onFollowed, onTopicRemoved }: Props) {
  const { generations, track, dismiss } = useGenerationTracker();
  const [rows, setRows] = useState<Row[]>([{ name: "", description: "" }]);
  const [submitting, setSubmitting] = useState(false);
  const [submitStage, setSubmitStage] = useState(0);
  const [results, setResults] = useState<
    Array<{ result: TopicBatchItemResult; name: string }> | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const stageTimers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    return () => {
      for (const timer of stageTimers.current) clearTimeout(timer);
    };
  }, []);

  const setRow = (index: number, patch: Partial<Row>) => {
    setRows((cur) => cur.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  };
  const addRow = () => {
    setRows((cur) => (cur.length >= MAX_ROWS ? cur : [...cur, { name: "", description: "" }]));
  };
  const removeRow = (index: number) => {
    setRows((cur) => (cur.length <= 1 ? cur : cur.filter((_, i) => i !== index)));
  };
  const resetForm = () => {
    setResults(null);
    setError(null);
    setRows([{ name: "", description: "" }]);
  };

  const filled = rows
    .map((r) => ({ name: r.name.trim(), description: r.description.trim() }))
    .filter((r) => r.name.length > 0);

  const submit = async () => {
    if (submitting || filled.length === 0) return;

    setSubmitting(true);
    setSubmitStage(0);
    setError(null);
    stageTimers.current = SUBMIT_STAGES.slice(1).map((stage, index) =>
      setTimeout(() => setSubmitStage(index + 1), stage.afterMs),
    );
    try {
      const { results: batch } = await api.requestTopics(
        filled.map((r) => ({ name: r.name, description: r.description || undefined })),
      );
      for (const item of batch) {
        if (!item.topic) continue;
        if (item.status === "generating") {
          onFollowed(item.topic, false);
          track({ topicId: item.topic.id, displayName: item.topic.display_name });
        } else if (item.status === "subscribed") {
          onFollowed(item.topic, true);
        }
      }
      setResults(batch.map((result) => ({ result, name: filled[result.request_index].name })));
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) {
        setError("Sign up to request a custom topic.");
      } else if (cause instanceof ApiError) {
        setError(cause.message);
      } else {
        setError("Something went wrong.");
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
        <h3 className="discover-title mono">Request topics</h3>
        {!results && rows.length > 1 ? (
          <span className="request-topic-count mono">
            {rows.length} / {MAX_ROWS}
          </span>
        ) : null}
      </div>

      {results ? (
        <>
          <ul className="request-topic-results">
            {results.map(({ result, name }, i) => (
              <li key={i} className="request-topic-result" data-status={result.status}>
                <span className="request-topic-result-mark" aria-hidden="true">
                  {result.status === "rejected" ? (
                    <svg viewBox="0 0 24 24">
                      <path d="M6 6l12 12M18 6 6 18" />
                    </svg>
                  ) : result.status === "generating" ? (
                    <svg viewBox="0 0 24 24">
                      <path d="M12 3a9 9 0 1 0 9 9" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24">
                      <path d="M20 6 9 17l-5-5" />
                    </svg>
                  )}
                </span>
                <span className="request-topic-result-body">
                  <span className="request-topic-result-name">
                    {result.topic?.display_name ?? name}
                  </span>
                  <span className="request-topic-result-note mono">
                    {result.status === "rejected"
                      ? result.detail || "That doesn’t look like a learnable topic"
                      : RESULT_COPY[result.status]}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <button type="button" className="request-topic-add" onClick={resetForm}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 5v14M5 12h14" />
            </svg>
            Request more
          </button>
        </>
      ) : (
        <form
          className="request-topic-rows"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {rows.map((row, index) => (
            <div className="request-topic-row" key={index}>
              <div className="request-topic-row-name">
                <input
                  type="text"
                  className="request-topic-input"
                  placeholder="e.g. Quantum computing"
                  value={row.name}
                  maxLength={120}
                  disabled={submitting}
                  onChange={(e) => setRow(index, { name: e.target.value })}
                />
                {rows.length > 1 ? (
                  <button
                    type="button"
                    className="request-topic-row-remove"
                    aria-label={`Remove row ${index + 1}`}
                    disabled={submitting}
                    onClick={() => removeRow(index)}
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M6 6l12 12M18 6 6 18" />
                    </svg>
                  </button>
                ) : null}
              </div>
              <textarea
                className="request-topic-desc"
                rows={2}
                placeholder="What do you want from this topic? (optional)"
                value={row.description}
                maxLength={400}
                disabled={submitting}
                onChange={(e) => setRow(index, { description: e.target.value })}
              />
            </div>
          ))}

          {rows.length < MAX_ROWS ? (
            <button
              type="button"
              className="request-topic-add"
              disabled={submitting}
              onClick={addRow}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 5v14M5 12h14" />
              </svg>
              Add another
            </button>
          ) : null}

          <button
            type="submit"
            className="request-topic-submit mono"
            disabled={submitting || filled.length === 0}
          >
            {submitting ? (
              <span className="btn-spinner" aria-hidden="true" />
            ) : filled.length === 0 ? (
              "Add topics"
            ) : filled.length === 1 ? (
              "Add 1 topic"
            ) : (
              `Add ${filled.length} topics`
            )}
          </button>

          {submitting ? (
            <p className="request-topic-notice mono" role="status" aria-live="polite">
              {SUBMIT_STAGES[submitStage].text}
            </p>
          ) : error ? (
            <p className="request-topic-notice mono error">{error}</p>
          ) : (
            <p className="discover-note request-topic-hint">
              One matched call for all of them. New topics take a few minutes.
            </p>
          )}
        </form>
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
