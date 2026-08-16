"use client";

/**
 * Owns everything the three-column shell needs to share across columns: which
 * topics the user follows, their progress, and which are currently filtered to.
 *
 * This used to live inside Feed.tsx, back when the topic rail was part of the
 * feed's own masthead. Now the right rail's TopicRail and InsightsPanel both
 * need the same state, so it moved up one level. Feed itself keeps everything
 * that is purely about the card thread.
 */

import { useCallback, useEffect, useState } from "react";

import { api, type Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
import { Feed } from "./Feed";
import { FocusToggle } from "./FocusToggle";
import { RightRail } from "./RightRail";
import { Sidebar } from "./Sidebar";

function toTopicProgress(p: {
  coverage: number;
  quiz_unlocked: boolean;
  mastered: boolean;
  tier_quiz_passed: boolean[];
}): TopicProgress {
  return {
    coverage: p.coverage,
    quizUnlocked: p.quiz_unlocked,
    mastered: p.mastered,
    quizTiersPassed: p.tier_quiz_passed.filter(Boolean).length,
  };
}

export function AppShell() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [progress, setProgress] = useState<Record<string, TopicProgress>>({});
  const [selected, setSelected] = useState<string[]>([]);
  // Session-local, not server state: which cards have been marked seen so
  // far, so InsightsPanel can show a count that only grows once per card
  // even if a card gets marked seen more than once in a session.
  const [readCardIds, setReadCardIds] = useState<Set<string>>(new Set());
  // Hides both rails, leaving just the feed. Neither rail carries state
  // worth preserving across the toggle, so this is plain UI state — not
  // persisted, not lifted any further than it needs to be.
  const [focusMode, setFocusMode] = useState(false);

  const loadTopics = useCallback(async () => {
    const list = await api.topics();
    setTopics(list);

    const entries = await Promise.all(
      list.map(async (topic) => {
        const p = await api.progress(topic.id);
        return [topic.id, toTopicProgress(p)] as const;
      }),
    );
    setProgress(Object.fromEntries(entries));
  }, []);

  useEffect(() => {
    void loadTopics();
  }, [loadTopics]);

  const refreshProgress = useCallback(async (topicId: string) => {
    const p = await api.progress(topicId);
    setProgress((current) => ({ ...current, [topicId]: toTopicProgress(p) }));
  }, []);

  // Called when a card gets marked seen, so InsightsPanel's session count and
  // the topic's progress both reflect it immediately instead of only as of
  // the last full page load.
  const onCardSeen = useCallback(
    (cardId: string, topicId: string) => {
      setReadCardIds((current) => {
        if (current.has(cardId)) return current;
        const next = new Set(current).add(cardId);
        void refreshProgress(topicId);
        return next;
      });
    },
    [refreshProgress],
  );

  const toggleTopic = (topicId: string) => {
    setSelected((current) =>
      current.includes(topicId) ? current.filter((id) => id !== topicId) : [...current, topicId],
    );
  };

  // DiscoverBox calls this after a successful follow, so the newly-subscribed
  // topic shows up in the filter/progress box without a full reload.
  const onFollowed = useCallback(async (topic: Topic) => {
    setTopics((current) => (current.some((t) => t.id === topic.id) ? current : [...current, topic]));
    const p = await api.progress(topic.id);
    setProgress((current) => ({ ...current, [topic.id]: toTopicProgress(p) }));
  }, []);

  return (
    <div className="app-grid" data-focused={focusMode}>
      {/* Both rails keep reserving their grid track even when hidden — an
          empty spacer, not a removed column — so toggling focus mode never
          reflows the center column sideways. */}
      {focusMode ? <div className="rail-left" aria-hidden="true" /> : <Sidebar />}
      <div className="shell">
        <Feed topics={topics} selected={selected} onCardSeen={onCardSeen} />
      </div>
      {focusMode ? (
        <>
          <div className="rail-right" aria-hidden="true" />
          <FocusToggle focused onToggle={() => setFocusMode(false)} />
        </>
      ) : (
        <RightRail
          topics={topics}
          progress={progress}
          selected={selected}
          onToggle={toggleTopic}
          cardsRead={readCardIds.size}
          onFollowed={onFollowed}
          onEnterFocus={() => setFocusMode(true)}
        />
      )}
    </div>
  );
}
