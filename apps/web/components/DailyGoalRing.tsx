"use client";

/**
 * Small circular progress ring for `daily_card_goal`, in the rail's utility
 * strip alongside ThemePicker/FocusToggle. Shows how many cards were
 * completed against today's goal (`/profile/me/today`, ADR-0060's local-day
 * definition) without taking up permanent rail space the way a full progress
 * bar would.
 *
 * Hover reveals the detail popover; a click pins it open the same way past
 * hover, so a touch device (no hover) can still reach it, and it stays open
 * long enough to actually read on desktop too. Escape and an outside click
 * dismiss the pin. Reuses `.share-popover`'s anchored-popover shape
 * (Card.tsx) rather than inventing a second popover language.
 */

import { useEffect, useRef, useState } from "react";

const SIZE = 30;
const STROKE = 3;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

interface Props {
  cardsRead: number;
  goal: number;
}

export function DailyGoalRing({ cardsRead, goal }: Props) {
  const [hovering, setHovering] = useState(false);
  const [pinned, setPinned] = useState(false);
  const open = hovering || pinned;
  const wrapRef = useRef<HTMLDivElement>(null);

  const progress = goal > 0 ? Math.min(cardsRead / goal, 1) : 0;
  const met = goal > 0 && cardsRead >= goal;
  const remaining = Math.max(goal - cardsRead, 0);

  useEffect(() => {
    if (!pinned) return;
    const onPointer = (e: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setPinned(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPinned(false);
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
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      <button
        type="button"
        className="daily-goal-ring"
        data-met={met}
        aria-expanded={open}
        aria-label={`Daily goal: ${cardsRead} of ${goal} cards read today`}
        onClick={() => setPinned((p) => !p)}
      >
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden="true">
          <circle
            className="daily-goal-track"
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            strokeWidth={STROKE}
            fill="none"
          />
          <circle
            className="daily-goal-progress"
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            strokeWidth={STROKE}
            fill="none"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE * (1 - progress)}
            strokeLinecap="round"
            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          />
        </svg>
      </button>

      {open ? (
        <div className="share-popover daily-goal-popover" role="status" onClick={(e) => e.stopPropagation()}>
          <span className="daily-goal-popover-head">
            {cardsRead} / {goal} cards today
          </span>
          <span className="daily-goal-popover-body">
            {met
              ? "Goal reached — keep going or come back tomorrow."
              : `${remaining} more to hit today's goal.`}
          </span>
        </div>
      ) : null}
    </div>
  );
}
