"use client";

/**
 * The user's personal bookshelf of saved knowledge cards.
 *
 * Deliberately distinct from LikedView's vertical list. Saved is a visual
 * library grid: compact tiles, 2 columns, browsable at a glance. Clicking
 * a tile opens the full Card in a portal overlay — "pull a book off the shelf."
 *
 * Design constraints (per product spec):
 *   - 2 columns everywhere (desktop, tablet, mobile — never a carousel)
 *   - Compact tiles: topic · difficulty · title · 2-line preview · bookmark
 *   - No large body text in the grid — these are browsing tiles, not reading
 *   - Border lifts to --line-strong on hover; background lifts to --bg-3
 *   - Framer Motion: AnimatePresence for tile exit; layout for grid reflow
 *
 * Performance contract: no LLM calls, no generation.
 * This is purely a retrieval + presentation surface (GET /cards/saved).
 */

import { createPortal } from "react-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

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

const DIFFICULTY_RANK: Record<string, number> = {
  beginner: 1,
  intermediate: 2,
  advanced: 3,
};

interface Props {
  /** Followed topics — used to look up accent hues for topic chips. */
  topics: Topic[];
  /** Navigate back to the feed from the empty state CTA. */
  onNavigateHome: () => void;
}

// ─── Tile ─────────────────────────────────────────────────────────────────────

interface TileProps {
  row: SavedCard;
  accentHue: number | null | undefined;
  onOpen: (row: SavedCard) => void;
}

function SavedTile({ row, accentHue, onOpen }: TileProps) {
  const { card, topic_name } = row;

  return (
    <motion.button
      type="button"
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.93, transition: { duration: 0.18 } }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="saved-tile"
      onClick={() => onOpen(row)}
      aria-label={`Open card: ${card.title}`}
      style={
        accentHue !== null && accentHue !== undefined
          ? ({ "--topic-hue": accentHue } as React.CSSProperties)
          : undefined
      }
    >
      {/* Topic + difficulty row */}
      <div className="saved-tile-head">
        <span className="saved-tile-topic">{topic_name.toUpperCase()}</span>
        <span className="saved-tile-difficulty" aria-label={card.difficulty}>
          {[1, 2, 3].map((step) => (
            <i key={step} data-on={step <= DIFFICULTY_RANK[card.difficulty]} />
          ))}
        </span>
      </div>

      {/* Title — the strongest element */}
      <h3 className="saved-tile-title">{card.title}</h3>

      {/* 2-line preview — browsing hint, not the full body */}
      <p className="saved-tile-preview">{card.summary}</p>

      {/* Footer: bookmark icon (filled = saved) */}
      <div className="saved-tile-footer" aria-hidden="true">
        <span className="saved-tile-bm">
          <BookmarkIcon filled />
        </span>
      </div>
    </motion.button>
  );
}

// ─── Card overlay portal ────────────────────────────────────────────────────

interface OverlayProps {
  row: SavedCard;
  accentHue: number | null | undefined;
  onClose: () => void;
  onUnbookmarked: (cardId: string) => void;
  seenIds: Set<string>;
  onSeen: (cardId: string) => void;
  onUnseen: (cardId: string) => void;
}

function SavedCardOverlay({
  row,
  accentHue,
  onClose,
  onUnbookmarked,
  seenIds,
  onSeen,
  onUnseen,
}: OverlayProps) {
  const backdropRef = useRef<HTMLDivElement>(null);

  // Dismiss on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleBackdrop = (e: React.MouseEvent) => {
    if (e.target === backdropRef.current) onClose();
  };

  return createPortal(
    <div
      ref={backdropRef}
      className="saved-overlay-backdrop"
      onClick={handleBackdrop}
      role="dialog"
      aria-modal="true"
      aria-label="Saved card"
    >
      <div className="saved-overlay-shell">
        <Card
          card={row.card}
          topicName={row.topic_name}
          accentHue={accentHue}
          seen={seenIds.has(row.card.id)}
          onSeen={onSeen}
          onUnseen={onUnseen}
          isHero={false}
          initialBookmarked
          onUnbookmarked={(cardId) => {
            onUnbookmarked(cardId);
            onClose();
          }}
        />
      </div>
    </div>,
    document.body,
  );
}

// ─── Main view ────────────────────────────────────────────────────────────────

export function SavedView({ topics, onNavigateHome }: Props) {
  const [rows, setRows] = useState<SavedCard[] | null>(null);
  const [error, setError] = useState(false);
  const [activeTopicId, setActiveTopicId] = useState<string | undefined>(undefined);
  const [sort, setSort] = useState<SortKey>("recent");
  const [search, setSearch] = useState("");
  const [openRow, setOpenRow] = useState<SavedCard | null>(null);
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
  // Set right when this view's own unbookmark already updated `rows`
  // locally -- see LikedView's identical guard for the full reasoning
  // (engagement.record's "unbookmark" branch invalidates "saved"
  // synchronously, which would otherwise force a visible refetch flash on
  // top of a removal this view already reflected).
  const skipNextRefreshRef = useRef(false);

  // Lookup: topicId → accent_hue from followed topics
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
        // Server-authoritative seen state (ADR-0010) -- merged in rather than
        // replacing local state so a card just marked read this session, whose
        // write hasn't round-tripped yet, doesn't flicker back to unseen.
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

  // Manual refresh, or an invalidation from elsewhere (bookmarking/unbookmarking
  // a card anywhere in the app) — re-fetches the current filter/sort without
  // needing a remount. Skipped once right after this view's own unbookmark.
  useRefreshEffect("saved", () => {
    if (skipNextRefreshRef.current) {
      skipNextRefreshRef.current = false;
      return;
    }
    void load(activeTopicId, sort);
  });

  // Client-side search across title + summary + topic name
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

  // Derive unique topics present in the saved collection for filter chips
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
    setRows((current) => {
      if (!current) return current;
      const removed = current.find((r) => r.card.id === cardId);
      if (!removed) return current;

      skipNextRefreshRef.current = true;
      offerUndo({
        label: "Removed from Saved",
        onUndo: () => {
          skipNextRefreshRef.current = true;
          // Write through so a Card mounted elsewhere for this same card_id
          // also flips back to bookmarked -- see lib/engagementState.ts.
          bookmarkedStore.set(removed.card.id, true);
          engagement.record(removed.card.id, "bookmark");
          setRows((cur) => {
            if (!cur) return [removed];
            if (cur.some((r) => r.card.id === removed.card.id)) return cur;
            return [removed, ...cur];
          });
        },
      });

      return current.filter((r) => r.card.id !== cardId);
    });
    setOpenRow(null);
  }, []);

  const handleTopicFilter = (topicId: string | undefined) => {
    setActiveTopicId(topicId);
    setSearch("");
  };

  const totalCards = rows?.length ?? 0;
  const topicCount = savedTopics.length;

  const openRowAccentHue =
    openRow ? topicHue(openRow.card.topic_id, hueByTopicId[openRow.card.topic_id]) : undefined;

  // ── Loading ──────────────────────────────────────────────────────────────
  if (rows === null && !error) {
    return (
      <div className="collection-view saved-view">
        <div className="collection-header">
          <p className="collection-eyebrow">SAVED</p>
          <p className="collection-title">Keep it here. Come back later.</p>
        </div>
        <div className="saved-skeleton-grid" aria-hidden="true">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="saved-skeleton-tile">
              <div className="saved-skeleton-meta collection-skeleton-bar" />
              <div className="saved-skeleton-title collection-skeleton-bar" />
              <div className="saved-skeleton-preview" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Error ─────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="collection-view saved-view">
        <div className="collection-header">
          <p className="collection-eyebrow">SAVED</p>
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

  // ── Empty state (no bookmarks at all) ─────────────────────────────────────
  if (totalCards === 0 && !activeTopicId && !search) {
    return (
      <div className="collection-view saved-view">
        <div className="collection-header">
          <p className="collection-eyebrow">SAVED</p>
          <p className="collection-title">Keep it here. Come back later.</p>
        </div>
        <div className="collection-state">
          <pre className="collection-state-ascii" aria-hidden="true">{`
  \u{1F516}  \u00B7  \u00B7  \u00B7  \u00B7  \u00B7
  \u00B7  \u00B7  \u00B7  \u00B7  \u00B7  \u00B7
  \u00B7  \u00B7  \u00B7  \u00B7  \u00B7  \u00B7`}</pre>
          <p className="collection-state-head">YOUR SHELF IS EMPTY</p>
          <p className="collection-state-body">
            Save cards you want to revisit.
            <br />
            They&apos;ll live here.
          </p>
          <button
            type="button"
            className="collection-action collection-cta"
            onClick={onNavigateHome}
          >
            <span className="collection-action-icon"><HomeIcon /></span>
            EXPLORE FEED
          </button>
        </div>
      </div>
    );
  }

  // ── Main view ─────────────────────────────────────────────────────────────
  return (
    <div className="collection-view saved-view">
      {/* Card overlay portal */}
      <AnimatePresence>
        {openRow !== null && (
          <SavedCardOverlay
            key={openRow.card.id}
            row={openRow}
            accentHue={openRowAccentHue}
            onClose={() => setOpenRow(null)}
            onUnbookmarked={handleUnbookmarked}
            seenIds={seenIds}
            onSeen={handleSeen}
            onUnseen={handleUnseen}
          />
        )}
      </AnimatePresence>

      {/* Header */}
      <div className="collection-header">
        <p className="collection-eyebrow">SAVED</p>
        <p className="collection-title">Keep it here. Come back later.</p>
      </div>

      {/* Collection metadata */}
      <p className="collection-meta">
        {totalCards === 1 ? "1 SAVED CARD" : `${totalCards} SAVED CARDS`}
        {topicCount > 0 ? ` \u00B7 ${topicCount} ${topicCount === 1 ? "TOPIC" : "TOPICS"}` : ""}
      </p>

      <hr className="collection-rule" />

      {/* Search + sort controls */}
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

      {/* Topic filter chips */}
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

      {/* Filter/search empty sub-state */}
      {visible.length === 0 ? (
        <p className="collection-note">
          {search
            ? `No saved cards match "${search}".`
            : "No saved cards in this topic."}
        </p>
      ) : null}

      {/* Grid */}
      <motion.div
        className="saved-grid"
        layout
        transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      >
        <AnimatePresence initial={false}>
          {visible.map((row) => (
            <SavedTile
              key={row.card.id}
              row={row}
              accentHue={topicHue(row.card.topic_id, hueByTopicId[row.card.topic_id])}
              onOpen={setOpenRow}
            />
          ))}
        </AnimatePresence>
      </motion.div>

      {/* Footer watermark */}
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
