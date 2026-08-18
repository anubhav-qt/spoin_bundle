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
import { AnimatePresence } from "framer-motion";

import { api, type Card as CardModel, type Topic } from "@/lib/api";
import { engagement } from "@/lib/engagement";
import { groupIntoStations, stationKey, stationKind } from "@/lib/stations";
import { topicHue } from "@/lib/topicColor";
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
  const loadingMoreRef = useRef(false);
  // Guards against React StrictMode's dev-only double-invoked mount effect
  // (and any other overlapping calls, e.g. a fast topic-filter change) firing
  // two concurrent `loadPage(true)` calls. The feed endpoint's stratified
  // selection isn't guaranteed identical between two back-to-back calls, so
  // without this, whichever response lands second fully replaces `cards` —
  // any card present in the first response but missing from the second
  // unmounts under AnimatePresence and plays Card.tsx's exit animation, which
  // reads as a random, unexplained "swipe right" on a card that was never
  // touched. Only the response matching the most recently issued request id
  // is ever applied.
  const loadRequestId = useRef(0);

  const topicName = useCallback(
    (topicId: string) => topics.find((t) => t.id === topicId)?.display_name ?? "",
    [topics],
  );

  const topicAccentHue = useCallback(
    (topicId: string) => {
      const index = topics.findIndex((t) => t.id === topicId);
      if (index === -1) return undefined;
      return topicHue(topicId, topics[index].accent_hue, index);
    },
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

      const requestId = ++loadRequestId.current;

      try {
        const page = await api.feed(position.current, selected);
        // A newer loadPage call was issued while this one was in flight —
        // its result (or the one still pending) is authoritative instead.
        if (requestId !== loadRequestId.current) return;

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
        if (requestId !== loadRequestId.current) return;
        setError(cause instanceof Error ? cause.message : "Unknown error");
      } finally {
        if (requestId === loadRequestId.current) {
          setLoading(false);
          setLoadingMore(false);
          loadingMoreRef.current = false;
        }
      }
    },
    [selected],
  );

  useEffect(() => {
    void loadPage(true);
  }, [loadPage]);

  // -- infinite scroll -------------------------------------------------------
  // `loadingMore` is read via a ref, not a dependency: keeping it out of the
  // deps array means the observer is created once per exhausted/loading
  // transition and only reacts to real intersection changes. Depending on
  // `loadingMore` directly used to tear down and recreate the observer on
  // every fetch start/end, and IntersectionObserver fires its callback
  // immediately on `observe()` with the sentinel's current state — with the
  // generous 600px rootMargin, the sentinel is often still intersecting right
  // after a page loads, so the recreated observer would immediately fire a
  // second, spurious `loadPage` with no real user scroll behind it.
  useEffect(() => {
    const node = sentinel.current;
    if (node === null || exhausted || loading) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !loadingMoreRef.current) {
          loadingMoreRef.current = true;
          void loadPage(false);
        }
      },
      // Prefetch a screen early, so the next page is usually already there.
      { rootMargin: "600px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [exhausted, loading, loadPage]);

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
            {/* Only when exactly one topic is filtered (station kind is
                "subtopic") — the curriculum slot is genuinely new information
                there. In the mixed feed (kind "topic"), the topic name is
                already shown on every card's own head, so a station heading
                that just repeats it is dead weight, not orientation. */}
            {kind === "subtopic" ? (
              <div className="station">
                <span className="station-name">{station.label}</span>
                <span className="station-count">{station.cards.length}</span>
              </div>
            ) : null}

            <AnimatePresence initial={false}>
              {station.cards
                .map((card) => (
                  <Card
                    key={card.id}
                    card={card}
                    topicName={topicName(card.topic_id)}
                    accentHue={topicAccentHue(card.topic_id)}
                    seen={seen.has(card.id)}
                    onSeen={markSeen}
                    onUnseen={unmarkSeen}
                    // Server-owned (ADR-0017) — at most one true per subtopic.
                    // No client heuristic here anymore.
                    isHero={card.is_hero}
                  />
                ))}
            </AnimatePresence>
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
