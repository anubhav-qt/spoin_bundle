"use client";

/**
 * The app's first modal (ADR-0015). Detailed per-topic stats: progress fields
 * plus engagement counts (likes/saves/notes/shares — ask-AI excluded, per
 * instruction, since it isn't a comprehension/ownership signal the way the
 * other four are).
 *
 * Rendered via a portal into `document.body`, not in place. This component
 * is mounted from TopicsProgressBox, which lives inside `.rail-right` — a
 * `position: sticky` element with its own `overflow-y: auto` scroll. Sticky
 * and fixed elements always create a stacking context (CSS Position spec),
 * so a `.modal-overlay` nested there is still stacked *within* `.rail-right`'s
 * context rather than at the document root: card titles and other positioned
 * content elsewhere in the tree (`.station`'s sticky headers, `.notice`'s
 * `z-index: 2`) could end up painting through it depending on compositor
 * layer order, `z-index: 100` notwithstanding. A portal makes `.modal-overlay`
 * an actual direct child of `<body>`, sidestepping the ancestor entirely
 * instead of trying to out-layer it with `transform`/`will-change` hacks.
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api, type Difficulty, type TopicStats } from "@/lib/api";
import { CheckIcon, HeartIcon, BookmarkIcon, NoteIcon, ShareIcon } from "./icons";

interface Props {
  topicId: string;
  topicName: string;
  onClose: () => void;
}

const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  beginner: "Beginner",
  intermediate: "Intermediate",
  advanced: "Advanced",
};
const TIERS: { key: Difficulty; label: string }[] = [
  { key: "beginner", label: "Beginner quiz" },
  { key: "intermediate", label: "Intermediate quiz" },
  { key: "advanced", label: "Advanced quiz" },
];

export function TopicStatsModal({ topicId, topicName, onClose }: Props) {
  const [stats, setStats] = useState<TopicStats | null>(null);

  useEffect(() => {
    void api.topicStats(topicId).then(setStats);
  }, [topicId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The thread scrolls at the window/body level (no inner scroll container),
  // so without this the feed keeps scrolling right underneath an open modal.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`${topicName} progress`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title">{topicName}</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>

        {stats === null ? (
          <p className="modal-loading mono">Loading…</p>
        ) : (
          <>
            <div className="modal-progress-row">
              <span className="mono">{DIFFICULTY_LABEL[stats.current_difficulty]}</span>
              <span className="mono">{Math.round(stats.coverage * 100)}% coverage</span>
              {stats.mastered ? <span className="modal-badge">Mastered</span> : null}
            </div>

            <div className="modal-tiers">
              {TIERS.map(({ key, label }, i) => (
                <span key={key} className="modal-tier" data-passed={stats.tier_quiz_passed[i] ?? false}>
                  <CheckIcon />
                  {label}
                </span>
              ))}
            </div>

            <div className="modal-engagement">
              <div className="modal-engagement-stat">
                <HeartIcon />
                <span>{stats.likes}</span>
                <span className="mono">likes</span>
              </div>
              <div className="modal-engagement-stat">
                <BookmarkIcon />
                <span>{stats.saves}</span>
                <span className="mono">saves</span>
              </div>
              <div className="modal-engagement-stat">
                <NoteIcon />
                <span>{stats.notes}</span>
                <span className="mono">notes</span>
              </div>
              <div className="modal-engagement-stat">
                <ShareIcon />
                <span>{stats.shares}</span>
                <span className="mono">shares</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
