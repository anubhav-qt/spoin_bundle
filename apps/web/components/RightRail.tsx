"use client";

/**
 * The right rail (ADR-0015), top to bottom: theme switcher + focus toggle,
 * font picker, topic filter, "View all topics" (opens `TopicDiscoveryModal`
 * on its Topics tab -- the full, unfiltered corpus), per-topic progress
 * ("Your topics"), then the inline `DiscoverBox` (ADR-0038 -- restored below
 * "Your topics", where it lived before ADR-0036 folded it into the modal).
 */

import { useState } from "react";

import type { Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
import { DiscoverBox } from "./DiscoverBox";
import { FocusToggle } from "./FocusToggle";
import { FontPicker } from "./FontPicker";
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
  const [discoveryView, setDiscoveryView] = useState<"topics" | "custom" | "request">("topics");

  const openDiscovery = (view: "topics" | "custom" | "request") => {
    setDiscoveryView(view);
    setDiscoveryOpen(true);
  };

  return (
    <aside className="rail-right" aria-label="Filters and insights">
      <div className="rail-top-row">
        <ThemePicker />
        <FocusToggle focused={false} onToggle={onEnterFocus} />
      </div>

      {/* ADR-0037: right after the color-theme picker, per how it was asked for. */}
      <FontPicker />

      {topics.length > 0 ? <TopicRail topics={topics} selected={selected} onToggle={onToggle} /> : null}

      {/* Right below the topic filters — opens straight to the full topic
          list (ADR-0038), not the 5-row-capped inline box below. */}
      <button type="button" className="discover-follow view-all-topics" onClick={() => openDiscovery("topics")}>
        View all topics
      </button>

      <TopicsProgressBox
        topics={topics}
        progress={progress}
        onProgressChanged={onProgressChanged}
        onTopicColorChanged={onTopicColorChanged}
      />

      {/* The inline Discover box (ADR-0038), restored below "Your topics" --
          where it lived before ADR-0036 deleted it in favor of the modal. */}
      <DiscoverBox onFollowed={onFollowed} />

      {discoveryOpen ? (
        <TopicDiscoveryModal
          onFollowed={onFollowed}
          onClose={() => setDiscoveryOpen(false)}
          initialView={discoveryView}
        />
      ) : null}
    </aside>
  );
}
