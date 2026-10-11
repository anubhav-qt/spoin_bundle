"use client";

/**
 * The topic filter — a horizontal strip of chips, one per followed topic.
 *
 * Each chip shows the user's name for the topic plus a compact status glance:
 * coverage percent, current difficulty tier, and a hair-thin meter. That
 * detail lived only in `TopicsProgressBox` between ADR-0015 and the ADR-0064
 * design canvas; the canvas puts it back on the filter chip (see ADR-0015's
 * forward note). Clicking a chip still only toggles the feed filter — the
 * quiz/progression actions stay one level deeper in `TopicsProgressBox`.
 *
 * The strip scrolls by wheel/trackpad/drag, but a plain mouse has no
 * horizontal axis — so it also renders a minimal chevron pair (borderless,
 * quiet, no circular chrome), shown only when there's actually somewhere to
 * scroll and fully hidden at each end so nothing overlays the first/last
 * chip at rest.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { isTierless } from "@spoin/shared/enums";

import type { Difficulty, Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";

interface Props {
  topics: Topic[];
  selected: string[];
  onToggle: (topicId: string) => void;
  progress: Record<string, TopicProgress>;
}

const DIFFICULTY_ABBR: Record<Difficulty, string> = {
  beginner: "BEG",
  intermediate: "INT",
  advanced: "ADV",
};

export function TopicRail({ topics, selected, onToggle, progress }: Props) {
  const railRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const updateArrows = useCallback(() => {
    const node = railRef.current;
    if (node === null) return;
    setCanScrollLeft(node.scrollLeft > 1);
    setCanScrollRight(node.scrollLeft + node.clientWidth < node.scrollWidth - 1);
  }, []);

  useEffect(() => {
    const node = railRef.current;
    if (node === null) return;

    updateArrows();
    node.addEventListener("scroll", updateArrows, { passive: true });

    const observer = new ResizeObserver(updateArrows);
    observer.observe(node);

    return () => {
      node.removeEventListener("scroll", updateArrows);
      observer.disconnect();
    };
  }, [updateArrows, topics.length]);

  const scrollBy = (direction: 1 | -1) => {
    const node = railRef.current;
    if (node === null) return;
    node.scrollBy({ left: direction * node.clientWidth * 0.7, behavior: "smooth" });
  };

  return (
    <div className="topic-rail-wrap">
      {canScrollLeft ? (
        <button
          type="button"
          className="topic-rail-arrow"
          data-side="left"
          aria-label="Scroll topics left"
          onClick={() => scrollBy(-1)}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
      ) : null}

      <div className="topic-rail" role="group" aria-label="Filter by topic" ref={railRef}>
        {topics.map((topic) => {
          const isSelected = selected.includes(topic.id);
          const coverage = progress[topic.id]?.coverage ?? 0;
          const pct = Math.round(Math.min(Math.max(coverage, 0), 1) * 100);
          const difficulty = progress[topic.id]?.currentDifficulty ?? "beginner";

          return (
            <button
              key={topic.id}
              className="topic-chip"
              data-selected={isSelected}
              aria-pressed={isSelected}
              onClick={() => onToggle(topic.id)}
              type="button"
            >
              {/* Always the user's own name for the topic, never the canonical one. */}
              <span className="topic-chip-name">{topic.display_name}</span>
              <span className="topic-chip-meta">
                <span>{pct}%</span>
                {isTierless(topic.scope) ? null : <span>{DIFFICULTY_ABBR[difficulty]}</span>}
              </span>
              <span className="topic-chip-track" aria-hidden="true">
                <span style={{ width: `${pct}%` }} />
              </span>
            </button>
          );
        })}
      </div>

      {canScrollRight ? (
        <button
          type="button"
          className="topic-rail-arrow"
          data-side="right"
          aria-label="Scroll topics right"
          onClick={() => scrollBy(1)}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
      ) : null}
    </div>
  );
}
