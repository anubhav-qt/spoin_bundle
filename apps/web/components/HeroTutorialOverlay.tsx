"use client";

/**
 * ADR-0035: a one-time spotlight pointing at a hero card's real mark-as-read
 * button. Four dimming strips surround a cutout matching the target's live
 * bounding rect — there is no element covering the target itself, so a click
 * that lands in the cutout reaches the real button underneath and fires its
 * own handler unmodified. A click on any strip is swallowed (stops here,
 * never reaches whatever was under it) and dismisses the tutorial.
 */

import { useEffect, useState, type MouseEvent, type RefObject } from "react";
import { createPortal } from "react-dom";

interface Rect {
  top: number;
  left: number;
  right: number;
  bottom: number;
}

interface Props {
  targetRef: RefObject<HTMLElement | null>;
  onDismiss: () => void;
}

export function HeroTutorialOverlay({ targetRef, onDismiss }: Props) {
  const [rect, setRect] = useState<Rect | null>(null);

  useEffect(() => {
    const update = () => {
      const el = targetRef.current;
      if (el === null) return;
      const box = el.getBoundingClientRect();
      setRect({ top: box.top, left: box.left, right: box.right, bottom: box.bottom });
    };

    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [targetRef]);

  if (rect === null) return null;

  const swallow = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    onDismiss();
  };

  const pad = 6;
  const hole = {
    top: rect.top - pad,
    left: rect.left - pad,
    right: rect.right + pad,
    bottom: rect.bottom + pad,
  };

  return createPortal(
    <div className="hero-tutorial" aria-hidden="false">
      <div
        className="hero-tutorial-strip"
        style={{ top: 0, left: 0, right: 0, height: Math.max(hole.top, 0) }}
        onClick={swallow}
      />
      <div
        className="hero-tutorial-strip"
        style={{ top: hole.bottom, left: 0, right: 0, bottom: 0 }}
        onClick={swallow}
      />
      <div
        className="hero-tutorial-strip"
        style={{ top: hole.top, height: hole.bottom - hole.top, left: 0, width: Math.max(hole.left, 0) }}
        onClick={swallow}
      />
      <div
        className="hero-tutorial-strip"
        style={{ top: hole.top, height: hole.bottom - hole.top, left: hole.right, right: 0 }}
        onClick={swallow}
      />

      <div className="hero-tutorial-ring" style={{ top: hole.top, left: hole.left, width: hole.right - hole.left, height: hole.bottom - hole.top }} />

      <div
        className="hero-tutorial-callout"
        style={{ top: hole.bottom + 12, left: Math.max(hole.right - 220, 12) }}
      >
        <span className="hero-tutorial-arrow" aria-hidden="true">
          ↑
        </span>
        <p className="mono">Tap here to mark this card as read</p>
      </div>
    </div>,
    document.body,
  );
}
