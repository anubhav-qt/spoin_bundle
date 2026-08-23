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
 * Structurally mirrors TopicDiscoveryModal's row layout on purpose (head +
 * toggle, flat rows separated by a hairline, a text block per row) rather
 * than having its own bespoke layout. The All/
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
  { key: "active", label: "In Progress" },
  { key: "mastered", label: "Completed" },
  { key: "all", label: "All" },
];

interface Props {
  topics: Topic[];
  progress: Record<string, TopicProgress>;
  onProgressChanged: (topicId: string) => void;
  onTopicColorChanged: (topicId: string, accentHue: number | null) => void;
  onUnfollowed: (topicId: string) => void | Promise<void>;
}

export function TopicsProgressBox({
  topics,
  progress,
  onProgressChanged,
  onTopicColorChanged,
  onUnfollowed,
}: Props) {
  const [mode, setMode] = useState<FilterMode>("active");
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
          accentHue={openTopic.accent_hue}
          topicIndex={topics.indexOf(openTopic)}
          onColorChanged={(hue) => onTopicColorChanged(openTopic.id, hue)}
          onClose={() => setOpenTopicId(null)}
          onProgressChanged={onProgressChanged}
          onUnfollow={async () => {
            await onUnfollowed(openTopic.id);
            setOpenTopicId(null);
          }}
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
  const pct = Math.round(Math.min(coverage, 1) * 100);
  const unlocked = progress?.quizUnlocked ?? false;
  const difficulty = progress?.currentDifficulty ?? "beginner";

  return (
    <div className="progress-row" onClick={onOpen} role="button" tabIndex={0}>
      <div className="progress-row-text">
        <div className="progress-row-top">
          <span className="progress-row-name">{topic.display_name}</span>
          <div className="progress-row-meta-right">
            <span className="progress-row-pct mono">{pct}%</span>
            <span className="progress-row-difficulty mono" data-tier={difficulty}>
              {DIFFICULTY_LABEL[difficulty]}
            </span>
          </div>
        </div>
        <div className="progress-row-meter-wrap">
          <div
            className="progress-row-meter-fill"
            data-complete={unlocked}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    </div>
  );
}
