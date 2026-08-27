"use client";

/**
 * The daily-goal ring (ADR-0062): distinct cards read in the reader's local
 * day against `daily_card_goal`. An inline-SVG ring (two circles,
 * dasharray/dashoffset) with a detail popover — hover reveals it, a click
 * pins it open, dismissed by Escape or an outside click. Same DOM shape and
 * dismissal wiring as Card.tsx's `.share-popover`, reused via a second class
 * rather than a parallel set of popover styles.
 *
 * Rendered in `MobileTopBar` (<=680px) and the right rail's utility row.
 */

import { useEffect, useRef, useState } from "react";

interface Props {
  cardsRead: number;
  goal: number;
  /** Rendered px size; the viewBox is fixed at 40. */
  size?: number;
}

// r = 16 within the 40 viewBox.
const CIRCUMFERENCE = 2 * Math.PI * 16;

export function DailyGoalRing({ cardsRead, goal, size = 36 }: Props) {
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  const safeGoal = Math.max(goal, 1);
  const ratio = Math.min(Math.max(cardsRead / safeGoal, 0), 1);
  const complete = cardsRead >= safeGoal;
  const remaining = Math.max(safeGoal - cardsRead, 0);
  const open = hovered || pinned;

  useEffect(() => {
    if (!pinned) return;
    const onPointer = (event: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        setPinned(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPinned(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [pinned]);

  return (
    <div
      className="daily-goal-wrap"
      ref={wrapRef}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        className="daily-goal-trigger"
        aria-label={`Daily goal — ${cardsRead} of ${safeGoal} cards read`}
        aria-expanded={open}
        onClick={() => setPinned((value) => !value)}
      >
        <svg className="daily-ring" width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
          <circle className="daily-ring-track" cx="20" cy="20" r="16" />
          <circle
            className="daily-ring-fill"
            data-complete={complete}
            cx="20"
            cy="20"
            r="16"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE * (1 - ratio)}
            transform="rotate(-90 20 20)"
          />
          <text className="daily-ring-num" x="20" y="24.5" textAnchor="middle">
            {cardsRead}
          </text>
        </svg>
      </button>

      {open ? (
        <div className="share-popover daily-goal-popover" role="status">
          <span className="daily-goal-popover-count mono">
            {cardsRead} / {safeGoal}
          </span>
          <span className="daily-goal-popover-label">
            {complete
              ? "Daily goal reached"
              : remaining === 1
                ? "1 more card today"
                : `${remaining} more cards today`}
          </span>
        </div>
      ) : null}
    </div>
  );
}
