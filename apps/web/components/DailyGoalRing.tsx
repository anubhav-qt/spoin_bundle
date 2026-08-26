"use client";

/**
 * Small circular progress ring for `daily_card_goal`, in the rail's utility
 * strip alongside ThemePicker/FocusToggle. Shows how many cards were
 * completed against today's goal (`/profile/me/today`, ADR-0062's local-day
 * definition) without taking up permanent rail space the way a full progress
 * bar would.
 *
 * Hover reveals the detail popover; a click pins it open the same way past
 * hover, so a touch device (no hover) can still reach it, and it stays open
 * long enough to actually read on desktop too. Escape and an outside click
 * dismiss the pin. Reuses `.share-popover`'s anchored-popover shape
 * (Card.tsx) rather than inventing a second popover language.
 *
 * The popover itself is portaled to `document.body` and positioned via
 * `getBoundingClientRect()` rather than CSS-anchored inside `.daily-goal-
 * wrap` (`position: absolute`, as `.share-popover` normally is). The ring
 * lives inside `RightRail`'s own scrollable rail (`overflow-x: hidden`,
 * by design) on desktop/tablet, and inside `MobileTopBar` (`position:
 * fixed`, sitting directly above the scrolling feed) on a phone -- either
 * ancestor can clip or bury a CSS-anchored popover as the page scrolls.
 * `TopicDiscoveryModal` escapes the same way for the same reason.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

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
  // Viewport-relative coords for the portaled popover -- null until the
  // first layout pass after `open` flips true, so nothing renders at (0, 0)
  // for a frame before the real position is known.
  const [coords, setCoords] = useState<{ top: number; right: number } | null>(null);

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

  // Right-anchored to the ring's own right edge, matching the CSS-anchored
  // layout this replaces. `capture: true` on the scroll listener catches
  // scrolling on any ancestor (the feed, a scrollable rail), not just the
  // window itself -- scroll events don't bubble, only capture.
  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      const rect = wrapRef.current?.getBoundingClientRect();
      if (!rect) return;
      setCoords({ top: rect.bottom + 8, right: window.innerWidth - rect.right });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open]);

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

      {open && coords
        ? createPortal(
            <div
              className="share-popover daily-goal-popover"
              role="status"
              style={{ top: coords.top, right: coords.right }}
              onClick={(e) => e.stopPropagation()}
            >
              <span className="daily-goal-popover-head">
                {cardsRead} / {goal} cards today
              </span>
              <span className="daily-goal-popover-body">
                {met
                  ? "Goal reached — keep going or come back tomorrow."
                  : `${remaining} more to hit today's goal.`}
              </span>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
