"use client";

/**
 * Dedicated Share Space for viewing and interacting with a shared card.
 *
 * Layout:
 * - Left rail: Standard Sidebar (navigates back to home/views).
 * - Center shell: Shows the shared card, plus an action to load more cards from the same topic.
 * - Right rail: ShareTopicRail, which highlights details, curriculum, and follow action for this topic.
 * - Guest integration: Guest users are served gracefully and prompted with the GuestNotice / signup flow.
 */

import { useCallback, useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import { MotionConfig } from "framer-motion";

import { api, type Card as CardModel, type Topic } from "@/lib/api";
import { getReducedMotion, subscribeReducedMotion } from "@/lib/motionPreference";
import { topicHue } from "@/lib/topicColor";
import { Card } from "@/components/Card";
import { CardSkeleton, ErrorNotice } from "@/components/FeedStates";
import { CustomCursor } from "@/components/CustomCursor";
import { FocusToggle } from "@/components/FocusToggle";
import { GuestNotice } from "@/components/GuestNotice";
import { ShareTopicRail } from "@/components/ShareTopicRail";
import { Sidebar, type ShellView } from "@/components/Sidebar";

interface PageProps {
  params: Promise<{ cardId: string }>;
}

export default function ShareCardPage({ params }: PageProps) {
  const { cardId } = use(params);
  const router = useRouter();

  const [card, setCard] = useState<CardModel | null>(null);
  const [topic, setTopic] = useState<Topic | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [moreCards, setMoreCards] = useState<CardModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seen, setSeen] = useState<Set<string>>(new Set());
  const [focusMode, setFocusMode] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    setReducedMotion(getReducedMotion());
    return subscribeReducedMotion(() => setReducedMotion(getReducedMotion()));
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [fetchedCard, userTopics] = await Promise.all([
        api.getCard(cardId),
        api.topics().catch(() => [] as Topic[]),
      ]);
      setCard(fetchedCard);
      setTopics(userTopics);
      const matched = userTopics.find((t) => t.id === fetchedCard.topic_id) ?? null;
      setTopic(matched);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load card");
    } finally {
      setLoading(false);
    }
  }, [cardId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const loadMoreTopicCards = async () => {
    if (!card || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await api.feed(undefined, [card.topic_id]);
      const fresh = page.cards.filter((c) => c.id !== card.id);
      setMoreCards(fresh);
    } catch (err) {
      console.error("Failed to load more cards:", err);
    } finally {
      setLoadingMore(false);
    }
  };

  const handleFollowed = (newTopic: Topic) => {
    setTopics((current) => [...current.filter((t) => t.id !== newTopic.id), newTopic]);
    if (card && newTopic.id === card.topic_id) {
      setTopic(newTopic);
    }
  };

  const handleNavigate = (v: ShellView) => {
    router.push(`/?view=${v}`);
  };

  const markSeen = useCallback((id: string) => {
    setSeen((prev) => new Set(prev).add(id));
  }, []);

  const unmarkSeen = useCallback((id: string) => {
    setSeen((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const topicName = topic?.display_name || card?.subtopic_title || "Topic";
  const accentHue = card ? topicHue(card.topic_id, topic?.accent_hue) : undefined;
  const isFollowing = Boolean(topic || (card && topics.some((t) => t.id === card.topic_id)));

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <CustomCursor />
      <GuestNotice />
      <div className="app-grid" data-focused={focusMode}>
        {focusMode ? (
          <div className="rail-left" aria-hidden="true" />
        ) : (
          <Sidebar
            onReset={() => router.push("/")}
            onRefresh={() => void loadData()}
            view="feed"
            onNavigate={handleNavigate}
          />
        )}

        <div className="shell">
          <main className="track">
            <div className="share-space-header">
              <span className="share-space-badge">Shared Knowledge Card</span>
            </div>

            {loading ? (
              <>
                <CardSkeleton />
                <CardSkeleton />
              </>
            ) : null}

            {error ? <ErrorNotice message={error} onRetry={() => void loadData()} /> : null}

            {card ? (
              <>
                <Card
                  key={card.id}
                  card={card}
                  topicName={topicName}
                  accentHue={accentHue}
                  seen={seen.has(card.id)}
                  onSeen={markSeen}
                  onUnseen={unmarkSeen}
                  isHero={false}
                />

                {/* Inline explore more cards from this topic */}
                {moreCards.length > 0 ? (
                  <div className="share-more-thread">
                    <div className="station">
                      <span className="station-name">More from {topicName}</span>
                      <span className="station-count">{moreCards.length}</span>
                    </div>
                    {moreCards.map((c) => (
                      <Card
                        key={c.id}
                        card={c}
                        topicName={topicName}
                        accentHue={accentHue}
                        seen={seen.has(c.id)}
                        onSeen={markSeen}
                        onUnseen={unmarkSeen}
                        isHero={c.is_hero}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="share-explore-divider">
                    <span className="share-explore-line" aria-hidden="true" />
                    <button
                      type="button"
                      className="share-explore-trigger"
                      onClick={() => void loadMoreTopicCards()}
                      disabled={loadingMore}
                    >
                      {loadingMore ? "Loading more cards…" : `Explore more cards from ${topicName}`}
                    </button>
                    <span className="share-explore-line" aria-hidden="true" />
                  </div>
                )}
              </>
            ) : null}
          </main>
        </div>

        {focusMode ? (
          <>
            <div className="rail-right" aria-hidden="true" />
            <FocusToggle focused onToggle={() => setFocusMode(false)} />
          </>
        ) : card ? (
          <ShareTopicRail
            topicId={card.topic_id}
            topicName={topicName}
            accentHue={accentHue}
            following={isFollowing}
            onFollowed={handleFollowed}
            onEnterFocus={() => setFocusMode(true)}
          />
        ) : (
          <div className="rail-right" />
        )}
      </div>
    </MotionConfig>
  );
}
