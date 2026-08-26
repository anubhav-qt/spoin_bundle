"use client";

/**
 * The mobile (≤680px) equivalent of `Sidebar`'s `.sidebar-topbar` +
 * `RightRail`'s `.rail-top-row`, merged into one fixed bar: below 680px
 * there's no vertical rail to host either one inline, and a phone doesn't
 * have room for two separate fixed rows. Both halves are CSS-hidden at that
 * width (`.sidebar-topbar`, `.rail-appearance`) so this doesn't duplicate
 * them, only relocates the same controls.
 *
 * `DailyGoalRing` and `FocusToggle` are pure-props components -- no fetch of
 * their own -- so rendering them a second time here is the same reasoning
 * that makes `AppShell`'s second `TopicRail` instance safe (see ADR-0063):
 * no duplicated request, no state to keep in sync.
 *
 * CSS-hidden above 680px via the same base `display: none` pattern as
 * `.mobile-topic-strip` -- rendered unconditionally rather than behind a
 * viewport check, so there's no SSR/hydration mismatch to worry about.
 */

import type { DailyGoalOut } from "@/lib/api";
import { DailyGoalRing } from "./DailyGoalRing";
import { FocusToggle } from "./FocusToggle";
import { RefreshIcon } from "./icons";
import { VIEW_LABEL, type ShellView } from "./Sidebar";

interface Props {
  onReset: () => void;
  onRefresh: () => void;
  view: ShellView;
  dailyGoal: DailyGoalOut;
  onEnterFocus: () => void;
}

export function MobileTopBar({ onReset, onRefresh, view, dailyGoal, onEnterFocus }: Props) {
  return (
    <div className="mobile-topbar">
      <button type="button" className="mobile-topbar-mark mono" onClick={onReset} aria-label="spoin">
        sp<span className="sidebar-mark-accent">o</span>in
      </button>

      <div className="mobile-topbar-controls">
        <DailyGoalRing cardsRead={dailyGoal.cards_read} goal={dailyGoal.goal} />
        <FocusToggle focused={false} onToggle={onEnterFocus} />
        <button
          type="button"
          className="mobile-topbar-refresh"
          onClick={onRefresh}
          aria-label={`Refresh ${VIEW_LABEL[view]}`}
        >
          <RefreshIcon />
        </button>
      </div>
    </div>
  );
}
