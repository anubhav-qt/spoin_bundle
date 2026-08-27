"use client";

/**
 * The right rail (ADR-0015), top to bottom: theme switcher + focus toggle,
 * font picker, topic filter, "View all topics" (opens `TopicDiscoveryModal`
 * on its Topics tab -- the full, unfiltered corpus), per-topic progress
 * ("Your topics"), then the inline `DiscoverBox` (ADR-0038 -- restored below
 * "Your topics", where it lived before ADR-0036 folded it into the modal).
 *
 * `variant="sheet"` renders the same content as a bottom sheet for phone
 * widths, where the rail column itself is hidden -- the Browse button in
 * `MobileTopBar` opens it. Everything below the sheet chrome is identical to
 * the rail; only the wrapper and a Settings shortcut differ.
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import type { DailyGoal, Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
import { DailyGoalRing } from "./DailyGoalRing";
import { DiscoverBox } from "./DiscoverBox";
import { FocusToggle } from "./FocusToggle";
import { FontPicker } from "./FontPicker";
import { GearIcon } from "./icons";
import type { ShellView } from "./Sidebar";
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
  /** Cards read today against the goal (ADR-0062) — feeds the rail's ring.
   *  The sheet omits the ring (it's in `MobileTopBar` there). */
  dailyGoal: DailyGoal;
  /** "rail" (default) docks it in the grid column; "sheet" renders it as a
   *  bottom sheet over the feed for phone widths. */
  variant?: "rail" | "sheet";
  /** Sheet only: close it. */
  onClose?: () => void;
  /** Sheet only: jump to a view (used by the Settings shortcut). */
  onNavigate?: (view: ShellView) => void;
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
  variant = "rail",
  onClose,
  onNavigate,
}: Props) {
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const [discoveryView, setDiscoveryView] = useState<"topics" | "custom" | "request">("topics");

  const openDiscovery = (view: "topics" | "custom" | "request") => {
    setDiscoveryView(view);
    setDiscoveryOpen(true);
  };

  // Sheet: Escape closes it, and lock the window-level feed scroll behind it
  // (same idiom as TopicStatsModal / Card.tsx's BlockModal).
  useEffect(() => {
    if (variant !== "sheet") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [variant, onClose]);

  // Docked rail: a four-up utility row — daily-goal ring, then Theme and Font
  // as equal-width dropdown controls, then the focus toggle. The sheet keeps
  // the pickers expanded (swatch grid + Aa row) under "Appearance" and has no
  // ring (that's in MobileTopBar there).
  const topControls =
    variant === "sheet" ? (
      <>
        <div className="rail-top-row">
          <ThemePicker />
        </div>
        {/* ADR-0037: right after the color-theme picker, per how it was asked for. */}
        <FontPicker />
      </>
    ) : (
      <div className="rail-utility">
        {/* Each column carries a `.picker-dropdown-label` on top (ADR-0064
            design canvas) — "Today" over the ring, matching "Theme"/"Font"
            from the two `PickerDropdown`s. Focus takes a blank spacer label
            so its icon baseline-aligns with the dropdown triggers. */}
        <div className="rail-utility-col">
          <span className="picker-dropdown-label">Today</span>
          <DailyGoalRing cardsRead={dailyGoal.cards_read} goal={dailyGoal.goal} size={38} />
        </div>
        <ThemePicker variant="dropdown" />
        <FontPicker variant="dropdown" />
        <div className="rail-utility-col">
          <span className="picker-dropdown-label" aria-hidden="true">
            &nbsp;
          </span>
          <FocusToggle focused={false} onToggle={onEnterFocus} />
        </div>
      </div>
    );

  const contents = (
    <>
      {topControls}

      {topics.length > 0 ? (
        <TopicRail
          topics={topics}
          selected={selected}
          onToggle={onToggle}
          progress={progress}
        />
      ) : null}

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
    </>
  );

  const discoveryModal = discoveryOpen ? (
    <TopicDiscoveryModal
      onFollowed={onFollowed}
      onTopicRemoved={onTopicRemoved}
      onClose={() => setDiscoveryOpen(false)}
      initialView={discoveryView}
    />
  ) : null;

  if (variant === "sheet") {
    return createPortal(
      <div
        className="browse-sheet-overlay"
        onClick={(event) => {
          if (event.target === event.currentTarget) onClose?.();
        }}
      >
        <aside className="browse-sheet" role="dialog" aria-modal="true" aria-label="Browse">
          <div className="browse-sheet-head">
            <span className="browse-sheet-grip" aria-hidden="true" />
            <div className="browse-sheet-head-row">
              <h2 className="browse-sheet-title">Browse</h2>
              <button
                type="button"
                className="browse-sheet-close"
                aria-label="Close"
                onClick={() => onClose?.()}
              >
                &times;
              </button>
            </div>
          </div>

          <div className="browse-sheet-body">
            {contents}

            {onNavigate ? (
              <button
                type="button"
                className="browse-sheet-settings"
                onClick={() => {
                  onNavigate("settings");
                  onClose?.();
                }}
              >
                <span className="browse-sheet-settings-icon">
                  <GearIcon />
                </span>
                Settings
              </button>
            ) : null}
          </div>
        </aside>

        {discoveryModal}
      </div>,
      document.body,
    );
  }

  return (
    <aside className="rail-right" aria-label="Filters and insights">
      {contents}
      {discoveryModal}
    </aside>
  );
}
