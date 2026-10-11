"use client";

/**
 * Redesigned TopicStatsModal:
 * - Clean, space-efficient header with inline quick actions (color swatch, follow/unfollow).
 * - High-impact Mastery & Progress Gauge (difficulty badge, overall completion %, cards seen/total).
 * - Interactive Tier Quiz Cards (Beginner, Intermediate, Advanced with unlock states & take quiz CTA).
 * - Clean 4-stat engagement bar (likes, saves, notes, shares).
 * - Interactive Curriculum Roadmap tree.
 *
 * A tierless topic (a survey or a one-shot, ADR-0106) has no tiers to show: one
 * mastery quiz across the whole topic, and its subtopics in one list.
 */

import { useEffect, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";

import { isTierless } from "@spoin/shared/enums";

import { api, type Difficulty, type SubtopicProgress, type TopicStats } from "@/lib/api";
import { defaultTopicHue, NO_TOPIC_COLOR } from "@/lib/topicColor";
import { CheckIcon, HeartIcon, BookmarkIcon, NoteIcon, ShareIcon } from "./icons";
import { QuizModal } from "./QuizModal";
import { SpoinWave } from "./SpoinWave";

interface Props {
  topicId: string;
  topicName: string;
  onClose: () => void;
  onFollow?: () => void | Promise<void>;
  following?: boolean;
  onUnfollow?: () => void | Promise<void>;
  onProgressChanged?: (topicId: string) => void;
  accentHue?: number | null;
  onColorChanged?: (hue: number | null) => void;
  topicIndex?: number;
}

const HUE_PRESETS = [355, 25, 45, 90, 150, 200, 230, 280];

const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  beginner: "Beginner",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

const TIERS: { key: Difficulty; label: string; desc: string }[] = [
  { key: "beginner", label: "Beginner Tier", desc: "Core concepts & fundamentals" },
  { key: "intermediate", label: "Intermediate Tier", desc: "Real-world design & trade-offs" },
  { key: "advanced", label: "Advanced Tier", desc: "Internals, optimization & mastery" },
];

const TIER_ORDER: Difficulty[] = ["beginner", "intermediate", "advanced"];

export function TopicStatsModal({
  topicId,
  topicName,
  onClose,
  onFollow,
  following = false,
  onUnfollow,
  onProgressChanged,
  accentHue,
  onColorChanged,
  topicIndex,
}: Props) {
  const [stats, setStats] = useState<TopicStats | null>(null);
  const [subtopics, setSubtopics] = useState<SubtopicProgress[] | null>(null);
  const [quiz, setQuiz] = useState<Difficulty | "mastery" | null>(null);
  const [unfollowing, setUnfollowing] = useState(false);
  const [confirmingUnfollow, setConfirmingUnfollow] = useState(false);

  const handleUnfollow = async () => {
    if (unfollowing || !onUnfollow) return;
    setUnfollowing(true);
    try {
      await onUnfollow();
    } finally {
      setUnfollowing(false);
    }
  };

  const loadStats = () => {
    void api.topicStats(topicId).then(setStats);
  };

  const selectHue = (hue: number) => {
    void api.setTopicColor(topicId, hue).then((topic) => onColorChanged?.(topic.accent_hue));
  };

  useEffect(loadStats, [topicId]);
  useEffect(() => {
    void api.topicCurriculum(topicId).then((c) => setSubtopics(c.subtopics));
  }, [topicId]);

  const onQuizGraded = () => {
    loadStats();
    onProgressChanged?.(topicId);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  const totalCardsInTopic = subtopics ? subtopics.reduce((acc, s) => acc + s.total_cards, 0) : 0;
  const totalCardsSeenInTopic = subtopics ? subtopics.reduce((acc, s) => acc + s.seen_cards, 0) : 0;
  const completedSubtopicsCount = subtopics ? subtopics.filter((s) => s.covered).length : 0;
  const tierless = stats !== null && isTierless(stats.scope);

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-panel modal-panel-wide topic-stats-modal-redesign"
        role="dialog"
        aria-modal="true"
        aria-label={`${topicName} details`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Streamlined Header */}
        <div className="topic-stats-head">
          <div className="topic-stats-title-col">
            <div className="topic-stats-title-row">
              <h2 className="topic-stats-title">{topicName}</h2>
              {stats?.mastered ? (
                <span className="topic-stats-badge-mastered mono">Mastered</span>
              ) : null}
            </div>
            {subtopics && subtopics.length > 0 ? (
              <span className="topic-stats-subtitle mono">
                {subtopics.length} subtopics · {totalCardsInTopic} total cards
              </span>
            ) : null}
          </div>

          <div className="topic-stats-head-actions">
            {onFollow !== undefined ? (
              <button
                type="button"
                className="topic-stats-follow-btn mono"
                disabled={following}
                onClick={() => void onFollow()}
              >
                {following ? "Following" : "+ Follow"}
              </button>
            ) : null}

            {onUnfollow !== undefined ? (
              confirmingUnfollow ? (
                <div className="topic-stats-unfollow-confirm">
                  <button
                    type="button"
                    className="topic-stats-confirm-yes mono"
                    disabled={unfollowing}
                    onClick={() => void handleUnfollow()}
                  >
                    {unfollowing ? "…" : "Confirm Unfollow"}
                  </button>
                  <button
                    type="button"
                    className="topic-stats-confirm-no mono"
                    onClick={() => setConfirmingUnfollow(false)}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="topic-stats-unfollow-btn mono"
                  onClick={() => setConfirmingUnfollow(true)}
                  title="Unfollow topic"
                >
                  Unfollow
                </button>
              )
            ) : null}

            <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
              ×
            </button>
          </div>
        </div>

        {/* Color Palette Row */}
        {onColorChanged !== undefined ? (
          <div className="topic-color-bar">
            <span className="topic-color-label mono">Accent Hue:</span>
            <div className="topic-color-swatches" role="group" aria-label="Topic accent color">
              <button
                type="button"
                className="modal-color-swatch modal-color-swatch-none"
                data-active={accentHue === NO_TOPIC_COLOR}
                aria-label="No color — follow the theme"
                onClick={() => selectHue(NO_TOPIC_COLOR)}
              />
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
          <div className="modal-loading">
            <SpoinWave variant="inline" caption="Loading topic data…" />
          </div>
        ) : (
          <div className="topic-stats-body">
            {/* Top Overview Cards */}
            <div className="topic-stats-overview-grid" data-tierless={tierless}>
              {tierless ? null : (
                <div className="topic-overview-card">
                  <span className="overview-card-label mono">Current Tier</span>
                  <span className="overview-card-value">{DIFFICULTY_LABEL[stats.current_difficulty]}</span>
                  <span className="overview-card-hint mono">
                    {stats.tier_quiz_passed[TIER_ORDER.indexOf(stats.current_difficulty)]
                      ? "Tier Quiz Passed ✓"
                      : "Quiz Incomplete"}
                  </span>
                </div>
              )}

              <div className="topic-overview-card">
                <span className="overview-card-label mono">Topic Coverage</span>
                <span className="overview-card-value">{Math.round(stats.coverage * 100)}%</span>
                <div className="overview-card-meter-bar">
                  <div
                    className="overview-card-meter-fill"
                    style={{ width: `${Math.round(stats.coverage * 100)}%` }}
                  />
                </div>
              </div>

              <div className="topic-overview-card">
                <span className="overview-card-label mono">Cards Studied</span>
                <span className="overview-card-value">
                  {totalCardsSeenInTopic} <span className="overview-card-total">/ {totalCardsInTopic}</span>
                </span>
                <span className="overview-card-hint mono">
                  {completedSubtopicsCount} of {subtopics?.length ?? 0} subtopics completed
                </span>
              </div>
            </div>

            {tierless ? (
              <MasteryQuizSection stats={stats} onStart={() => setQuiz("mastery")} />
            ) : (
              <TierQuizSection stats={stats} onStart={setQuiz} />
            )}

            {/* Engagement Metrics Bar */}
            <div className="topic-stats-engagement-bar">
              <div className="engagement-stat-cell">
                <HeartIcon />
                <span className="stat-value">{stats.likes}</span>
                <span className="stat-label mono">Likes</span>
              </div>
              <div className="engagement-stat-cell">
                <BookmarkIcon />
                <span className="stat-value">{stats.saves}</span>
                <span className="stat-label mono">Saves</span>
              </div>
              <div className="engagement-stat-cell">
                <NoteIcon />
                <span className="stat-value">{stats.notes}</span>
                <span className="stat-label mono">Notes</span>
              </div>
              <div className="engagement-stat-cell">
                <ShareIcon />
                <span className="stat-value">{stats.shares}</span>
                <span className="stat-label mono">Shares</span>
              </div>
            </div>

            {/* Interactive Curriculum Roadmap */}
            <div className="curriculum-tree-section">
              <div className="curriculum-tree-head">
                <span className="curriculum-tree-title mono">Curriculum Roadmap</span>
                {subtopics ? (
                  <span className="curriculum-tree-count mono">
                    {completedSubtopicsCount} / {subtopics.length} completed
                  </span>
                ) : null}
              </div>

              {subtopics === null ? (
                <div className="modal-loading">
                  <SpoinWave variant="inline" caption="Loading roadmap…" />
                </div>
              ) : (
                <div className="curriculum-tree-root">
                  {tierless ? (
                    <div className="curriculum-tree-tier" data-passed={stats.mastered}>
                      <div className="curriculum-tree-branches">
                        <div className="curriculum-tree-trunk-line" aria-hidden="true" />
                        <SubtopicLeaves subtopics={subtopics} />
                      </div>
                    </div>
                  ) : null}
                  {tierless ? null : TIER_ORDER.map((tier, tierIdx) => {
                    const tierSubtopics = subtopics.filter((s) => s.difficulty === tier);
                    if (tierSubtopics.length === 0) return null;
                    const tierPassed = stats.tier_quiz_passed[tierIdx] ?? false;
                    const tierCoveredCount = tierSubtopics.filter((s) => s.covered).length;
                    const tierTotalSeen = tierSubtopics.reduce((acc, s) => acc + s.seen_cards, 0);
                    const tierTotalCards = tierSubtopics.reduce((acc, s) => acc + s.total_cards, 0);
                    const tierProgress = tierTotalCards > 0 ? tierTotalSeen / tierTotalCards : 0;
                    const isCurrentTier = stats.current_difficulty === tier;

                    return (
                      <div
                        key={tier}
                        className="curriculum-tree-tier"
                        data-current={isCurrentTier}
                        data-passed={tierPassed}
                      >
                        {/* Tier Root Node */}
                        <div className="curriculum-tree-tier-node">
                          <div
                            className="curriculum-tier-indicator"
                            data-passed={tierPassed}
                            data-current={isCurrentTier}
                          >
                            {tierPassed ? (
                              <span className="tier-check-icon">✓</span>
                            ) : (
                              <span className="tier-number-badge">{tierIdx + 1}</span>
                            )}
                          </div>
                          <div className="curriculum-tier-info">
                            <span className="curriculum-tier-name">{DIFFICULTY_LABEL[tier]} Tier</span>
                            <span className="curriculum-tier-meta mono">
                              {tierCoveredCount} of {tierSubtopics.length} subtopics • {Math.round(tierProgress * 100)}%
                            </span>
                          </div>
                          {tierPassed ? (
                            <span className="curriculum-tier-status-pill passed mono">Mastered</span>
                          ) : isCurrentTier ? (
                            <span className="curriculum-tier-status-pill active mono">Active</span>
                          ) : null}
                        </div>

                        {/* Branch Trunk & Subtopic Leaf Nodes */}
                        <div className="curriculum-tree-branches">
                          <div className="curriculum-tree-trunk-line" aria-hidden="true" />
                          <SubtopicLeaves subtopics={tierSubtopics} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {quiz !== null ? (
        <QuizModal
          topicId={topicId}
          topicName={topicName}
          difficulty={quiz === "mastery" ? undefined : quiz}
          onClose={() => setQuiz(null)}
          onGraded={onQuizGraded}
        />
      ) : null}
    </div>,
    document.body,
  );
}

/** One certification quiz per tier, unlocked one tier at a time. */
function TierQuizSection({
  stats,
  onStart,
}: {
  stats: TopicStats;
  onStart: (difficulty: Difficulty) => void;
}) {
  return (
    <div className="topic-quizzes-section">
      <div className="topic-section-header">
        <span className="topic-section-title mono">Tier Certification Quizzes</span>
        <span className="topic-section-subtitle mono">Requires 80% coverage in tier</span>
      </div>

      <div className="topic-quizzes-grid">
        {TIERS.map(({ key, label, desc }, i) => {
          const passed = stats.tier_quiz_passed[i] ?? false;
          const isCurrent = stats.current_difficulty === key;
          const canTake = isCurrent && stats.quiz_unlocked;

          return (
            <div
              key={key}
              className="topic-quiz-card"
              data-passed={passed}
              data-current={isCurrent}
            >
              <div className="topic-quiz-card-head">
                <div className="topic-quiz-card-title-row">
                  <span className="topic-quiz-badge mono">Level {i + 1}</span>
                  {passed ? (
                    <span className="topic-quiz-status passed mono">✓ Passed</span>
                  ) : isCurrent ? (
                    <span className="topic-quiz-status active mono">Active</span>
                  ) : (
                    <span className="topic-quiz-status locked mono">Locked</span>
                  )}
                </div>
                <span className="topic-quiz-card-name">{label}</span>
                <p className="topic-quiz-card-desc">{desc}</p>
              </div>

              <div className="topic-quiz-card-footer">
                {passed ? (
                  <button
                    type="button"
                    className="topic-quiz-action-btn passed mono"
                    onClick={() => onStart(key)}
                  >
                    Retake Quiz
                  </button>
                ) : isCurrent ? (
                  <button
                    type="button"
                    className="topic-quiz-action-btn active mono"
                    disabled={!stats.quiz_unlocked}
                    onClick={() => onStart(key)}
                  >
                    {stats.quiz_unlocked ? "Start Quiz →" : "Reach 80% to Unlock"}
                  </button>
                ) : (
                  <span className="topic-quiz-locked-note mono">Complete Level {i} First</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** A tierless topic's one quiz: every subtopic, every difficulty. */
function MasteryQuizSection({ stats, onStart }: { stats: TopicStats; onStart: () => void }) {
  return (
    <div className="topic-quizzes-section">
      <div className="topic-section-header">
        <span className="topic-section-title mono">Mastery Quiz</span>
        <span className="topic-section-subtitle mono">Requires 80% coverage in every subtopic</span>
      </div>

      <div className="topic-quizzes-grid" data-tierless="true">
        <div className="topic-quiz-card" data-passed={stats.mastered} data-current={!stats.mastered}>
          <div className="topic-quiz-card-head">
            <div className="topic-quiz-card-title-row">
              <span className="topic-quiz-badge mono">Whole topic</span>
              {stats.mastered ? (
                <span className="topic-quiz-status passed mono">✓ Passed</span>
              ) : stats.quiz_unlocked ? (
                <span className="topic-quiz-status active mono">Active</span>
              ) : (
                <span className="topic-quiz-status locked mono">Locked</span>
              )}
            </div>
            <span className="topic-quiz-card-name">Mastery Quiz</span>
            <p className="topic-quiz-card-desc">One quiz across every subtopic</p>
          </div>

          <div className="topic-quiz-card-footer">
            <button
              type="button"
              className={`topic-quiz-action-btn ${stats.mastered ? "passed" : "active"} mono`}
              disabled={!stats.mastered && !stats.quiz_unlocked}
              onClick={onStart}
            >
              {stats.mastered ? "Retake Quiz" : stats.quiz_unlocked ? "Start Quiz →" : "Reach 80% to Unlock"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** A subtopic per leaf: the cards seen against the cards written. */
function SubtopicLeaves({ subtopics }: { subtopics: SubtopicProgress[] }) {
  return (
    <div className="curriculum-tree-leaves">
      {subtopics.map((s) => {
        const isComplete = s.covered;
        const inProgress = !s.covered && s.seen_cards > 0;
        const pct = Math.min(s.coverage, 1) * 100;

        return (
          <div
            key={s.subtopic_id}
            className="curriculum-leaf-node"
            data-status={isComplete ? "complete" : inProgress ? "in-progress" : "unstarted"}
          >
            {/* Branch Elbow Connector */}
            <div className="curriculum-branch-elbow" aria-hidden="true" />

            {/* Subtopic Status Dot */}
            <div
              className="curriculum-leaf-dot"
              data-status={isComplete ? "complete" : inProgress ? "in-progress" : "unstarted"}
            >
              {isComplete ? (
                <svg viewBox="0 0 16 16" className="leaf-check-svg">
                  <path
                    d="M3.5 8.5l3 3L12.5 4.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              ) : inProgress ? (
                <span className="leaf-pulse-dot" />
              ) : null}
            </div>

            {/* Subtopic Card Box */}
            <div className="curriculum-leaf-card">
              <div className="curriculum-leaf-header">
                <span className="curriculum-leaf-title">{s.title}</span>
                <span className="curriculum-leaf-cards mono">
                  {s.total_cards === 0 ? "generating" : `${s.seen_cards}/${s.total_cards}`}
                </span>
              </div>
              <div className="curriculum-leaf-meter-wrap">
                <div className="curriculum-leaf-meter">
                  <div
                    className="curriculum-leaf-fill"
                    data-complete={isComplete}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="curriculum-leaf-pct mono">{Math.round(pct)}%</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
