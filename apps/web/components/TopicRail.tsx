"use client";

/**
 * The topic filter — name-only pills. Progress/quiz-readiness detail used to
 * live here too, but that congested a single chip; it now lives in
 * TopicsProgressBox instead (ADR-0015). This component's only job is
 * filtering the feed.
 *
 * The rail scrolls horizontally (mouse wheel / trackpad / drag), but nothing
 * on screen signals that or gives a click target for it — so it also renders
 * a left/right arrow pair, shown only once there's actually somewhere to
 * scroll to, and disabled at each end rather than hidden, so the pair
 * doesn't jump around as you reach the edges.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { Topic } from "@/lib/api";

interface Props {
  topics: Topic[];
  selected: string[];
  onToggle: (topicId: string) => void;
}

export function TopicRail({ topics, selected, onToggle }: Props) {
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
      <button
        type="button"
        className="topic-rail-arrow"
        data-side="left"
        aria-label="Scroll topics left"
        disabled={!canScrollLeft}
        onClick={() => scrollBy(-1)}
      >
        <svg viewBox="0 0 24 24">
          <path d="M15 6l-6 6 6 6" />
        </svg>
      </button>

      <div className="topic-rail" role="group" aria-label="Filter by topic" ref={railRef}>
        {topics.map((topic) => (
          <button
            key={topic.id}
            className="topic-chip"
            data-selected={selected.includes(topic.id)}
            aria-pressed={selected.includes(topic.id)}
            onClick={() => onToggle(topic.id)}
            type="button"
          >
            {/* Always the user's own name for the topic, never the canonical one. */}
            {topic.display_name}
          </button>
        ))}
      </div>

      <button
        type="button"
        className="topic-rail-arrow"
        data-side="right"
        aria-label="Scroll topics right"
        disabled={!canScrollRight}
        onClick={() => scrollBy(1)}
      >
        <svg viewBox="0 0 24 24">
          <path d="M9 6l6 6-6 6" />
        </svg>
      </button>
    </div>
  );
}
