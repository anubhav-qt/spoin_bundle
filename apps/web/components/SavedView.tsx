"use client";

/**
 * "Revisit" — the user's personal shelf of saved (bookmarked) knowledge cards.
 *
 * F6 (v1 finish line): this used to be a bespoke 2-column tile grid with a
 * click-to-open card overlay. It is now the SAME vertical reading list as
 * `LikedView` / `NotesView` — same masthead, search, sort, topic filter, undo
 * wiring, and full `Card` rendering — because there was no product reason for
 * "Revisit" to look different from the other two collections. ADR-0072 records
 * dropping the grid (it partially supersedes ADR-0046, which had listed "Saved's
 * tile grid and overlay" as page-specific vocabulary to keep). The eventual
 * shared `CollectionView` extraction is task 0034.
 *
 * Performance contract (same as the feed): no LLM calls, no generation. Purely
 * a retrieval + presentation surface (`GET /cards/saved`).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";

import { api, type SavedCard, type Topic } from "@/lib/api";
import { engagement } from "@/lib/engagement";
import { bookmarkedStore } from "@/lib/engagementState";
import { useRefreshEffect } from "@/lib/refresh";
import { explicitTopicHue, topicHue } from "@/lib/topicColor";
import { offerUndo } from "@/lib/undo";
import { Card } from "./Card";
import { BookmarkIcon, HomeIcon } from "./icons";

type SortKey = "recent" | "oldest" | "topic" | "difficulty";

const SORT_LABELS: Record<SortKey, string> = {
  recent: "RECENT",
  oldest: "OLDEST",
  topic: "TOPIC",
  difficulty: "DIFFICULTY",
};

interface Props {
  /** Whether this view is the one currently on screen — see
   *  `useRefreshEffect`'s docstring on why an invalidation while hidden must
   *  not run this view's refetch synchronously. */
  active?: boolean;
  /** Followed topics, used to look up accent hues for topic filter chips. */
  topics: Topic[];
  /** Navigate back to the feed when the CTA is clicked in the empty state. */
  onNavigateHome: () => void;
}

export function SavedView({ topics, onNavigateHome, active = true }: Props) {
  const [rows, setRows] = useState<SavedCard[] | null>(null);
  const [error, setError] = useState(false);
  const [activeTopicId, setActiveTopicId] = useState<string | undefined>(undefined);
  const [sort, setSort] = useState<SortKey>("recent");
  const [search, setSearch] = useState("");
  const [seenIds, setSeenIds] = useState<Set<string>>(new Set());
  const handleSeen = useCallback((id: string) => {
    setSeenIds((s) => (s.has(id) ? s : new Set(s).add(id)));
  }, []);
  const handleUnseen = useCallback((id: string) => {
    setSeenIds((s) => {
      if (!s.has(id)) return s;
      const next = new Set(s);
      next.delete(id);
      return next;
    });
  }, []);
  // Consumed once by the very next "saved" invalidation, so this view's own
  // unbookmark (which invalidates "saved" synchronously) doesn't force a
  // loading-skeleton flash on top of a removal it already reflected. An
  // invalidation from elsewhere (bookmarking in the feed) still refetches.
  const skipNextRefreshRef = useRef(false);

  // Mirrors `rows` so `handleUnbookmarked` reads it synchronously rather than
  // from inside a `setRows` updater — `offerUndo` calls `setState` on the
  // unrelated `UndoToast`, and an updater can run during render, which throws
  // "Cannot update a component while rendering a different component".
  const rowsRef = useRef<SavedCard[] | null>(null);
  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

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
        const data = await api.savedCards(topicId, sortKey ?? sort);
        setRows(data);
        // Server-authoritative seen state (ADR-0010) — merged in, not replacing
        // local state, so a card marked read this session whose write hasn't
        // round-tripped doesn't flicker back to unseen.
        setSeenIds((prev) => {
          const next = new Set(prev);
          for (const row of data) if (row.card.seen) next.add(row.card.id);
          return next;
        });
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

  useRefreshEffect(
    "saved",
    () => {
      if (skipNextRefreshRef.current) {
        skipNextRefreshRef.current = false;
        return;
      }
      void load(activeTopicId, sort);
    },
    active,
  );

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

  const savedTopics = useMemo(() => {
    if (!rows) return [];
    const seen = new Map<string, { id: string; name: string }>();
    for (const r of rows) {
      if (!seen.has(r.card.topic_id)) {
        seen.set(r.card.topic_id, { id: r.card.topic_id, name: r.topic_name });
      }
    }
    return Array.from(seen.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [rows]);

  const handleUnbookmarked = useCallback((cardId: string) => {
    // Optimistic removal + a 5-second undo that re-bookmarks and re-inserts the
    // captured row (a fresh `card_bookmark` row server-side, created_at resets —
    // the delete-now-undo-by-redo tradeoff, see lib/undo.ts). Reads `rowsRef`,
    // not a `setRows` updater, so `offerUndo` runs as a plain call here.
    const current = rowsRef.current;
    if (!current) return;
    const removed = current.find((r) => r.card.id === cardId);
    if (!removed) return;

    skipNextRefreshRef.current = true;
    setRows((cur) => (cur ? cur.filter((r) => r.card.id !== cardId) : cur));

    offerUndo({
      label: "Removed from Revisit",
      onUndo: () => {
        skipNextRefreshRef.current = true;
        // Write through so a Card mounted elsewhere for this card_id (the feed)
        // also flips back to bookmarked — see lib/engagementState.ts.
        bookmarkedStore.set(removed.card.id, true);
        engagement.record(removed.card.id, "bookmark");
        setRows((cur) => {
          if (!cur) return [removed];
          if (cur.some((r) => r.card.id === removed.card.id)) return cur;
          return [removed, ...cur];
        });
      },
    });
  }, []);

  const handleTopicFilter = (topicId: string | undefined) => {
    setActiveTopicId(topicId);
    setSearch("");
  };

  const totalCards = rows?.length ?? 0;
  const topicCount = savedTopics.length;

  // ── Loading ──────────────────────────────────────────────────────────────
  if (rows === null && !error) {
    return (
      <div className="collection-view saved-view">
        <div className="collection-header">
          <p className="collection-eyebrow">REVISIT</p>
          <p className="collection-title">Keep it here. Come back later.</p>
        </div>
        <div className="collection-list">
          {[1, 2, 3].map((i) => (
            <div key={i} className="collection-skeleton-card" aria-hidden="true">
              <div className="liked-skeleton-meta collection-skeleton-bar" />
              <div className="liked-skeleton-title collection-skeleton-bar" />
              <div className="liked-skeleton-body collection-skeleton-bar" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="collection-view saved-view">
        <div className="collection-header">
          <p className="collection-eyebrow">REVISIT</p>
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

  // ── Empty (nothing saved, no filter) ─────────────────────────────────────
  if (totalCards === 0 && !activeTopicId && !search) {
    return (
      <div className="collection-view saved-view">
        <div className="collection-header">
          <p className="collection-eyebrow">REVISIT</p>
          <p className="collection-title">Keep it here. Come back later.</p>
        </div>
        <div className="collection-state">
          <pre className="collection-state-ascii" aria-hidden="true">{`
  \u{1F516}  ·  ·  ·  ·  ·
  ·  ·  ·  ·  ·  ·
  ·  ·  ·  ·  ·  ·`}</pre>
          <p className="collection-state-head">NOTHING SAVED YET</p>
          <p className="collection-state-body">
            Save a card when you want to come back to it.
            <br />
            It&apos;ll live here.
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

  // ── Main view ────────────────────────────────────────────────────────────
  return (
    <div className="collection-view saved-view">
      <div className="collection-header">
        <p className="collection-eyebrow">REVISIT</p>
        <p className="collection-title">Keep it here. Come back later.</p>
      </div>

      <p className="collection-meta">
        {totalCards === 1 ? "1 SAVED CARD" : `${totalCards} SAVED CARDS`}
        {topicCount > 0 ? ` · ${topicCount} ${topicCount === 1 ? "TOPIC" : "TOPICS"}` : ""}
      </p>

      <hr className="collection-rule" />

      <div className="collection-controls">
        <input
          id="saved-search"
          type="search"
          className="collection-search"
          placeholder="Search saved cards…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search saved cards"
        />
        <div className="collection-pill-row" role="group" aria-label="Sort order">
          {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
            <button
              key={key}
              type="button"
              className="collection-pill"
              data-active={sort === key}
              onClick={() => setSort(key)}
              aria-pressed={sort === key}
            >
              {SORT_LABELS[key]}
            </button>
          ))}
        </div>
      </div>

      {savedTopics.length > 1 ? (
        <div className="collection-filters" role="group" aria-label="Filter by topic">
          <button
            type="button"
            className="collection-chip"
            data-selected={!activeTopicId}
            onClick={() => handleTopicFilter(undefined)}
          >
            ALL
          </button>
          {savedTopics.map((t) => {
            const hue = explicitTopicHue(hueByTopicId[t.id]);
            return (
              <button
                key={t.id}
                type="button"
                className="collection-chip"
                data-selected={activeTopicId === t.id}
                onClick={() => handleTopicFilter(t.id)}
                style={hue !== null ? ({ "--topic-hue": hue } as React.CSSProperties) : undefined}
              >
                {t.name.toUpperCase()}
              </button>
            );
          })}
        </div>
      ) : null}

      {visible.length === 0 ? (
        <p className="collection-note">
          {search ? `No saved cards match "${search}".` : "No saved cards in this topic."}
        </p>
      ) : null}

      <div className="collection-list">
        <AnimatePresence initial={false}>
          {visible.map((row) => (
            <Card
              key={row.card.id}
              card={row.card}
              topicName={row.topic_name}
              accentHue={topicHue(row.card.topic_id, hueByTopicId[row.card.topic_id])}
              seen={seenIds.has(row.card.id)}
              onSeen={handleSeen}
              onUnseen={handleUnseen}
              isHero={false}
              initialBookmarked
              onUnbookmarked={handleUnbookmarked}
            />
          ))}
        </AnimatePresence>
      </div>

      {visible.length > 0 ? (
        <div className="collection-footer" aria-hidden="true">
          <span className="collection-footer-icon"><BookmarkIcon filled /></span>
          <span className="collection-footer-label">
            {visible.length} {visible.length === 1 ? "card" : "cards"} saved
          </span>
        </div>
      ) : null}
    </div>
  );
}
