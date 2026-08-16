"use client";

/**
 * The topic filter — name-only pills. Progress/quiz-readiness detail used to
 * live here too, but that congested a single chip; it now lives in
 * TopicsProgressBox instead (ADR-0015). This component's only job is
 * filtering the feed.
 */

import type { Topic } from "@/lib/api";

interface Props {
  topics: Topic[];
  selected: string[];
  onToggle: (topicId: string) => void;
}

export function TopicRail({ topics, selected, onToggle }: Props) {
  return (
    <div className="topic-rail" role="group" aria-label="Filter by topic">
      {topics.map((topic) => (
        <button
          key={topic.id}
          className="topic-chip"
          data-selected={selected.includes(topic.id)}
          aria-pressed={selected.includes(topic.id)}
          onClick={() => onToggle(topic.id)}
          type="button"
        >
          {/* Always the user's own name for the topic, never the canonical one. */}
          {topic.display_name}
        </button>
      ))}
    </div>
  );
}
