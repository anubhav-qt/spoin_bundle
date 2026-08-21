"use client";

/**
 * "All my notes" (docs/tasks/0004-notes-in-one-place.md, part 2) — every
 * `CardNote` this user has written, newest edit first, rendered as full
 * `Card`s with the note editor expanded by default so it reads as a study
 * view rather than a bare list of card titles.
 *
 * Modeled on the unified collection surface (ADR-0046) alongside LikedView
 * and SavedView — sharing the same typography, controls, filtering, sorting,
 * loading skeletons, and empty states.
 *
 * Seen-state here is presentation-only: this view isn't part of the feed's
 * progression path, so "Got it" toggles just flip the icon locally rather
 * than round-tripping through engagement/progress like the feed does.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";

import { api, type NoteWithCard, type Topic } from "@/lib/api";
import { engagement } from "@/lib/engagement";
import { useRefreshEffect } from "@/lib/refresh";
import { topicHue } from "@/lib/topicColor";
import { Card } from "./Card";
import { HomeIcon, NoteIcon } from "./icons";

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
  /** Followed topics, used to look up accent hues for topic filter chips. */
  topics?: Topic[];
  /** Navigate back to the feed when the CTA is clicked in the empty state. */
  onNavigateHome?: () => void;
}

export function NotesView({ topics = [], onNavigateHome }: Props) {
  const [rows, setRows] = useState<NoteWithCard[] | null>(null);
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

  const load = useCallback(async () => {
    setError(false);
    setRows(null);
    try {
      await engagement.whenIdle();
      const data = await api.listNotes();
      setRows(data);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Manual refresh, or an invalidation from elsewhere (a note saved/deleted
  // from a card in the feed, say) — re-fetches without needing a remount.
  useRefreshEffect("notes", () => void load());

  // Derive unique topics present in the notes collection for the filter bar.
  const notesTopics = useMemo(() => {
    if (!rows) return [];
    const seen = new Map<string, { id: string; name: string }>();
    for (const r of rows) {
      if (!seen.has(r.card.topic_id)) {
        seen.set(r.card.topic_id, { id: r.card.topic_id, name: r.topic_name });
      }
    }
    return Array.from(seen.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [rows]);

  // Client-side search and topic filtering
  const filteredRows = useMemo(() => {
    if (!rows) return [];
    let list = rows;
    if (activeTopicId) {
      list = list.filter((r) => r.card.topic_id === activeTopicId);
    }
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (r) =>
          r.note.body.toLowerCase().includes(q) ||
          r.card.title.toLowerCase().includes(q) ||
          r.card.summary.toLowerCase().includes(q) ||
          r.topic_name.toLowerCase().includes(q),
      );
    }
    return list;
  }, [rows, activeTopicId, search]);

  // Sorting
  const visible = useMemo(() => {
    const list = [...filteredRows];
    switch (sort) {
      case "recent":
        return list.sort(
          (a, b) => new Date(b.note.updated_at).getTime() - new Date(a.note.updated_at).getTime(),
        );
      case "oldest":
        return list.sort(
          (a, b) => new Date(a.note.updated_at).getTime() - new Date(b.note.updated_at).getTime(),
        );
      case "topic":
        return list.sort((a, b) => a.topic_name.localeCompare(b.topic_name));
      case "difficulty":
        return list.sort(
          (a, b) =>
            (DIFFICULTY_RANK[a.card.difficulty] ?? 0) - (DIFFICULTY_RANK[b.card.difficulty] ?? 0),
        );
      default:
        return list;
    }
  }, [filteredRows, sort]);

  const onNoteChange = (cardId: string, body: string | null) => {
    if (body === null) {
      // A note cleared to empty deletes it — drop the row rather than leaving
      // a card with no note content sitting in a "notes" view.
      setRows((current) => current?.filter((row) => row.card.id !== cardId) ?? current);
    } else {
      setRows((current) =>
        current?.map((row) =>
          row.card.id === cardId
            ? { ...row, note: { ...row.note, body, updated_at: new Date().toISOString() } }
            : row,
        ) ?? current,
      );
    }
  };

  const handleTopicFilter = (topicId: string | undefined) => {
    setActiveTopicId(topicId);
    setSearch("");
  };

  const handleSort = (key: SortKey) => {
    setSort(key);
  };

  const totalNotes = rows?.length ?? 0;
  const topicCount = notesTopics.length;

  // --------------------------------------------------------------------------
  // Loading state
  // --------------------------------------------------------------------------
  if (rows === null && !error) {
    return (
      <div className="collection-view notes-view">
        <div className="collection-header">
          <p className="collection-eyebrow">NOTES</p>
          <p className="collection-title">Private. Only you can see these.</p>
        </div>
        <div className="notes-view-list">
          {[1, 2, 3].map((i) => (
            <div key={i} className="notes-skeleton" aria-hidden="true">
              <div className="notes-skeleton-meta collection-skeleton-bar" />
              <div className="notes-skeleton-title collection-skeleton-bar" />
              <div className="notes-skeleton-body collection-skeleton-bar" />
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
      <div className="collection-view notes-view">
        <div className="collection-header">
          <p className="collection-eyebrow">NOTES</p>
        </div>
        <div className="collection-state">
          <p className="collection-state-head">COULDN&apos;T LOAD YOUR NOTES</p>
          <p className="collection-state-body">Something went sideways.</p>
          <button
            type="button"
            className="collection-action collection-cta"
            onClick={() => void load()}
          >
            TRY AGAIN
          </button>
        </div>
      </div>
    );
  }

  // --------------------------------------------------------------------------
  // Empty state (no notes at all, no active filter/search)
  // --------------------------------------------------------------------------
  if (totalNotes === 0 && !activeTopicId && !search) {
    return (
      <div className="collection-view notes-view">
        <div className="collection-header">
          <p className="collection-eyebrow">NOTES</p>
          <p className="collection-title">Private. Only you can see these.</p>
        </div>
        <div className="collection-state">
          <pre className="collection-state-ascii" aria-hidden="true">{`
  ✎  ·  ·  ·  ·  ·
  ·  ·  ·  ·  ·  ·
  ·  ·  ·  ·  ·  ·`}</pre>
          <p className="collection-state-head">NO NOTES YET</p>
          <p className="collection-state-body">
            Tap the note icon on any card<br />
            to jot down your thoughts.<br />
            They&apos;ll live here.
          </p>
          {onNavigateHome && (
            <button
              type="button"
              className="collection-action collection-cta"
              onClick={onNavigateHome}
            >
              <span className="collection-action-icon"><HomeIcon /></span>
              EXPLORE CARDS
            </button>
          )}
        </div>
      </div>
    );
  }

  // --------------------------------------------------------------------------
  // Main view
  // --------------------------------------------------------------------------
  return (
    <div className="collection-view notes-view">
      {/* Header */}
      <div className="collection-header">
        <p className="collection-eyebrow">NOTES</p>
        <p className="collection-title">Private. Only you can see these.</p>
      </div>

      {/* Collection metadata */}
      <p className="collection-meta">
        {totalNotes === 1 ? "1 NOTE" : `${totalNotes} NOTES`}
        {topicCount > 0 ? ` · ${topicCount} ${topicCount === 1 ? "TOPIC" : "TOPICS"}` : ""}
      </p>

      <hr className="collection-rule" />

      {/* Search + Sort controls */}
      <div className="collection-controls">
        <input
          id="notes-search"
          type="search"
          className="collection-search"
          placeholder="Search notes…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search notes"
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
      {notesTopics.length > 1 ? (
        <div className="collection-filters" role="group" aria-label="Filter by topic">
          <button
            type="button"
            className="collection-chip"
            data-selected={!activeTopicId}
            onClick={() => handleTopicFilter(undefined)}
          >
            ALL
          </button>
          {notesTopics.map((t) => {
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
          {search ? `No notes match "${search}".` : "No notes in this topic."}
        </p>
      ) : null}

      {/* Card list */}
      <div className="notes-view-list">
        <AnimatePresence initial={false}>
          {visible.map((row) => (
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
              initialNoteOpen
              onNoteChange={onNoteChange}
            />
          ))}
        </AnimatePresence>
      </div>

      {/* Note watermark at bottom — quiet editorial touch */}
      {visible.length > 0 ? (
        <div className="collection-footer" aria-hidden="true">
          <span className="collection-footer-icon"><NoteIcon /></span>
          <span className="collection-footer-label">
            {visible.length} {visible.length === 1 ? "note" : "notes"} written
          </span>
        </div>
      ) : null}
    </div>
  );
}
