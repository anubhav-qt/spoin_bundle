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

import { useEffect, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";

import { api, type Difficulty, type TopicStats } from "@/lib/api";
import { defaultTopicHue } from "@/lib/topicColor";
import { CheckIcon, HeartIcon, BookmarkIcon, NoteIcon, ShareIcon } from "./icons";
import { QuizModal } from "./QuizModal";

interface Props {
  topicId: string;
  topicName: string;
  onClose: () => void;
  /** Present only when opened from Discover, for a topic not yet followed —
   *  renders a Follow action in the modal instead of assuming the caller
   *  already knows the topic is followed. `/topics/{id}/stats` itself works
   *  fine with no UserTopicProgress row (defaults to 0% coverage, beginner
   *  tier), so this reuses the same modal rather than a separate "preview"
   *  component — the stats it shows are simply honestly empty for a topic
   *  the user hasn't started. */
  onFollow?: () => void | Promise<void>;
  following?: boolean;
  /** ADR-0034. Present only for an already-followed topic (there's no
   *  UserTopic row to color for a Discover preview) — omitted from Discover's
   *  call, same pattern as `onFollow` being absent there in reverse. */
  accentHue?: number | null;
  onColorChanged?: (hue: number | null) => void;
  /** This topic's position in the followed-topics list (subscription order)
   *  — feeds the same curated first-10 default `Feed.tsx` uses, so the
   *  swatch highlighted as "current" here matches what's actually rendered
   *  on the card. Omitted from Discover's call (no ordered membership yet). */
  topicIndex?: number;
}

/** 8 preset hues, evenly spaced — a discrete swatch picker (ThemePicker's
 *  pattern) rather than a continuous color wheel, since the actual rendered
 *  color is always derived from the active palette (ADR-0034), not this
 *  swatch's own color. */
const HUE_PRESETS = [355, 25, 45, 90, 150, 200, 230, 280];

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

export function TopicStatsModal({
  topicId,
  topicName,
  onClose,
  onFollow,
  following = false,
  accentHue,
  onColorChanged,
  topicIndex,
}: Props) {
  const [stats, setStats] = useState<TopicStats | null>(null);
  // The tier being quizzed, frozen at the moment the quiz opens — NOT read
  // live from `stats.current_difficulty` while the modal is open. A pass
  // advances that field via `loadStats` (below), and QuizModal keys its
  // fetch off its `difficulty` prop: if that prop tracked `stats` live, a
  // promotion mid-quiz would silently restart QuizModal against the newly
  // (and still-locked) next tier, wiping the results screen the user just
  // earned.
  const [quizDifficulty, setQuizDifficulty] = useState<Difficulty | null>(null);

  const loadStats = () => {
    void api.topicStats(topicId).then(setStats);
  };

  const selectHue = (hue: number) => {
    void api.setTopicColor(topicId, hue).then((topic) => onColorChanged?.(topic.accent_hue));
  };

  useEffect(loadStats, [topicId]);

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
        aria-label={`${topicName} details`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title">{topicName}</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>

        {onFollow !== undefined ? (
          <button
            type="button"
            className="modal-follow"
            disabled={following}
            onClick={() => void onFollow()}
          >
            {following ? "Following…" : "Follow this topic"}
          </button>
        ) : null}

        {onColorChanged !== undefined ? (
          <div className="modal-color-picker">
            <span className="modal-color-picker-label mono">Card color</span>
            <div className="modal-color-swatches" role="group" aria-label="Topic accent color">
              {HUE_PRESETS.map((hue) => (
                <button
                  key={hue}
                  type="button"
                  className="modal-color-swatch"
                  data-active={(accentHue ?? defaultTopicHue(topicId, topicIndex)) === hue}
                  style={{ "--swatch-hue": hue } as CSSProperties}
                  aria-label={`Set accent hue ${hue}`}
                  onClick={() => selectHue(hue)}
                />
              ))}
            </div>
          </div>
        ) : null}

        {stats === null ? (
          <p className="modal-loading mono">Loading…</p>
        ) : (
          <>
            <div className="modal-progress-row">
              <span className="mono">{DIFFICULTY_LABEL[stats.current_difficulty]}</span>
              <span className="mono">{Math.round(stats.coverage * 100)}% coverage</span>
              {stats.mastered ? <span className="modal-badge">Completed</span> : null}
            </div>

            <div className="modal-tiers">
              {TIERS.map(({ key, label }, i) => (
                <span key={key} className="modal-tier" data-passed={stats.tier_quiz_passed[i] ?? false}>
                  <CheckIcon />
                  {label}
                </span>
              ))}
            </div>

            <button
              type="button"
              className="modal-quiz"
              data-locked={!stats.quiz_unlocked}
              disabled={!stats.quiz_unlocked}
              onClick={() => setQuizDifficulty(stats.current_difficulty)}
            >
              {!stats.quiz_unlocked
                ? "Quiz locked — reach 80% coverage"
                : `Take the ${DIFFICULTY_LABEL[stats.current_difficulty]} quiz`}
            </button>

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

      {quizDifficulty !== null ? (
        <QuizModal
          topicId={topicId}
          topicName={topicName}
          difficulty={quizDifficulty}
          onClose={() => setQuizDifficulty(null)}
          onGraded={loadStats}
        />
      ) : null}
    </div>,
    document.body,
  );
}
