"use client";

/**
 * One card in the thread.
 *
 * The collapsed state carries the whole surface content-model.md asks for:
 * topic, difficulty, title, a preview hook, read state, and all six actions —
 * like, bookmark, note, ask AI, share, got it. Nothing waits for expansion,
 * "got it" included: it is reachable as the circular icon at the far right
 * of the action row whether or not the card has ever been opened.
 *
 * ADR-0017 adds hybrid disclosure on top of that: the preview hook shown
 * while collapsed depends on `card.archetype` (server-derived, never guessed
 * here — see lib/api.ts and content/archetype.py on the API). A card can
 * carry more than one tag; `getPrimaryArchetype` picks a priority order for
 * the COLLAPSED teaser only. Expanded always renders the full body via the
 * extended `Markdown` parser below, so every tag's content shows regardless
 * of which one "won" the teaser.
 *
 * Tapping a COLLAPSED card opens it (hero cards are the one exception — see
 * `isHero` below, never collapse). Once expanded, tapping the card body no
 * longer closes it — a long body means the reader's next several taps are
 * inside it (selecting text, hitting a code block's copy button), and a tap
 * that closes the whole card by accident there is a real annoyance, not a
 * shortcut. Instead, an explicit × at the far right of the head row, tapping
 * anywhere OUTSIDE the card, or Escape all close it.
 *
 * This component owns the interaction, never the rules. What counts as SEEN and
 * what the dwell threshold means belong to the API. It reports what happened,
 * honestly and separately:
 *
 *   expand            -> sent promptly; progression depends on it
 *   explicit_complete -> they tapped "Got it"
 *   dwell_complete    -> they stayed past the threshold
 */

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { motion } from "framer-motion";
import katex from "katex";

import { api, type ArchetypeTag, type Card as CardModel, type Difficulty } from "@/lib/api";
import { DwellTimer, engagement } from "@/lib/engagement";
import { invalidate } from "@/lib/refresh";
import { HeroTutorialOverlay } from "./HeroTutorialOverlay";
import {
  BookmarkIcon,
  CheckIcon,
  CloseIcon,
  CopyIcon,
  ExpandIcon,
  HeartIcon,
  NoteIcon,
  ShareIcon,
  SparkIcon,
} from "./icons";

/** ADR-0035. Per-browser, matching ThemePicker's `spoin-palette` precedent —
 *  presentation-only state, no product consequence if lost or duplicated
 *  across devices. */
const HERO_TUTORIAL_KEY = "spoin-hero-tutorial-seen";

/** Module-scope, not component state: every Card in the feed shares one flag
 *  so that when several hero cards mount in the same render pass (multiple
 *  stations, each with its own hero), only the first to claim it shows the
 *  tutorial instead of every one of them stacking overlays. Resets on full
 *  reload, same as the in-memory-only parts of feed state elsewhere — the
 *  localStorage flag above is what actually makes it a once-ever tutorial. */
let heroTutorialClaimed = false;

function claimHeroTutorial(): boolean {
  if (typeof window === "undefined" || localStorage.getItem(HERO_TUTORIAL_KEY) !== null) return false;
  if (heroTutorialClaimed) return false;
  heroTutorialClaimed = true;
  return true;
}

/** Mirrors SPOIN_DWELL_COMPLETE_MS. The server stays the authority; this only
 *  decides when the client stops waiting and reports. */
const DWELL_COMPLETE_MS = 8000;

const DIFFICULTY_RANK: Record<Difficulty, number> = {
  beginner: 1,
  intermediate: 2,
  advanced: 3,
};

interface Props {
  card: CardModel;
  topicName: string;
  /** 0-359, or undefined for a mixed/unknown topic — omitted entirely rather
   *  than defaulted here, so --topic-accent falls back to the plain palette
   *  accent (ADR-0034) instead of every card converging on hue 0 (red). */
  accentHue: number | undefined;
  seen: boolean;
  onSeen: (cardId: string) => void;
  onUnseen: (cardId: string) => void;
  /** "First card in this station" — a feed-layout placeholder for real
   *  curation, not a property of the card (ADR-0017, docs/tasks/0006). */
  isHero: boolean;
  /** Opens the note editor pre-expanded — used by NotesView so a note is
   *  visible/editable immediately instead of requiring an extra click. */
  initialNoteOpen?: boolean;
  /** Seeds the liked state — used by LikedView where every card in the list
   *  is already liked. Feed cards omit this and start unliked (unchanged). */
  initialLiked?: boolean;
  /** Fired when the user untaps the heart from an already-liked state -- used
   *  by LikedView to remove the card from the collection after unlike. Omitted
   *  by the feed, which has nothing to remove. */
  onUnliked?: (cardId: string) => void;
  /** Seeds the bookmarked state -- used by SavedView where every card in the
   *  grid is already bookmarked. Feed cards omit this and start un-bookmarked. */
  initialBookmarked?: boolean;
  /** Fired when the user un-bookmarks from an already-saved state -- used by
   *  SavedView to remove the tile from the grid. Omitted by the feed. */
  onUnbookmarked?: (cardId: string) => void;
  /** Fired after a note save/delete completes, so a caller holding its own
   *  copy of this card's note (NotesView's list) can update without
   *  refetching the whole list. Omitted by the feed, which has nothing of
   *  its own to keep in sync beyond this card's own state. */
  onNoteChange?: (cardId: string, body: string | null) => void;
}

export function Card({
  card,
  topicName,
  accentHue,
  seen,
  onSeen,
  onUnseen,
  isHero,
  initialNoteOpen,
  initialLiked,
  onUnliked,
  initialBookmarked,
  onUnbookmarked,
  onNoteChange,
}: Props) {
  // Hero never collapses: starting `expanded` (and `everExpanded`) true and
  // making `toggle` a no-op for hero reuses every bit of existing dwell/reveal
  // logic below instead of forking a parallel code path for it.
  const [expanded, setExpanded] = useState(isHero);
  const [liked, setLiked] = useState(initialLiked ?? false);
  const [bookmarked, setBookmarked] = useState(initialBookmarked ?? false);
  const [noteOpen, setNoteOpen] = useState(initialNoteOpen ?? false);
  const [noteDraft, setNoteDraft] = useState(card.note ?? "");
  const [savedNote, setSavedNote] = useState(card.note ?? null);
  const [noteSaving, setNoteSaving] = useState(false);
  const [everExpanded, setEverExpanded] = useState(isHero);
  const [focused, setFocused] = useState(true);
  // ADR-0035: only the very first hero card mounted while the flag is unset
  // shows the tutorial — read once at mount, not reactively, so it can't
  // flip back on for a second hero card later in the same session. Claims
  // via the shared `heroTutorialClaimed` flag so simultaneous hero cards
  // (multiple stations) don't all show it at once.
  const [showTutorial, setShowTutorial] = useState(() => isHero && claimHeroTutorial());

  const dwell = useRef(new DwellTimer());
  const article = useRef<HTMLElement>(null);
  const node = useRef<HTMLDivElement>(null);
  const gotItButton = useRef<HTMLButtonElement>(null);
  const impressed = useRef(false);

  const dismissTutorial = useCallback(() => {
    localStorage.setItem(HERO_TUTORIAL_KEY, "1");
    setShowTutorial(false);
  }, []);

  // Auto-dismiss if the card gets marked seen through any path while the
  // tutorial is up — no separate dismiss click needed once the thing it was
  // pointing at is already done.
  useEffect(() => {
    if (seen && showTutorial) dismissTutorial();
  }, [seen, showTutorial, dismissTutorial]);

  const collapse = useCallback(() => {
    if (isHero) return;
    setExpanded(false);
    engagement.record(card.id, "collapse");
  }, [card.id, isHero]);

  // An impression is logged when the card actually enters the viewport, not on
  // render. Without a true denominator `card_quality` is not a rate, and a rate
  // is the only thing stopping old cards dominating the ranker forever.
  useEffect(() => {
    const el = article.current;
    if (el === null || impressed.current) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !impressed.current) {
          impressed.current = true;
          engagement.record(card.id, "impression");
          observer.disconnect();
        }
      },
      { threshold: 0.5 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [card.id]);

  // Focus pull (ADR-0017): a card mostly in view reads as scale-100/opacity-100,
  // one mostly scrolled past reads as scale-95/opacity-50. Deliberately NOT
  // scroll-snap — the feed scrolls at the window level by design (see the
  // header comment in globals.css on why), and forcing a hard snap point there
  // would fight the sticky `.station` header and in-place height changes on
  // expand/collapse. This reuses the same IntersectionObserver pattern as the
  // impression tracker above rather than a scroll-position/rAF loop.
  useEffect(() => {
    const el = node.current;
    if (el === null) return;

    const observer = new IntersectionObserver(
      ([entry]) => setFocused(entry.intersectionRatio > 0.6),
      { threshold: [0, 0.25, 0.5, 0.6, 0.75, 1] },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Click genuinely empty space — outside every card, not just this one — to
  // close it, and Escape too.
  //
  // `pointerdown` rather than `click`: a click fires only after mouseup, so a
  // press that starts outside and drags across the card would still close it.
  // Listening on the capture phase catches it before the target card's own
  // click handler runs.
  //
  // A click on a *different* card does NOT close this one — cards can be
  // expanded independently and simultaneously. Only a click that lands
  // outside every `.card` (the gaps, the masthead, the margins) collapses
  // this one.
  useEffect(() => {
    if (!expanded || isHero) return;

    const onPointerDown = (event: PointerEvent) => {
      const el = article.current;
      const target = event.target as HTMLElement;
      if (el !== null && !el.contains(target) && target.closest(".card") === null) {
        collapse();
      }
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") collapse();
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [expanded, isHero, collapse]);

  // Dwell accrues only while expanded, the tab is visible, AND the card is
  // actually the one in view (`focused`, from the intersection observer
  // above) — scrolling on to the next card while this one stays expanded
  // must stop the clock, or a card gets silently marked read seconds after
  // the reader has moved past it. The completion check is scheduled for the
  // remaining time (threshold minus what's already accumulated) rather than
  // a flat 8s-from-mount timeout, so pausing and resuming across several
  // scroll-past/scroll-back cycles still adds up correctly instead of either
  // firing early or never re-arming.
  useEffect(() => {
    // Hero cards are only marked seen by the explicit "mark as read" action
    // (see the explicit_complete handler below) — never by dwell time, since
    // they start pre-expanded and would otherwise self-mark within seconds
    // of appearing, before the reader has actually read anything.
    if (!expanded || isHero) return;

    const timer = dwell.current;
    let completeTimer: ReturnType<typeof setTimeout> | null = null;

    const clearScheduled = () => {
      if (completeTimer !== null) {
        clearTimeout(completeTimer);
        completeTimer = null;
      }
    };

    const complete = () => {
      engagement.record(card.id, "dwell_complete", timer.elapsedMs);
      onSeen(card.id);
    };

    const schedule = () => {
      const remaining = DWELL_COMPLETE_MS - timer.elapsedMs;
      if (remaining <= 0) {
        complete();
        return;
      }
      completeTimer = setTimeout(complete, remaining);
    };

    const sync = () => {
      clearScheduled();
      if (document.visibilityState === "visible" && focused) {
        timer.start();
        schedule();
      } else {
        timer.pause();
      }
    };

    sync();
    document.addEventListener("visibilitychange", sync);

    return () => {
      clearScheduled();
      document.removeEventListener("visibilitychange", sync);
      timer.pause();
      if (timer.elapsedMs > 0) engagement.record(card.id, "dwell", timer.elapsedMs);
    };
  }, [expanded, focused, card.id, onSeen]);

  // Clicking the card anywhere outside the action row toggles it — open if
  // collapsed, closed if already expanded. Symmetric with the click-outside
  // and Escape handlers above, which cover the "closed by something other
  // than the card itself" cases this doesn't. No-op for hero (never collapses).
  const toggle = () => {
    // Opens a collapsed card. Once expanded, a tap on the body is a no-op —
    // closing happens only via the explicit × (below) or clicking outside.
    if (isHero || expanded) return;
    setExpanded(true);
    setEverExpanded(true);
    engagement.record(card.id, "expand");
    // Fallback for a feed with no hero card in it: nothing has claimed the
    // mark-as-read tutorial yet, so the first regular card the reader opens
    // takes the slot instead of the tutorial silently never showing.
    if (claimHeroTutorial()) setShowTutorial(true);
  };

  // Toggleable: a stray tap is easy to make on a circular icon this small, so
  // tapping it again undoes it. This only corrects the LOCAL, in-session
  // indicator — the `explicit_complete` event already sent is an immutable
  // fact in the log (ADR-0011) and is never retracted, and server-side SEEN
  // state deliberately never reverts (ADR-0010). Turning the icon back off
  // does not re-hide the card or un-teach the quiz gate what it already
  // knows; it just fixes what the button looks like right now.
  const gotIt = (event: React.MouseEvent) => {
    event.stopPropagation();
    if (seen) {
      onUnseen(card.id);
      return;
    }
    engagement.record(card.id, "explicit_complete", dwell.current.elapsedMs);
    onSeen(card.id);
  };

  const act = (event: React.MouseEvent, run: () => void) => {
    // Actions live in the row regardless of expanded state, so every one of
    // them has to stop the click from also toggling the card.
    event.stopPropagation();
    run();
  };

  const saveNote = async () => {
    const trimmed = noteDraft.trim();
    if (noteSaving) return;
    setNoteSaving(true);
    try {
      if (trimmed === "") {
        if (savedNote !== null) {
          await api.deleteNote(card.id);
          setSavedNote(null);
          onNoteChange?.(card.id, null);
          invalidate("notes");
        }
      } else {
        const result = await api.saveNote(card.id, trimmed);
        setSavedNote(result.body);
        onNoteChange?.(card.id, result.body);
        engagement.record(card.id, "note");
        invalidate("notes");
      }
    } finally {
      setNoteSaving(false);
    }
  };

  const deleteNote = async () => {
    if (noteSaving) return;
    setNoteSaving(true);
    try {
      await api.deleteNote(card.id);
      setSavedNote(null);
      setNoteDraft("");
      onNoteChange?.(card.id, null);
      invalidate("notes");
    } finally {
      setNoteSaving(false);
    }
  };

  const archetype = getPrimaryArchetype(card.archetype);
  // ASCII scene (ADR-0021, or a model-drawn one on the free-form generation
  // testing branch — see lib/api.ts). Renders right after the title, in the
  // usual teaser/summary's slot, standing in for it entirely — the scene IS
  // the preview while collapsed, not an addition to it.
  const asciiArt = card.visual_id !== null ? card.visual_slots?.art : undefined;
  const hasAsciiArt = asciiArt !== undefined && asciiArt.trim() !== "";

  return (
    <motion.div
      ref={node}
      className="node"
      data-read={seen}
      layout
      exit={{ x: "100%", opacity: 0, transition: { duration: 0.22 } }}
      transition={{ layout: { duration: 0.22, ease: [0.16, 1, 0.3, 1] } }}
    >
      <div className="card-focus" data-focused={focused}>
        <article
          ref={article}
          className="card"
          data-expanded={expanded}
          data-hero={isHero}
          onClick={toggle}
          aria-expanded={expanded}
          style={accentHue !== undefined ? ({ "--topic-hue": accentHue } as CSSProperties) : undefined}
        >
          <div className="card-head">
            {/* Always this user's own name for the topic (ADR-0004). */}
            <span className="card-topic">{topicName}</span>
            <span className="difficulty" aria-label={card.difficulty}>
              {[1, 2, 3].map((step) => (
                <i key={step} data-on={step <= DIFFICULTY_RANK[card.difficulty]} />
              ))}
            </span>
            {seen ? <span className="card-read">· Read</span> : null}
            {isHero ? <span className="hero-badge">Hero</span> : null}
            {expanded && !isHero ? (
              <button
                type="button"
                className="card-close"
                aria-label="Collapse card"
                onClick={(e) => {
                  e.stopPropagation();
                  collapse();
                }}
              >
                <CloseIcon />
              </button>
            ) : null}
          </div>

          <h2 className="card-title">{inline(normalizeText(card.title))}</h2>

          {/* An ascii-art card shows its scene right where the summary/teaser
              normally goes — the FIRST thing after the title, ahead of
              everything else, standing in for the usual collapsed hook
              entirely (never both). Kept visible through expansion too,
              unlike the code/diagram teaser above, since the art is a
              standalone illustration, not a preview of something body
              repeats. */}
          {hasAsciiArt ? (
            <AsciiArt art={asciiArt!} alt={card.visual_slots?.alt} />
          ) : archetype === "default" ? (
            <p className="card-summary">{inline(normalizeText(card.summary))}</p>
          ) : !expanded ? (
            <ArchetypeTeaser archetype={archetype} body={card.body} />
          ) : null}

          {/* `inert` while collapsed. Clipping to zero height hides the body
              visually but leaves it in the tab order, so keyboard users would
              otherwise tab through every collapsed card's hidden content. */}
          <div className="card-reveal" data-open={expanded} inert={!expanded}>
            <div className="card-reveal-body">
              <div className="card-body">
                <Markdown source={card.body} />
              </div>
            </div>
          </div>

          <div className="card-actions">
            <button
              className="action"
              data-on={liked}
              aria-pressed={liked}
              aria-label="Like"
              onClick={(e) =>
                act(e, () => {
                  const wasLiked = liked;
                  setLiked(!wasLiked);
                  engagement.record(card.id, wasLiked ? "unlike" : "like");
                  if (wasLiked) onUnliked?.(card.id);
                })
              }
              type="button"
            >
              <HeartIcon filled={liked} />
            </button>

            <button
              className="action"
              data-on={bookmarked}
              aria-pressed={bookmarked}
              aria-label="Save"
              onClick={(e) =>
                act(e, () => {
                  const wasBookmarked = bookmarked;
                  setBookmarked(!wasBookmarked);
                  engagement.record(card.id, wasBookmarked ? "unbookmark" : "bookmark");
                  if (wasBookmarked) onUnbookmarked?.(card.id);
                })
              }
              type="button"
            >
              <BookmarkIcon />
            </button>

            <button
              className="action"
              data-on={savedNote !== null}
              aria-pressed={noteOpen}
              aria-label="Note"
              onClick={(e) => act(e, () => setNoteOpen((open) => !open))}
              type="button"
            >
              <NoteIcon />
            </button>

            <button
              className="action"
              aria-label="Ask AI"
              onClick={(e) => act(e, () => engagement.record(card.id, "ask_ai"))}
              type="button"
            >
              <SparkIcon />
            </button>

            <button
              className="action"
              aria-label="Share"
              onClick={(e) => act(e, () => engagement.record(card.id, "share"))}
              type="button"
            >
              <ShareIcon />
            </button>

            <span className="action-spacer" />

            {/* Sits apart from the other five by both position and shape —
                pushed to the extreme right by the spacer above, its own
                circular fill once active. Disabled until the card has been
                opened at least once this session: it is a fast way to confirm
                "I already know this" after a look, not a way to skip reading
                altogether. */}
            <button
              ref={gotItButton}
              className="action action-gotit"
              data-done={seen}
              aria-label={everExpanded ? "Got it" : "Got it (open the card first)"}
              disabled={!everExpanded}
              onClick={gotIt}
              type="button"
            >
              <CheckIcon />
            </button>
          </div>

          {/* Always mounted, height driven by a real CSS transition (the
              grid-template-rows 0fr/1fr trick) rather than a conditional
              `noteOpen ? ... : null` or a display:none/block flip — both of
              those change height in one instant frame, which is what made
              Framer Motion's `layout` on the outer .node (compensating by
              animating the WHOLE card's transform between its old and new
              bounding box) look like a discontinuous jump instead of one
              continuous grow/shrink: framer had a real, gradual height
              change to track against every frame instead of a single jump
              to react to. */}
          <div className="card-note" data-open={noteOpen} inert={!noteOpen} onClick={(e) => e.stopPropagation()}>
            <div className="card-note-body">
              <textarea
                className="card-note-input"
                placeholder="Private note — only you can see this."
                value={noteDraft}
                onChange={(e) => setNoteDraft(e.target.value)}
                disabled={noteSaving}
                rows={3}
              />
              <div className="card-note-actions">
                {savedNote !== null ? (
                  <button
                    type="button"
                    className="card-note-delete"
                    onClick={() => void deleteNote()}
                    disabled={noteSaving}
                  >
                    Delete
                  </button>
                ) : null}
                <button
                  type="button"
                  className="card-note-save"
                  onClick={() => void saveNote()}
                  disabled={noteSaving || noteDraft.trim() === (savedNote ?? "")}
                >
                  {noteSaving ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          </div>
        </article>
      </div>

      {showTutorial ? <HeroTutorialOverlay targetRef={gotItButton} onDismiss={dismissTutorial} /> : null}
    </motion.div>
  );
}

/** Priority order for the COLLAPSED teaser only — expanded always shows every
 *  tag's content via the full Markdown render regardless of which one "won"
 *  here (ADR-0017). "combo" is a teaser-only category: a card tagged both
 *  code and diagram gets a stacked teaser showing a line of each, rather
 *  than picking one and hiding the other from the preview entirely. */
function getPrimaryArchetype(tags: ArchetypeTag[]): ArchetypeTag | "combo" | "default" {
  if (tags.includes("code") && tags.includes("diagram")) return "combo";
  if (tags.includes("code")) return "code";
  if (tags.includes("diagram")) return "diagram";
  if (tags.includes("comparison")) return "comparison";
  return "default";
}

/** Normalizes escaped characters (e.g. \n, \", \') while preserving LaTeX syntax. */
function normalizeText(source: string): string {
  if (!source) return "";

  // Protect escaped dollar signs \$ before splitting on math boundaries
  const escapedDollarPlaceHolder = "\uE000";
  const text = source.replace(/\\\$/g, escapedDollarPlaceHolder);

  // Match $$...$$, $...$, \[...\], \(...\)
  const mathRegex = /(\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\[[\s\S]*?\\\]|\\\([^)\n]+\\\))/g;
  const segments = text.split(mathRegex);

  for (let i = 0; i < segments.length; i++) {
    if (i % 2 === 0) {
      // Outside math: normalize escaped newlines, tabs, quotes
      segments[i] = segments[i]
        .replace(/\\r\\n|\\r/g, "\n")
        .replace(/\\n/g, "\n")
        .replace(/\\t/g, "  ")
        .replace(/\\"/g, '"')
        .replace(/\\'/g, "'");
    } else {
      // Inside math: normalize linebreaks and quotes
      segments[i] = segments[i]
        .replace(/\\r\\n|\\r/g, "\n")
        .replace(/\\"/g, '"')
        .replace(/\\'/g, "'");
    }
  }

  return segments.join("").replace(new RegExp(escapedDollarPlaceHolder, "g"), "\\$");
}

/** Presentation-only mirror of content/archetype.py's diagram heuristic — it
 *  exists here purely to pick which fenced block to preview in the collapsed
 *  teaser. `card.archetype` (server-derived) remains the single source of
 *  truth for WHICH archetype a card is; this never overrides it. */
const DIAGRAM_LANG_TAGS = new Set(["diagram", "text", "ascii", "table", ""]);
const DIAGRAM_CHARS_RE = /[─│┌└┐┘├┤┬┴┼→▶►]|-->|==>|──>|\+[-+]+\+|\|.*\|/;

function isDiagramFence(lang: string, content: string): boolean {
  const normalized = lang.toLowerCase();
  if (normalized === "diagram") return true;
  if (!DIAGRAM_LANG_TAGS.has(normalized)) return false;
  return DIAGRAM_CHARS_RE.test(content);
}

const FENCE_RE = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g;

function firstFenceOfKind(body: string, kind: "code" | "diagram"): { lang: string; content: string } | null {
  const normalized = normalizeText(body);
  for (const match of normalized.matchAll(FENCE_RE)) {
    const [, lang, content] = match;
    if ((isDiagramFence(lang, content) ? "diagram" : "code") === kind) {
      return { lang, content: content.replace(/\n$/, "") };
    }
  }
  return null;
}

function firstNonEmptyLine(text: string): string {
  return text.split("\n").find((line) => line.trim().length > 0)?.trim() ?? "";
}

/** The teaser renders as plain text, not through `inline()` — so this both
 *  picks a SHORT label (the bolded claim right after the marker, if the body
 *  follows the `❌ **claim** — explanation` shape; a truncated first line
 *  otherwise) and strips markdown syntax, rather than showing raw `**`/full
 *  paragraphs verbatim. */
function extractComparisonTag(marker: string, body: string): string | null {
  const normalized = normalizeText(body);
  const boldClaim = new RegExp(`${marker}\\s*\\*\\*([^*]+)\\*\\*`).exec(normalized);
  if (boldClaim !== null) return boldClaim[1].trim();

  const line = new RegExp(`${marker}\\s*([^\\n]+)`).exec(normalized);
  if (line === null) return null;
  const plain = line[1].replace(/\*\*/g, "").trim();
  return plain.length > 60 ? `${plain.slice(0, 57).trimEnd()}…` : plain;
}

function comparisonTags(body: string): { bad: string; good: string } | null {
  const bad = extractComparisonTag("❌", body);
  const good = extractComparisonTag("✅", body);
  if (bad === null || good === null) return null;
  return { bad, good };
}

/** Renders a card's ASCII scene (ADR-0021, or free-form model-drawn art —
 *  see `Card.tsx`'s `hasAsciiArt`). */
function AsciiArt({ art, alt }: { art: string; alt: string | undefined }) {
  return (
    <div className="card-ascii" role="img" aria-label={alt || "A hand-drawn ASCII scene"}>
      <pre>{normalizeText(art)}</pre>
    </div>
  );
}

function ArchetypeTeaser({ archetype, body }: { archetype: ArchetypeTag | "combo"; body: string }) {
  if (archetype === "combo") {
    const code = firstFenceOfKind(body, "code");
    const diagram = firstFenceOfKind(body, "diagram");
    return (
      <div className="card-teaser card-teaser-combo">
        <div className="card-teaser-code">
          <span className="card-teaser-badge mono">{(code?.lang || "code").toUpperCase()}</span>
          <code className="card-teaser-line mono">
            {code !== null ? firstNonEmptyLine(code.content) : ""}
          </code>
        </div>
        <div className="card-teaser-combo-divider" />
        <p className="card-teaser-diagram mono">
          {diagram !== null ? firstNonEmptyLine(diagram.content) : ""}
        </p>
      </div>
    );
  }

  if (archetype === "code") {
    const fence = firstFenceOfKind(body, "code");
    return (
      <div className="card-teaser card-teaser-code">
        <span className="card-teaser-badge mono">{(fence?.lang || "code").toUpperCase()}</span>
        <code className="card-teaser-line mono">
          {fence !== null ? firstNonEmptyLine(fence.content) : ""}
        </code>
      </div>
    );
  }

  if (archetype === "diagram") {
    const fence = firstFenceOfKind(body, "diagram");
    return (
      <p className="card-teaser card-teaser-diagram mono">
        {fence !== null ? firstNonEmptyLine(fence.content) : ""}
      </p>
    );
  }

  // Minimal by design (ADR-0017 follow-up): the actual claim text is raw,
  // occasionally-unparsed markdown from the generator, so the collapsed
  // teaser shows only that a comparison exists, not its content. The full
  // claim renders properly via ProseBlocks once expanded.
  return (
    <div className="card-teaser card-teaser-comparison-mini">
      <span className="comparison-badge">
        <span className="comparison-badge-dots">
          <i />
          <i />
        </span>
        Myth vs Fact
      </span>
    </div>
  );
}

function MathBlock({ math }: { math: string }) {
  let clean = math.trim();
  if (clean.startsWith("$$") && clean.endsWith("$$") && clean.length >= 4) {
    clean = clean.slice(2, -2).trim();
  } else if (clean.startsWith("\\[") && clean.endsWith("\\]") && clean.length >= 4) {
    clean = clean.slice(2, -2).trim();
  }

  try {
    const html = katex.renderToString(clean, {
      displayMode: true,
      throwOnError: false,
      output: "htmlAndMathml",
    });
    return <div className="math-block" dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    return <pre className="math-block mono">{clean}</pre>;
  }
}

function InlineMath({ math }: { math: string }) {
  let clean = math.trim();
  if (clean.startsWith("$") && clean.endsWith("$") && clean.length >= 2) {
    clean = clean.slice(1, -1).trim();
  } else if (clean.startsWith("\\(") && clean.endsWith("\\)") && clean.length >= 4) {
    clean = clean.slice(2, -2).trim();
  }

  try {
    const html = katex.renderToString(clean, {
      displayMode: false,
      throwOnError: false,
      output: "htmlAndMathml",
    });
    return <span className="inline-math" dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    return <span className="inline-math">{clean}</span>;
  }
}

/**
 * Markdown renderer covering headings, paragraphs, ordered/unordered lists,
 * tables, blockquotes, bold, italic, inline code, links, LaTeX math formulas,
 * fenced code/diagram blocks, and ❌/✅ comparison pairs (ADR-0017).
 */
function Markdown({ source }: { source: string }) {
  const tokens = tokenize(source);

  return (
    <>
      {tokens.map((token, index) =>
        token.type === "fence" ? (
          token.kind === "diagram" ? (
            <DiagramBlock key={index} content={token.content} />
          ) : (
            <CodeBlock key={index} lang={token.lang} content={token.content} />
          )
        ) : (
          <ProseBlocks key={index} text={token.text} />
        ),
      )}
    </>
  );
}

type Token =
  | { type: "fence"; lang: string; content: string; kind: "code" | "diagram" }
  | { type: "prose"; text: string };

/** Fences are extracted BEFORE block splitting — a fenced block's own
 *  blank lines would otherwise get corrupted by line/paragraph splitters. */
function tokenize(source: string): Token[] {
  const normalized = normalizeText(source);
  const tokens: Token[] = [];
  let lastIndex = 0;

  for (const match of normalized.matchAll(FENCE_RE)) {
    const [full, lang, content] = match;
    const index = match.index ?? 0;
    if (index > lastIndex) tokens.push({ type: "prose", text: normalized.slice(lastIndex, index) });

    const kind = isDiagramFence(lang, content) ? "diagram" : "code";
    tokens.push({ type: "fence", lang, content: content.replace(/\n$/, ""), kind });

    lastIndex = index + full.length;
  }

  if (lastIndex < normalized.length) tokens.push({ type: "prose", text: normalized.slice(lastIndex) });
  return tokens;
}

function ProseBlocks({ text }: { text: string }) {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];
  let i = 0;
  let keyIndex = 0;

  let pairBuffer: { tone: "bad" | "good"; text: string }[] = [];
  const flushPairs = () => {
    if (pairBuffer.length === 0) return;
    const rows = pairBuffer;
    pairBuffer = [];
    nodes.push(
      <div className="comparison-pair" key={`pair-${keyIndex++}`}>
        {rows.map((row, idx) => (
          <div className="comparison-row" data-tone={row.tone} key={idx}>
            {inline(row.text)}
          </div>
        ))}
      </div>,
    );
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.length === 0) {
      flushPairs();
      i++;
      continue;
    }

    // Comparison row (❌ / ✅)
    const badMatch = /^❌\s*([\s\S]*)$/.exec(trimmed);
    const goodMatch = /^✅\s*([\s\S]*)$/.exec(trimmed);
    if (badMatch !== null || goodMatch !== null) {
      pairBuffer.push({
        tone: badMatch !== null ? "bad" : "good",
        text: (badMatch ?? goodMatch)![1],
      });
      i++;
      continue;
    }
    flushPairs();

    // Display Math Block: $$ ... $$ or \[ ... \]
    if (trimmed.startsWith("$$") || trimmed.startsWith("\\[")) {
      const isBracket = trimmed.startsWith("\\[");
      const endMarker = isBracket ? "\\]" : "$$";

      if (
        trimmed.length > 2 &&
        (isBracket ? trimmed.endsWith("\\]") : trimmed.slice(2).includes("$$"))
      ) {
        nodes.push(<MathBlock key={`math-${keyIndex++}`} math={trimmed} />);
        i++;
        continue;
      }

      const mathLines = [line];
      i++;
      while (i < lines.length) {
        mathLines.push(lines[i]);
        if (lines[i].includes(endMarker)) {
          i++;
          break;
        }
        i++;
      }
      nodes.push(<MathBlock key={`math-${keyIndex++}`} math={mathLines.join("\n")} />);
      continue;
    }

    // Heading: #, ##, ###, ####, #####, ######
    const headingMatch = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (headingMatch !== null) {
      const level = headingMatch[1].length;
      const Tag = (`h${Math.min(level, 6)}`) as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
      nodes.push(<Tag key={`h-${keyIndex++}`}>{inline(headingMatch[2])}</Tag>);
      i++;
      continue;
    }

    // Blockquote: > line
    if (trimmed.startsWith(">")) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ""));
        i++;
      }
      nodes.push(
        <blockquote key={`quote-${keyIndex++}`}>
          <p>{inline(quoteLines.join(" "))}</p>
        </blockquote>,
      );
      continue;
    }

    // Unordered List: - item, * item, • item
    if (/^[-*•]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ""));
        i++;
      }
      nodes.push(
        <ul key={`ul-${keyIndex++}`}>
          {items.map((item, idx) => (
            <li key={idx}>{inline(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    // Ordered List: 1. item, 2. item, 1) item
    if (/^\d+[.)]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+[.)]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+[.)]\s+/, ""));
        i++;
      }
      nodes.push(
        <ol key={`ol-${keyIndex++}`}>
          {items.map((item, idx) => (
            <li key={idx}>{inline(item)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    // Markdown Table: | a | b |
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
        tableLines.push(lines[i].trim());
        i++;
      }
      if (tableLines.length >= 2) {
        const parseRow = (r: string) =>
          r
            .slice(1, -1)
            .split("|")
            .map((c) => c.trim());
        const headerCols = parseRow(tableLines[0]);
        const isSeparator = /^[\s|:-]+$/.test(tableLines[1]);
        const bodyStart = isSeparator ? 2 : 1;
        const rows = tableLines.slice(bodyStart).map(parseRow);

        nodes.push(
          <div className="card-table-wrapper" key={`tbl-${keyIndex++}`}>
            <table>
              {isSeparator ? (
                <thead>
                  <tr>
                    {headerCols.map((col, idx) => (
                      <th key={idx}>{inline(col)}</th>
                    ))}
                  </tr>
                </thead>
              ) : null}
              <tbody>
                {rows.map((row, rIdx) => (
                  <tr key={rIdx}>
                    {row.map((cell, cIdx) => (
                      <td key={cIdx}>{inline(cell)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>,
        );
        continue;
      }
    }

    // Paragraph: collect lines until blank line or next structural block
    const pLines: string[] = [];
    while (i < lines.length) {
      const cur = lines[i].trim();
      if (cur.length === 0) break;
      if (
        /^#{1,6}\s+/.test(cur) ||
        /^[-*•]\s+/.test(cur) ||
        /^\d+[.)]\s+/.test(cur) ||
        cur.startsWith(">") ||
        cur.startsWith("$$") ||
        cur.startsWith("\\[") ||
        cur.startsWith("❌") ||
        cur.startsWith("✅") ||
        (cur.startsWith("|") && cur.endsWith("|"))
      ) {
        break;
      }
      pLines.push(cur);
      i++;
    }

    if (pLines.length > 0) {
      nodes.push(<p key={`p-${keyIndex++}`}>{inline(pLines.join(" "))}</p>);
    }
  }

  flushPairs();
  return <>{nodes}</>;
}

const INLINE_RE =
  /(\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\[[\s\S]*?\\\]|\\\([^)\n]+\\\)|`[^`]+`|\*\*\*[^*]+\*\*\*|___[^_]+___|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|~~[^~]+~~|\[[^\]]+\]\([^)]+\))/g;

function inline(text: string): React.ReactNode[] {
  return text.split(INLINE_RE).map((part, index) => {
    if (!part) return null;

    if (
      (part.startsWith("$$") && part.endsWith("$$") && part.length >= 4) ||
      (part.startsWith("\\[") && part.endsWith("\\]") && part.length >= 4)
    ) {
      return <MathBlock key={index} math={part} />;
    }

    if (
      (part.startsWith("$") && part.endsWith("$") && part.length >= 2) ||
      (part.startsWith("\\(") && part.endsWith("\\)") && part.length >= 4)
    ) {
      return <InlineMath key={index} math={part} />;
    }

    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }

    if (
      (part.startsWith("***") && part.endsWith("***") && part.length > 6) ||
      (part.startsWith("___") && part.endsWith("___") && part.length > 6)
    ) {
      return (
        <strong key={index}>
          <em>{part.slice(3, -3)}</em>
        </strong>
      );
    }

    if (
      (part.startsWith("**") && part.endsWith("**") && part.length > 4) ||
      (part.startsWith("__") && part.endsWith("__") && part.length > 4)
    ) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }

    if (
      (part.startsWith("*") && part.endsWith("*") && part.length > 2) ||
      (part.startsWith("_") && part.endsWith("_") && part.length > 2)
    ) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }

    if (part.startsWith("~~") && part.endsWith("~~") && part.length > 4) {
      return <del key={index}>{part.slice(2, -2)}</del>;
    }

    const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (linkMatch !== null) {
      return (
        <a key={index} href={linkMatch[2]} target="_blank" rel="noreferrer" className="card-link">
          {linkMatch[1]}
        </a>
      );
    }

    return <span key={index}>{part}</span>;
  });
}

/** Bounded, dependency-free highlighting for the handful of languages this
 *  corpus actually uses — not a general-purpose grammar. Comments and string
 *  literals per-line, plus a keyword list per language. */
const COMMENT_MARKERS: Record<string, string> = {
  bash: "#",
  python: "#",
  yaml: "#",
  dockerfile: "#",
  sql: "--",
  javascript: "//",
  typescript: "//",
};

const KEYWORDS: Record<string, string> = {
  bash: "if|then|else|fi|for|do|done|while|echo|export|function|return",
  python: "def|return|if|elif|else|for|while|import|from|class|with|as|in|not|and|or|None|True|False",
  javascript: "function|return|const|let|var|if|else|for|while|import|from|export|class|new|async|await",
  typescript:
    "function|return|const|let|var|if|else|for|while|import|from|export|class|new|async|await|interface|type",
  yaml: "true|false|null",
  sql: "SELECT|FROM|WHERE|JOIN|INSERT|UPDATE|DELETE|CREATE|TABLE|AND|OR|NOT|NULL|ORDER|BY|GROUP",
  dockerfile: "FROM|RUN|CMD|COPY|ADD|WORKDIR|EXPOSE|ENV|ENTRYPOINT|ARG|LABEL|USER",
};

const STRING_RE = /("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/;

function highlightLine(line: string, lang: string): React.ReactNode {
  const commentMarker = COMMENT_MARKERS[lang];
  if (commentMarker !== undefined && line.trimStart().startsWith(commentMarker)) {
    return <span className="code-tok-comment">{line}</span>;
  }

  const keywordPattern = KEYWORDS[lang];
  const segments = line.split(STRING_RE);

  return segments.map((segment, i) => {
    if (segment.length > 1 && (segment.startsWith('"') || segment.startsWith("'"))) {
      return (
        <span className="code-tok-string" key={i}>
          {segment}
        </span>
      );
    }
    if (keywordPattern === undefined) return <span key={i}>{segment}</span>;

    const wordRe = new RegExp(`\\b(${keywordPattern})\\b`, lang === "sql" ? "gi" : "g");
    const testRe = new RegExp(`^(?:${keywordPattern})$`, lang === "sql" ? "i" : "");
    const parts = segment.split(wordRe);
    return (
      <span key={i}>
        {parts.map((part, j) =>
          testRe.test(part) ? (
            <span className="code-tok-keyword" key={j}>
              {part}
            </span>
          ) : (
            part
          ),
        )}
      </span>
    );
  });
}

function CodeLines({ lines, lang }: { lines: string[]; lang: string }) {
  return (
    <pre>
      <span className="code-block-lines">
        {lines.map((_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </span>
      <code className="code-block-source">
        {lines.map((line, i) => (
          <div key={i}>{highlightLine(line, lang)}</div>
        ))}
      </code>
    </pre>
  );
}

function CodeBlock({ lang, content }: { lang: string; content: string }) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const lines = content.split("\n");
  const normalizedLang = lang.toLowerCase();

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be denied (permissions, insecure context). The
      // button just stays "Copy" — nothing recoverable client-side.
    }
  };

  return (
    <div className="code-block">
      <div className="code-block-head">
        <span>{lang || "code"}</span>
        <button
          type="button"
          className="code-block-copy"
          data-copied={copied}
          onClick={(e) => {
            e.stopPropagation();
            void copy();
          }}
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
          {copied ? "Copied" : "Copy"}
        </button>
        <button
          type="button"
          className="block-expand"
          aria-label="Expand code"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(true);
          }}
        >
          <ExpandIcon />
        </button>
      </div>
      <CodeLines lines={lines} lang={normalizedLang} />
      {expanded ? (
        <BlockModal title={lang || "code"} onClose={() => setExpanded(false)}>
          <div className="code-block">
            <CodeLines lines={lines} lang={normalizedLang} />
          </div>
        </BlockModal>
      ) : null}
    </div>
  );
}

function DiagramBlock({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="diagram-block">
      <div className="diagram-block-head">
        <button
          type="button"
          className="block-expand"
          aria-label="Expand diagram"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(true);
          }}
        >
          <ExpandIcon />
        </button>
      </div>
      <pre>{content}</pre>
      {expanded ? (
        <BlockModal title="Diagram" onClose={() => setExpanded(false)}>
          <div className="diagram-block">
            <pre>{content}</pre>
          </div>
        </BlockModal>
      ) : null}
    </div>
  );
}

/** Portal + Escape-to-close + body-scroll-lock, matching TopicStatsModal's
 *  idiom (ADR-0015) — the feed scrolls at the window level, so without the
 *  lock it keeps scrolling underneath the open modal. */
function BlockModal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
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

  return createPortal(
    <div
      className="modal-overlay"
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
    >
      <div
        className="modal-panel modal-panel-wide"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title">{title}</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
