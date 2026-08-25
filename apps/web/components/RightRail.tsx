"use client";

/**
 * The right rail (ADR-0015), top to bottom: theme switcher + focus toggle,
 * font picker, topic filter, "View all topics" (opens `TopicDiscoveryModal`
 * on its Topics tab -- the full, unfiltered corpus), per-topic progress
 * ("Your topics"), then the inline `DiscoverBox` (ADR-0038 -- restored below
 * "Your topics", where it lived before ADR-0036 folded it into the modal).
 */

import { useEffect, useState } from "react";

import type { DailyGoalOut, Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
import { CloseIcon } from "./icons";
import { DailyGoalRing } from "./DailyGoalRing";
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
  onUnfollowed: (topicId: string) => void | Promise<void>;
  /** A generation request was cancelled (GenerationProgressPanel) -- the
   *  server already dropped the subscription; this just catches up local
   *  state, same tail end as `onUnfollowed` without a second API call. */
  onTopicRemoved: (topicId: string) => void;
  dailyGoal: DailyGoalOut;
  /** Below 1150px `.rail-right` renders as a sheet (slide-over on tablet,
   *  bottom sheet on phone) instead of inline, and these two control whether
   *  it's open. Above 1150px the CSS ignores `data-open` and keeps the rail
   *  always visible, so `open` is simply never true there -- the trigger
   *  that flips it (Sidebar's `onOpenRail`) is itself CSS-hidden on desktop. */
  open: boolean;
  onClose: () => void;
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
  onUnfollowed,
  onTopicRemoved,
  dailyGoal,
  open,
  onClose,
}: Props) {
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const [discoveryView, setDiscoveryView] = useState<"topics" | "custom" | "request">("topics");

  const openDiscovery = (view: "topics" | "custom" | "request") => {
    setDiscoveryView(view);
    setDiscoveryOpen(true);
  };

  // Both only take effect on the sheet's own presentation (≤1150px) -- see
  // the `open` prop's comment. Harmless no-ops on desktop, where `open`
  // never becomes true.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  return (
    <>
      {/* Only rendered visible ≤1150px (see the CSS); a no-op backdrop the
          rest of the time. Sits behind `.rail-right` itself, in front of
          everything else -- both fixed, both toggled by the same `open`. */}
      <div
        className="rail-sheet-backdrop"
        data-open={open}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className="rail-right" aria-label="Filters and insights" data-open={open}>
        {/* CSS-hidden above 1150px, same as the backdrop -- Escape and the
            backdrop click both already close the sheet; this is the visible,
            discoverable affordance for the same action. */}
        <button type="button" className="rail-sheet-close" onClick={onClose} aria-label="Close">
          <CloseIcon />
        </button>

        {/* Theme/font/focus/goal -- duplicated by `MobileTopBar` ≤680px
            (ADR-0061), so this whole group is CSS-hidden there rather than
            shown twice. Still the only copy 681-1150px, where the sheet is
            reachable but `MobileTopBar` doesn't render. */}
        <div className="rail-appearance">
          <div className="rail-top-row">
            <ThemePicker />
            <FocusToggle focused={false} onToggle={onEnterFocus} />
            <DailyGoalRing cardsRead={dailyGoal.cards_read} goal={dailyGoal.goal} />
          </div>

          {/* ADR-0037: right after the color-theme picker, per how it was asked for. */}
          <FontPicker />
        </div>

        {topics.length > 0 ? <TopicRail topics={topics} selected={selected} onToggle={onToggle} /> : null}

        {/* Right below the topic filters — opens straight to the full topic
            list (ADR-0038), not the 5-row-capped inline box below. */}
        <button type="button" className="view-all-topics" onClick={() => openDiscovery("topics")}>
          View all topics
        </button>

        <TopicsProgressBox
          topics={topics}
          progress={progress}
          onProgressChanged={onProgressChanged}
          onTopicColorChanged={onTopicColorChanged}
          onUnfollowed={onUnfollowed}
        />

        {/* The inline Discover box (ADR-0038), restored below "Your topics" --
            where it lived before ADR-0036 deleted it in favor of the modal. */}
        <DiscoverBox onFollowed={onFollowed} />

        {discoveryOpen ? (
          <TopicDiscoveryModal
            onFollowed={onFollowed}
            onTopicRemoved={onTopicRemoved}
            onClose={() => setDiscoveryOpen(false)}
            initialView={discoveryView}
          />
        ) : null}
      </aside>
    </>
  );
}
