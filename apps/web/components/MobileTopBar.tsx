"use client";

/**
 * The top bar for phone-width viewports (<=680px), where both rails are
 * hidden. Carries the wordmark, a refresh control, the daily-goal ring, and
 * the button that opens the Browse sheet (filters, appearance, topics,
 * discover, settings — everything the desktop right rail holds).
 *
 * Tablet portrait (680-900px) keeps the right rail visible and does NOT
 * render this bar — see `.mobile-topbar` in globals.css.
 *
 * The wordmark doubles as the dev-only reset easter egg, same as `Sidebar`.
 */

import type { DailyGoal } from "@/lib/api";
import { DailyGoalRing } from "./DailyGoalRing";
import { RefreshIcon, SlidersIcon } from "./icons";

interface Props {
  onReset: () => void;
  onRefresh: () => void;
  onOpenBrowse: () => void;
  /** Cards read today against the goal (ADR-0062) — feeds the ring. */
  dailyGoal: DailyGoal;
}

export function MobileTopBar({ onReset, onRefresh, onOpenBrowse, dailyGoal }: Props) {
  return (
    <header className="mobile-topbar">
      <button type="button" className="mobile-topbar-mark mono" onClick={onReset} aria-label="spoin">
        sp<span className="sidebar-mark-accent">o</span>in
      </button>

      <div className="mobile-topbar-actions">
        <button
          type="button"
          className="mobile-topbar-btn"
          onClick={onRefresh}
          aria-label="Refresh"
        >
          <RefreshIcon />
        </button>
        <button
          type="button"
          className="mobile-topbar-btn mobile-topbar-btn-primary"
          onClick={onOpenBrowse}
          aria-label="Browse and filter"
        >
          <SlidersIcon />
        </button>
        <DailyGoalRing cardsRead={dailyGoal.cards_read} goal={dailyGoal.goal} size={32} />
      </div>
    </header>
  );
}
