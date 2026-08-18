"use client";

/**
 * The right rail (ADR-0015), top to bottom: theme switcher + focus toggle,
 * font picker, topic filter, "View all topics" (opens `TopicDiscoveryModal`
 * on its request-a-topic tab), per-topic progress ("Your topics"), then a
 * second "Discover" entry into the same modal, opened on its Discover tab.
 *
 * ADR-0036 originally folded the standalone Discover list and RequestTopicBox
 * into one modal reached from a single "View all topics" button. This splits
 * that one button into two entry points at different rail positions (per how
 * it was asked for), both opening the same `TopicDiscoveryModal` on whichever
 * tab makes sense from where the reader clicked.
 */

import { useState } from "react";

import type { Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
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
  const [discoveryView, setDiscoveryView] = useState<"discover" | "request" | "custom">("discover");

  const openDiscovery = (view: "discover" | "request" | "custom") => {
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

      {/* Right below the topic filters — opens on the "everything you can
          follow" tab, including the request-a-topic form (moved in here
          rather than living inline in the rail). */}
      <button type="button" className="discover-follow view-all-topics" onClick={() => openDiscovery("request")}>
        View all topics
      </button>

      <TopicsProgressBox
        topics={topics}
        progress={progress}
        onProgressChanged={onProgressChanged}
        onTopicColorChanged={onTopicColorChanged}
      />

      {/* Re-added below "Your topics" (ADR-0036 had folded this into the
          modal above only) — same modal, opened straight to Discover so
          finding something new is one click after checking your progress. */}
      <button type="button" className="discover-follow discover-entry" onClick={() => openDiscovery("discover")}>
        Discover
      </button>

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
