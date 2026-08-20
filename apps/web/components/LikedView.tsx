"use client";

/**
 * The user's personal shelf of liked knowledge cards.
 *
 * Modeled closely on NotesView — same loading/error/empty pattern, same Card
 * reuse, same "presentation-only seen state" stance (liking a card from this
 * view does not advance progression). The distinctive pieces are:
 *
 *   - Topic filter pills (server-side, one GET per change)
 *   - Client-side text search across title + summary
 *   - Sort control (recent / oldest / topic / difficulty)
 *   - Unlike interaction: optimistic removal with Framer Motion exit animation
 *
 * Performance contract (same as the feed): no LLM calls, no generation.
 * This is purely a retrieval + presentation surface.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";

import { api, type LikedCard, type Topic } from "@/lib/api";
import { engagement } from "@/lib/engagement";
import { topicHue } from "@/lib/topicColor";
import { Card } from "./Card";
import { HeartIcon, HomeIcon } from "./icons";

type SortKey = "recent" | "oldest" | "topic" | "difficulty";

const SORT_LABELS: Record<SortKey, string> = {
  recent: "RECENT",
  oldest: "OLDEST",
  topic: "TOPIC",
  difficulty: "DIFFICULTY",
};

interface Props {
  /** Followed topics, used to look up accent hues for topic filter chips. */
  topics: Topic[];
  /** Navigate back to the feed when the CTA is clicked in the empty state. */
  onNavigateHome: () => void;
}

export function LikedView({ topics, onNavigateHome }: Props) {
  const [rows, setRows] = useState<LikedCard[] | null>(null);
  const [error, setError] = useState(false);
  const [activeTopicId, setActiveTopicId] = useState<string | undefined>(undefined);
  const [sort, setSort] = useState<SortKey>("recent");
  const [search, setSearch] = useState("");
  const [seenIds, setSeenIds] = useState<Set<string>>(new Set());

  // Build a lookup of topicId → accent_hue from the followed-topics list.
  const hueByTopicId = useMemo(
    () => Object.fromEntries(topics.map((t) => [t.id, t.accent_hue])),
    [topics],
  );

  const load = useCallback(
    async (topicId?: string, sortKey?: SortKey) => {
      setError(false);
      setRows(null);
      try {
        await engagement.whenIdle();
        const data = await api.likedCards(topicId, sortKey ?? sort);
        setRows(data);
      } catch {
        setError(true);
      }
    },
    [sort],
  );

  useEffect(() => {
    void load(activeTopicId, sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTopicId, sort]);

  // Client-side search filter over the already-fetched rows.
  const visible = useMemo(() => {
    if (!rows) return [];
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.card.title.toLowerCase().includes(q) ||
        r.card.summary.toLowerCase().includes(q) ||
        r.topic_name.toLowerCase().includes(q),
    );
  }, [rows, search]);

  // Derive unique topics present in the liked collection for the filter bar.
  const likedTopics = useMemo(() => {
    if (!rows) return [];
    const seen = new Map<string, { id: string; name: string }>();
    for (const r of rows) {
      if (!seen.has(r.card.topic_id)) {
        seen.set(r.card.topic_id, { id: r.card.topic_id, name: r.topic_name });
      }
    }
    return Array.from(seen.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [rows]);

  const handleUnliked = useCallback((cardId: string) => {
    // Optimistically remove from local collection after unlike.
    setRows((current) => current?.filter((r) => r.card.id !== cardId) ?? current);
  }, []);

  const handleTopicFilter = (topicId: string | undefined) => {
    setActiveTopicId(topicId);
    setSearch(""); // Clear search when switching topic filters.
  };

  const handleSort = (key: SortKey) => {
    setSort(key);
  };

  const totalCards = rows?.length ?? 0;
  const topicCount = likedTopics.length;

  // --------------------------------------------------------------------------
  // Loading state
  // --------------------------------------------------------------------------
  if (rows === null && !error) {
    return (
      <div className="collection-view liked-view">
        <div className="collection-header">
          <p className="collection-eyebrow">LIKED</p>
          <p className="collection-title">Things worth remembering.</p>
        </div>
        <div className="liked-view-list">
          {[1, 2, 3].map((i) => (
            <div key={i} className="liked-skeleton" aria-hidden="true">
              <div className="liked-skeleton-meta collection-skeleton-bar" />
              <div className="liked-skeleton-title collection-skeleton-bar" />
              <div className="liked-skeleton-body collection-skeleton-bar" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // --------------------------------------------------------------------------
  // Error state
  // --------------------------------------------------------------------------
  if (error) {
    return (
      <div className="collection-view liked-view">
        <div className="collection-header">
          <p className="collection-eyebrow">LIKED</p>
        </div>
        <div className="collection-state">
          <p className="collection-state-head">COULDN&apos;T LOAD YOUR SHELF</p>
          <p className="collection-state-body">Something went sideways.</p>
          <button
            type="button"
            className="collection-action collection-cta"
            onClick={() => void load(activeTopicId, sort)}
          >
            TRY AGAIN
          </button>
        </div>
      </div>
    );
  }

  // --------------------------------------------------------------------------
  // Empty state (no likes at all, no active filter)
  // --------------------------------------------------------------------------
  if (totalCards === 0 && !activeTopicId && !search) {
    return (
      <div className="collection-view liked-view">
        <div className="collection-header">
          <p className="collection-eyebrow">LIKED</p>
          <p className="collection-title">Things worth remembering.</p>
        </div>
        <div className="collection-state">
          <pre className="collection-state-ascii" aria-hidden="true">{`
  ♡  ·  ·  ·  ·  ·
  ·  ·  ·  ·  ·  ·
  ·  ·  ·  ·  ·  ·`}</pre>
          <p className="collection-state-head">NOTHING LIKED YET</p>
          <p className="collection-state-body">
            When something makes you stop scrolling<br />
            and think <em>&ldquo;I want to remember this&rdquo;</em>,<br />
            it&apos;ll live here.
          </p>
          <button
            type="button"
            className="collection-action collection-cta"
            onClick={onNavigateHome}
          >
            <span className="collection-action-icon"><HomeIcon /></span>
            EXPLORE CARDS
          </button>
        </div>
      </div>
    );
  }

  // --------------------------------------------------------------------------
  // Main view
  // --------------------------------------------------------------------------
  return (
    <div className="collection-view liked-view">
      {/* Header */}
      <div className="collection-header">
        <p className="collection-eyebrow">LIKED</p>
        <p className="collection-title">Things worth remembering.</p>
      </div>

      {/* Collection metadata */}
      <p className="collection-meta">
        {totalCards === 1 ? "1 LIKED CARD" : `${totalCards} LIKED CARDS`}
        {topicCount > 0 ? ` · ${topicCount} ${topicCount === 1 ? "TOPIC" : "TOPICS"}` : ""}
      </p>

      <hr className="collection-rule" />

      {/* Search + Sort controls */}
      <div className="collection-controls">
        <input
            id="liked-search"
            type="search"
            className="collection-search"
            placeholder="Search liked cards…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          aria-label="Search liked cards"
        />
        <div className="collection-pill-row" role="group" aria-label="Sort order">
          {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
            <button
              key={key}
              type="button"
              className="collection-pill"
              data-active={sort === key}
              onClick={() => handleSort(key)}
              aria-pressed={sort === key}
            >
              {SORT_LABELS[key]}
            </button>
          ))}
        </div>
      </div>

      {/* Topic filter pills */}
      {likedTopics.length > 1 ? (
        <div className="collection-filters" role="group" aria-label="Filter by topic">
          <button
            type="button"
            className="collection-chip"
            data-selected={!activeTopicId}
            onClick={() => handleTopicFilter(undefined)}
          >
            ALL
          </button>
          {likedTopics.map((t) => {
            const hue = hueByTopicId[t.id];
            return (
              <button
                key={t.id}
                type="button"
                className="collection-chip"
                data-selected={activeTopicId === t.id}
                onClick={() => handleTopicFilter(t.id)}
                style={
                  hue !== undefined && hue !== null
                    ? ({ "--topic-hue": hue } as React.CSSProperties)
                    : undefined
                }
              >
                {t.name.toUpperCase()}
              </button>
            );
          })}
        </div>
      ) : null}

      {/* Empty state for filtered/searched result */}
      {visible.length === 0 ? (
        <p className="collection-note">
          {search
            ? `No liked cards match "${search}".`
            : "No liked cards in this topic."}
        </p>
      ) : null}

      {/* Card list */}
      <div className="liked-view-list">
        <AnimatePresence initial={false}>
          {visible.map((row) => {
            return (
              <Card
                key={row.card.id}
                card={row.card}
                topicName={row.topic_name}
                accentHue={topicHue(row.card.topic_id, hueByTopicId[row.card.topic_id])}
                seen={seenIds.has(row.card.id)}
                onSeen={(cardId) => setSeenIds((s) => new Set(s).add(cardId))}
                onUnseen={(cardId) => {
                  setSeenIds((s) => {
                    const next = new Set(s);
                    next.delete(cardId);
                    return next;
                  });
                }}
                isHero={false}
                initialLiked
                onUnliked={handleUnliked}
              />
            );
          })}
        </AnimatePresence>
      </div>

      {/* Heart watermark at bottom — quiet editorial touch */}
      {visible.length > 0 ? (
        <div className="collection-footer" aria-hidden="true">
          <span className="collection-footer-icon"><HeartIcon filled /></span>
          <span className="collection-footer-label">
            {visible.length} {visible.length === 1 ? "card" : "cards"} liked
          </span>
        </div>
      ) : null}
    </div>
  );
}
