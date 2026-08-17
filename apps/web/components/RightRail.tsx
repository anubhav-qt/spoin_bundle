"use client";

/**
 * The right rail (ADR-0015), top to bottom: theme switcher + focus toggle,
 * topic filter, per-topic progress + quiz, request a topic, browse topics.
 *
 * ADR-0036: the inline Discover list moved into `TopicDiscoveryModal`
 * (opened from the "View all topics" button below), and RequestTopicBox
 * moved up to sit directly below the topic filter box.
 */

import { useState } from "react";

import type { Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
import { FocusToggle } from "./FocusToggle";
import { RequestTopicBox } from "./RequestTopicBox";
import { ThemePicker } from "./ThemePicker";
import { TopicDiscoveryModal } from "./TopicDiscoveryModal";
import { TopicRail } from "./TopicRail";
import { TopicsProgressBox } from "./TopicsProgressBox";

interface Props {
  topics: Topic[];
  progress: Record<string, TopicProgress>;
  selected: string[];
  onToggle: (topicId: string) => void;
  onFollowed: (topic: Topic) => void;
  onEnterFocus: () => void;
  onProgressChanged: (topicId: string) => void;
  onTopicColorChanged: (topicId: string, accentHue: number | null) => void;
}

export function RightRail({
  topics,
  progress,
  selected,
  onToggle,
  onFollowed,
  onEnterFocus,
  onProgressChanged,
  onTopicColorChanged,
}: Props) {
  const [discoveryOpen, setDiscoveryOpen] = useState(false);

  return (
    <aside className="rail-right" aria-label="Filters and insights">
      <div className="rail-top-row">
        <ThemePicker />
        <FocusToggle focused={false} onToggle={onEnterFocus} />
      </div>

      {topics.length > 0 ? <TopicRail topics={topics} selected={selected} onToggle={onToggle} /> : null}

      <TopicsProgressBox
        topics={topics}
        progress={progress}
        onProgressChanged={onProgressChanged}
        onTopicColorChanged={onTopicColorChanged}
      />

      <RequestTopicBox onFollowed={onFollowed} />

      <button type="button" className="discover-follow view-all-topics" onClick={() => setDiscoveryOpen(true)}>
        View all topics
      </button>

      {discoveryOpen ? (
        <TopicDiscoveryModal onFollowed={onFollowed} onClose={() => setDiscoveryOpen(false)} />
      ) : null}
    </aside>
  );
}
