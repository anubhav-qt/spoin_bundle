"use client";

/**
 * Replaces the single global "take a quiz" button (ADR-0014's QuizCTA) with
 * one row per followed topic — a coverage bar and a per-row quiz pill that
 * enables at 80%, instead of one bit collapsing every topic's state into a
 * single button (ADR-0015). Clicking a row's body opens the detailed stats
 * modal for that topic.
 */

import { useState } from "react";

import type { Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
import { TopicStatsModal } from "./TopicStatsModal";

interface Props {
  topics: Topic[];
  progress: Record<string, TopicProgress>;
}

export function TopicsProgressBox({ topics, progress }: Props) {
  const [openTopicId, setOpenTopicId] = useState<string | null>(null);
  const openTopic = topics.find((t) => t.id === openTopicId) ?? null;

  return (
    <div className="progress-box">
      <h3 className="progress-box-title mono">Your topics</h3>

      {topics.map((topic) => (
        <TopicProgressRow
          key={topic.id}
          topic={topic}
          progress={progress[topic.id]}
          onOpen={() => setOpenTopicId(topic.id)}
        />
      ))}

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
  const [announced, setAnnounced] = useState(false);
  const coverage = progress?.coverage ?? 0;
  const unlocked = progress?.quizUnlocked ?? false;

  return (
    <div className="progress-row" onClick={onOpen} role="button" tabIndex={0}>
      <div className="progress-row-main">
        <span className="progress-row-name">{topic.display_name}</span>
        <span className="meter">
          <span className="meter-fill" data-complete={unlocked} style={{ width: `${Math.min(coverage, 1) * 100}%` }} />
        </span>
      </div>

      <button
        type="button"
        className="progress-row-quiz"
        data-locked={!unlocked}
        disabled={!unlocked}
        onClick={(e) => {
          e.stopPropagation();
          setAnnounced(true);
        }}
      >
        {!unlocked ? "Locked" : announced ? "Soon" : "Quiz"}
      </button>
    </div>
  );
}
