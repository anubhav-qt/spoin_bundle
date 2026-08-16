"use client";

/**
 * Replaces the single global "take a quiz" button (ADR-0014's QuizCTA) with
 * one row per followed topic — a coverage bar, nothing else. The row is
 * purely a status glance: name, current difficulty tier, coverage. Taking
 * the quiz is an action with real consequences (it changes progression), so
 * it lives one level deeper, inside the detail modal a click on the row
 * opens — not a button sitting in a scannable list where a stray tap could
 * trigger it.
 *
 * Structurally mirrors DiscoverBox on purpose (head + toggle, flat rows
 * separated by a hairline, a text block per row) rather than having its own
 * bespoke layout — two boxes doing the same job (a titled, filterable list
 * in the right rail) should look like the same kind of thing. The All/
 * Mastered/In Progress toggle filters the already-loaded `progress` map
 * client-side — no new request, since `mastered` is already a fact the
 * server sent for every followed topic.
 */

import { useState } from "react";

import type { Difficulty, Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
import { TopicStatsModal } from "./TopicStatsModal";

const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  beginner: "Beginner",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

type FilterMode = "all" | "mastered" | "active";

const FILTERS: { key: FilterMode; label: string }[] = [
  { key: "all", label: "All" },
  { key: "mastered", label: "Completed" },
  { key: "active", label: "In Progress" },
];

interface Props {
  topics: Topic[];
  progress: Record<string, TopicProgress>;
}

export function TopicsProgressBox({ topics, progress }: Props) {
  const [mode, setMode] = useState<FilterMode>("all");
  const [openTopicId, setOpenTopicId] = useState<string | null>(null);
  const openTopic = topics.find((t) => t.id === openTopicId) ?? null;

  const visible = topics.filter((topic) => {
    if (mode === "all") return true;
    const mastered = progress[topic.id]?.mastered ?? false;
    return mode === "mastered" ? mastered : !mastered;
  });

  return (
    <div className="progress-box">
      <div className="progress-box-head">
        <h3 className="progress-box-title mono">Your topics</h3>
        <div className="progress-toggle" role="group" aria-label="Filter your topics">
          {FILTERS.map(({ key, label }) => (
            <button key={key} type="button" data-active={mode === key} onClick={() => setMode(key)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="progress-box-list">
        {visible.length === 0 ? (
          <p className="progress-box-empty mono">
            {mode === "mastered" ? "Nothing completed yet" : mode === "active" ? "Everything here is completed" : "No topics followed yet"}
          </p>
        ) : (
          visible.map((topic) => (
            <TopicProgressRow
              key={topic.id}
              topic={topic}
              progress={progress[topic.id]}
              onOpen={() => setOpenTopicId(topic.id)}
            />
          ))
        )}
      </div>

      {openTopic !== null ? (
        <TopicStatsModal
          topicId={openTopic.id}
          topicName={openTopic.display_name}
          onClose={() => setOpenTopicId(null)}
        />
      ) : null}
    </div>
  );
}

function TopicProgressRow({
  topic,
  progress,
  onOpen,
}: {
  topic: Topic;
  progress: TopicProgress | undefined;
  onOpen: () => void;
}) {
  const coverage = progress?.coverage ?? 0;
  const unlocked = progress?.quizUnlocked ?? false;

  return (
    <div className="progress-row" onClick={onOpen} role="button" tabIndex={0}>
      <div className="progress-row-text">
        <div className="progress-row-top">
          <span className="progress-row-name">{topic.display_name}</span>
          <span className="progress-row-difficulty mono">
            {DIFFICULTY_LABEL[progress?.currentDifficulty ?? "beginner"]}
          </span>
        </div>
        {/* Where Discover's row shows "X followers" — this row's equivalent
            meta line is the coverage bar. */}
        <span className="meter">
          <span
            className="meter-fill"
            data-complete={unlocked}
            style={{ width: `${Math.min(coverage, 1) * 100}%` }}
          />
        </span>
      </div>
    </div>
  );
}
