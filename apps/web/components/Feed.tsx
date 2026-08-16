"use client";

/**
 * The center column: masthead and the card thread. The honest end states live
 * here too.
 *
 * Note what is NOT here: no ranking, no difficulty mixing, no seen-state rules,
 * no pagination arithmetic. This asks the API for a page and renders what comes
 * back. Every one of those decisions lives server-side so the React Native
 * client gets identical behaviour for free — if this file ever starts making
 * product decisions, that is the bug.
 *
 * `topics` and `selected` are owned by AppShell — the right rail's topic
 * filter needs the same state, so it lives one level up.
 *
 * The one local state that resembles a rule is `seen`: an optimistic set, so a
 * tapped card marks itself immediately. Engagement is eventually consistent by
 * design, and the UI must not read back its own writes.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, type Card as CardModel, type Topic } from "@/lib/api";
import { engagement } from "@/lib/engagement";
import { groupIntoStations, stationKey, stationKind } from "@/lib/stations";
import { Card } from "./Card";
import { CardSkeleton, DegradedNotice, EmptyFeed, EndOfFeed, ErrorNotice } from "./FeedStates";

interface Props {
  topics: Topic[];
  selected: string[];
  /** Called after a card is marked seen, so the caller can track session reads and refresh that topic's progress. */
  onCardSeen: (cardId: string, topicId: string) => void;
}

export function Feed({ topics, selected, onCardSeen }: Props) {
  const [cards, setCards] = useState<CardModel[]>([]);
  const [seen, setSeen] = useState<Set<string>>(new Set());

  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [degraded, setDegraded] = useState(false);
  const [exhausted, setExhausted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sentinel = useRef<HTMLDivElement>(null);
  const position = useRef<number | undefined>(undefined);

  const topicName = useCallback(
    (topicId: string) => topics.find((t) => t.id === topicId)?.display_name ?? "",
    [topics],
  );

  // Topic stations when the feed is mixed; subtopic stations when it is filtered
  // to exactly one topic, where the topic name would be identical on every
  // station and therefore useless.
  const kind = stationKind(selected);
  const stations = useMemo(
    () => groupIntoStations(cards, kind, topicName),
    [cards, kind, topicName],
  );

  useEffect(() => {
    engagement.start();
    return () => engagement.stop();
  }, []);

  // -- data -----------------------------------------------------------------
  const loadPage = useCallback(
    async (reset: boolean) => {
      if (reset) {
        setLoading(true);
        position.current = undefined;
      } else {
        setLoadingMore(true);
      }

      try {
        const page = await api.feed(position.current, selected);
        position.current = page.next_position;

        setCards((current) => {
          if (reset) return page.cards;
          // Belt and braces against a duplicate slipping through a slate refill.
          // A visibly repeated card is the most damaging feed bug there is.
          const known = new Set(current.map((c) => c.id));
          return [...current, ...page.cards.filter((c) => !known.has(c.id))];
        });

        setDegraded(page.degraded);
        setExhausted(page.exhausted);
        setError(null);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Unknown error");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [selected],
  );

  useEffect(() => {
    void loadPage(true);
  }, [loadPage]);

  // -- infinite scroll -------------------------------------------------------
  useEffect(() => {
    const node = sentinel.current;
    if (node === null || exhausted || loading) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !loadingMore) void loadPage(false);
      },
      // Prefetch a screen early, so the next page is usually already there.
      { rootMargin: "600px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [exhausted, loading, loadingMore, loadPage]);

  const markSeen = useCallback(
    (cardId: string) => {
      setSeen((current) => {
        if (current.has(cardId)) return current;
        return new Set(current).add(cardId);
      });
      const card = cards.find((c) => c.id === cardId);
      if (card !== undefined) onCardSeen(cardId, card.topic_id);
    },
    [cards, onCardSeen],
  );

  // Undoes the LOCAL, in-session indicator only — see the comment on Card's
  // `gotIt` handler. The event already sent and the server's SEEN state are
  // untouched.
  const unmarkSeen = useCallback((cardId: string) => {
    setSeen((current) => {
      if (!current.has(cardId)) return current;
      const next = new Set(current);
      next.delete(cardId);
      return next;
    });
  }, []);

  return (
    <>
      {/* Not sticky, deliberately — the wordmark already lives in the left
          nav, so this is just a one-line orientation cue that scrolls away
          with the rest of the thread rather than pinning a second banner. */}
      {kind === "subtopic" || seen.size > 0 ? (
        <p className="feed-intro">
          {seen.size > 0
            ? `${seen.size} read this session`
            : "One topic — following the curriculum"}
        </p>
      ) : null}

      <main className="track">
        {error !== null && cards.length === 0 ? (
          <ErrorNotice message={error} onRetry={() => void loadPage(true)} />
        ) : null}

        {loading ? (
          <>
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </>
        ) : null}

        {!loading && cards.length === 0 && error === null ? <EmptyFeed /> : null}

        {stations.map((station, index) => (
          <section key={stationKey(station, index)}>
            <div className="station">
              <span className="station-name">{station.label}</span>
              <span className="station-count">{station.cards.length}</span>
            </div>

            {station.cards.map((card) => (
              <Card
                key={card.id}
                card={card}
                topicName={topicName(card.topic_id)}
                seen={seen.has(card.id)}
                onSeen={markSeen}
                onUnseen={unmarkSeen}
              />
            ))}
          </section>
        ))}

        {loadingMore ? <CardSkeleton /> : null}
        {degraded && !loading ? <DegradedNotice /> : null}
        {exhausted && cards.length > 0 && !degraded ? <EndOfFeed /> : null}

        <div ref={sentinel} className="sentinel" />
      </main>
    </>
  );
}
