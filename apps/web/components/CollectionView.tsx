"use client";

/**
 * The one collection surface (ADR-0046): a filtered, searchable, sortable list
 * of a user's collected cards with a 5-second undo-on-remove window. LikedView,
 * SavedView ("Revisit") and NotesView are thin configs over this component
 * (task 0034). Before ADR-0072 removed Revisit's bespoke grid they had drifted
 * into three near-identical copies of everything below — the topic filter
 * chips, the loading / error / empty states, the search + sort row, the
 * `rowsRef` + `offerUndo` wiring, the `skipNextRefreshRef` guard, and the
 * server-authoritative `seen` merge.
 *
 * Performance contract (same as the feed): retrieval + presentation only — no
 * LLM calls, no generation.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AnimatePresence } from "framer-motion";

import { type Card as CardModel, type Topic } from "@/lib/api";
import { engagement } from "@/lib/engagement";
import { useRefreshEffect, type RefreshScope } from "@/lib/refresh";
import { explicitTopicHue, topicHue } from "@/lib/topicColor";
import { offerUndo } from "@/lib/undo";
import { Card } from "./Card";
import { HomeIcon } from "./icons";

export type CollectionSortKey = "recent" | "oldest" | "topic" | "difficulty";

const SORT_LABELS: Record<CollectionSortKey, string> = {
  recent: "RECENT",
  oldest: "OLDEST",
  topic: "TOPIC",
  difficulty: "DIFFICULTY",
};

/** Handed to a view's `cardProps` so its per-card remove / edit behaviour
 *  plugs into the shared undo + skip-next-refresh machinery. */
export interface CollectionRowOps<TRow> {
  /** Optimistically drop `cardId`, then offer a 5-second undo. `redo` runs the
   *  server-side re-create (re-like / re-bookmark / re-`PUT` the note) with the
   *  captured row; the shared code re-inserts it into the list afterwards. */
  removeWithUndo: (
    cardId: string,
    opts: { label: string; redo: (removed: TRow) => void | Promise<void> },
  ) => void;
  /** In-place patch of one row (NotesView's non-deleting note edit). */
  updateRow: (cardId: string, patch: (row: TRow) => TRow) => void;
}

export interface CollectionConfig<TRow> {
  scope: RefreshScope;
  /** Small-caps label above the title. */
  eyebrow: string;
  title: string;
  searchPlaceholder: string;
  searchAriaLabel: string;
  /** `[singular, plural]` for the "N LIKED CARDS" metadata line. */
  countNoun: [string, string];
  errorHead: string;
  /** One glyph for the empty-state ASCII block. */
  emptyGlyph: string;
  emptyHead: string;
  emptyBody: ReactNode;
  footerIcon: ReactNode;
  /** The footer reads "N cards <verb>" / "N notes <verb>". */
  footerVerb: string;
  /** `[singular, plural]` noun for the footer ("card" / "note"). */
  itemNoun: [string, string];
  /** Plural noun for the filtered-empty line ("liked cards" / "notes"). */
  filteredEmptyNoun: string;

  /** One fetch. Liked / Revisit pass `topicId` + `sort` to the server;
   *  Notes ignores both and filters + sorts client-side (`clientFilterSort`). */
  fetch: (topicId: string | undefined, sort: CollectionSortKey) => Promise<TRow[]>;
  card: (row: TRow) => CardModel;
  topicName: (row: TRow) => string;

  /** Notes: filter + sort in memory, fetch once. */
  clientFilterSort?: boolean;
  /** Extra client-side search predicate (Notes also matches the note body). */
  searchExtra?: (row: TRow, lowerQuery: string) => boolean;
  /** Client sort comparator — required when `clientFilterSort`. */
  sortRow?: (a: TRow, b: TRow, key: CollectionSortKey) => number;

  /** Per-card props threaded into the `Card` (initialLiked / onUnliked /
   *  initialNoteOpen / …). */
  cardProps: (
    row: TRow,
    ops: CollectionRowOps<TRow>,
  ) => {
    initialLiked?: boolean;
    onUnliked?: (cardId: string) => void;
    initialBookmarked?: boolean;
    onUnbookmarked?: (cardId: string) => void;
    initialNoteOpen?: boolean;
    onNoteChange?: (cardId: string, body: string | null) => void;
  };
}

interface Props<TRow> {
  config: CollectionConfig<TRow>;
  /** Whether this view is the one on screen — see `useRefreshEffect`'s
   *  docstring on why an invalidation while hidden must not refetch here. */
  active?: boolean;
  /** Followed topics, for the filter chips' accent hues. */
  topics: Topic[];
  /** Back to the feed from the empty-state CTA. */
  onNavigateHome?: () => void;
}

export function CollectionView<TRow>({ config, topics, onNavigateHome, active = true }: Props<TRow>) {
  const [rows, setRows] = useState<TRow[] | null>(null);
  const [error, setError] = useState(false);
  const [activeTopicId, setActiveTopicId] = useState<string | undefined>(undefined);
  const [sort, setSort] = useState<CollectionSortKey>("recent");
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

  // Consumed once by the next `scope` invalidation, so this view's own
  // remove / edit (which invalidates `scope` synchronously via engagement or
  // Card's own handler) doesn't force a loading flash over a change already
  // reflected locally. An invalidation from elsewhere still refetches.
  const skipNextRefreshRef = useRef(false);

  // Mirrors `rows` so remove handlers read it synchronously rather than from
  // inside a `setRows` updater — `offerUndo` calls setState on the unrelated
  // UndoToast, and an updater can run during React's render phase, which it
  // rejects with "Cannot update a component while rendering a different one".
  const rowsRef = useRef<TRow[] | null>(null);
  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  // Config is a stable module-level object per view; a ref keeps `load` /
  // the row ops from listing it as a dependency without going stale.
  const cfg = useRef(config);
  cfg.current = config;

  const hueByTopicId = useMemo(
    () => Object.fromEntries(topics.map((t) => [t.id, t.accent_hue])),
    [topics],
  );

  const load = useCallback(async (topicId: string | undefined, sortKey: CollectionSortKey) => {
    setError(false);
    setRows(null);
    try {
      await engagement.whenIdle();
      const data = await cfg.current.fetch(topicId, sortKey);
      setRows(data);
      // Server-authoritative seen state (ADR-0010) — merged in, not replacing
      // local state, so a card marked read this session whose write hasn't
      // round-tripped doesn't flicker back to unseen.
      setSeenIds((prev) => {
        const next = new Set(prev);
        for (const row of data) {
          const c = cfg.current.card(row);
          if (c.seen) next.add(c.id);
        }
        return next;
      });
    } catch {
      setError(true);
    }
  }, []);

  // Server-side views (Liked / Revisit): refetch on topic / sort change.
  useEffect(() => {
    if (config.clientFilterSort) return;
    void load(activeTopicId, sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTopicId, sort]);

  // Client-side view (Notes): fetch exactly once; filter + sort happen below.
  useEffect(() => {
    if (!config.clientFilterSort) return;
    void load(undefined, "recent");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reload = useCallback(() => {
    if (cfg.current.clientFilterSort) void load(undefined, "recent");
    else void load(activeTopicId, sort);
  }, [load, activeTopicId, sort]);

  // Manual refresh, or an invalidation from elsewhere (liking / bookmarking /
  // note-editing a card in the feed). Skipped once right after this view's own
  // change, which already updated `rows` locally.
  useRefreshEffect(
    config.scope,
    () => {
      if (skipNextRefreshRef.current) {
        skipNextRefreshRef.current = false;
        return;
      }
      reload();
    },
    active,
  );

  const removeWithUndo = useCallback<CollectionRowOps<TRow>["removeWithUndo"]>(
    (cardId, { label, redo }) => {
      const current = rowsRef.current;
      if (!current) return;
      const removed = current.find((r) => cfg.current.card(r).id === cardId);
      if (!removed) return;

      skipNextRefreshRef.current = true;
      setRows((cur) => (cur ? cur.filter((r) => cfg.current.card(r).id !== cardId) : cur));

      offerUndo({
        label,
        onUndo: () => {
          // Arm the guard BEFORE `redo` runs — its re-like / re-bookmark /
          // `invalidate` fires synchronously (or right after an await) and
          // would otherwise trip this view's own refresh listener.
          skipNextRefreshRef.current = true;
          void Promise.resolve(redo(removed)).then(() => {
            setRows((cur) => {
              if (!cur) return [removed];
              if (cur.some((r) => cfg.current.card(r).id === cardId)) return cur;
              return [removed, ...cur];
            });
          });
        },
      });
    },
    [],
  );

  const updateRow = useCallback<CollectionRowOps<TRow>["updateRow"]>((cardId, patch) => {
    setRows((cur) => cur?.map((r) => (cfg.current.card(r).id === cardId ? patch(r) : r)) ?? cur);
  }, []);

  const rowOps = useMemo<CollectionRowOps<TRow>>(
    () => ({ removeWithUndo, updateRow }),
    [removeWithUndo, updateRow],
  );

  // Unique topics present in the collection, for the filter bar.
  const collectionTopics = useMemo(() => {
    if (!rows) return [];
    const seen = new Map<string, { id: string; name: string }>();
    for (const r of rows) {
      const c = config.card(r);
      if (!seen.has(c.topic_id)) seen.set(c.topic_id, { id: c.topic_id, name: config.topicName(r) });
    }
    return Array.from(seen.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [rows, config]);

  const visible = useMemo(() => {
    if (!rows) return [];
    const q = search.trim().toLowerCase();

    if (config.clientFilterSort) {
      let list = rows;
      if (activeTopicId) list = list.filter((r) => config.card(r).topic_id === activeTopicId);
      if (q) {
        list = list.filter(
          (r) =>
            config.card(r).title.toLowerCase().includes(q) ||
            config.card(r).summary.toLowerCase().includes(q) ||
            config.topicName(r).toLowerCase().includes(q) ||
            (config.searchExtra?.(r, q) ?? false),
        );
      }
      return config.sortRow ? [...list].sort((a, b) => config.sortRow!(a, b, sort)) : list;
    }

    // Server already applied topic + sort; only local search remains.
    if (!q) return rows;
    return rows.filter(
      (r) =>
        config.card(r).title.toLowerCase().includes(q) ||
        config.card(r).summary.toLowerCase().includes(q) ||
        config.topicName(r).toLowerCase().includes(q),
    );
  }, [rows, search, activeTopicId, sort, config]);

  const handleTopicFilter = (topicId: string | undefined) => {
    setActiveTopicId(topicId);
    setSearch("");
  };

  const totalCards = rows?.length ?? 0;
  const topicCount = collectionTopics.length;

  const Header = (
    <div className="collection-header">
      <p className="collection-eyebrow">{config.eyebrow}</p>
      <p className="collection-title">{config.title}</p>
    </div>
  );
  const HeaderNoTitle = (
    <div className="collection-header">
      <p className="collection-eyebrow">{config.eyebrow}</p>
    </div>
  );

  // ── Loading ────────────────────────────────────────────────────────────────
  if (rows === null && !error) {
    return (
      <div className="collection-view">
        {Header}
        <div className="collection-list">
          {[1, 2, 3].map((i) => (
            <div key={i} className="collection-skeleton-card" aria-hidden="true">
              <div className="collection-skeleton-meta collection-skeleton-bar" />
              <div className="collection-skeleton-title collection-skeleton-bar" />
              <div className="collection-skeleton-body collection-skeleton-bar" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Error ──────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="collection-view">
        {HeaderNoTitle}
        <div className="collection-state">
          <p className="collection-state-head">{config.errorHead}</p>
          <p className="collection-state-body">Something went sideways.</p>
          <button type="button" className="collection-action collection-cta" onClick={reload}>
            TRY AGAIN
          </button>
        </div>
      </div>
    );
  }

  // ── Empty (nothing collected, no active filter) ────────────────────────────
  if (totalCards === 0 && !activeTopicId && !search) {
    return (
      <div className="collection-view">
        {Header}
        <div className="collection-state">
          <pre className="collection-state-ascii" aria-hidden="true">{`
  ${config.emptyGlyph}  ·  ·  ·  ·  ·
  ·  ·  ·  ·  ·  ·
  ·  ·  ·  ·  ·  ·`}</pre>
          <p className="collection-state-head">{config.emptyHead}</p>
          <p className="collection-state-body">{config.emptyBody}</p>
          {onNavigateHome ? (
            <button
              type="button"
              className="collection-action collection-cta"
              onClick={onNavigateHome}
            >
              <span className="collection-action-icon">
                <HomeIcon />
              </span>
              EXPLORE CARDS
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  // ── Main ───────────────────────────────────────────────────────────────────
  const [nounSingular, nounPlural] = config.countNoun;
  const [itemSingular, itemPlural] = config.itemNoun;

  return (
    <div className="collection-view">
      {Header}

      <p className="collection-meta">
        {totalCards === 1 ? `1 ${nounSingular}` : `${totalCards} ${nounPlural}`}
        {topicCount > 0 ? ` · ${topicCount} ${topicCount === 1 ? "TOPIC" : "TOPICS"}` : ""}
      </p>

      <hr className="collection-rule" />

      <div className="collection-controls">
        <input
          type="search"
          className="collection-search"
          placeholder={config.searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label={config.searchAriaLabel}
        />
        <div className="collection-pill-row" role="group" aria-label="Sort order">
          {(Object.keys(SORT_LABELS) as CollectionSortKey[]).map((key) => (
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

      {collectionTopics.length > 1 ? (
        <div className="collection-filters" role="group" aria-label="Filter by topic">
          <button
            type="button"
            className="collection-chip"
            data-selected={!activeTopicId}
            onClick={() => handleTopicFilter(undefined)}
          >
            ALL
          </button>
          {collectionTopics.map((t) => {
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
          {search
            ? `No ${config.filteredEmptyNoun} match "${search}".`
            : `No ${config.filteredEmptyNoun} in this topic.`}
        </p>
      ) : null}

      <div className="collection-list">
        <AnimatePresence initial={false}>
          {visible.map((row) => (
            <Card
              key={config.card(row).id}
              card={config.card(row)}
              topicName={config.topicName(row)}
              accentHue={topicHue(config.card(row).topic_id, hueByTopicId[config.card(row).topic_id])}
              seen={seenIds.has(config.card(row).id)}
              onSeen={handleSeen}
              onUnseen={handleUnseen}
              isHero={false}
              {...config.cardProps(row, rowOps)}
            />
          ))}
        </AnimatePresence>
      </div>

      {visible.length > 0 ? (
        <div className="collection-footer" aria-hidden="true">
          <span className="collection-footer-icon">{config.footerIcon}</span>
          <span className="collection-footer-label">
            {visible.length} {visible.length === 1 ? itemSingular : itemPlural} {config.footerVerb}
          </span>
        </div>
      ) : null}
    </div>
  );
}
