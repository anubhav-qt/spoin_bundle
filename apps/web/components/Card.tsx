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

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { motion } from "framer-motion";
import katex from "katex";

import {
  ApiError,
  api,
  type ArchetypeTag,
  type Card as CardModel,
  type CardReportReason,
  type Difficulty,
} from "@/lib/api";
import { DwellTimer, engagement } from "@/lib/engagement";
import { bookmarkedStore, likedStore } from "@/lib/engagementState";
import { invalidate } from "@/lib/refresh";
import { AskPanel } from "./AskPanel";
import { HeroTutorialOverlay } from "./HeroTutorialOverlay";
import { MermaidBlock } from "./MermaidBlock";
import {
  BookmarkIcon,
  CheckIcon,
  CloseIcon,
  CopyIcon,
  ExpandIcon,
  FlagIcon,
  HeartIcon,
  LinkIcon,
  NoteIcon,
  PhotoIcon,
  ShareIcon,
  SparkIcon,
} from "./icons";

/** B14 / ADR-0076: the five report reasons, in picker order. */
const REPORT_REASONS: { value: CardReportReason; label: string }[] = [
  { value: "art", label: "Bad art" },
  { value: "diagram", label: "Broken diagram" },
  { value: "code_block", label: "Code block shouldn’t be here" },
  { value: "formatting", label: "Formatting is broken" },
  { value: "other", label: "Something else" },
];

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
const DWELL_COMPLETE_MS = 10000;

/** How long a card must stay ≥50% on screen before it counts as shown.
 *
 *  An impression is no longer free: it marks the card DEFERRED server-side, so
 *  it drops out of rotation until this difficulty's cycle comes round again.
 *  Without a threshold, one fast flick down the feed would consume every card
 *  it passed. A second is long enough that the reader plausibly saw the card
 *  and short enough that ordinary browsing still advances the feed. */
const IMPRESSION_DWELL_MS = 1000;

/** How far the pointer may travel, and how long it may stay down, for a
 *  press/release pair on the page background to still count as a deliberate
 *  tap rather than the start of a scroll. Both are deliberately generous —
 *  the cost of missing a real tap is one extra tap; the cost of a false
 *  positive is every open card collapsing mid-scroll. */
const TAP_SLOP_PX = 10;
const TAP_MAX_MS = 500;

const DIFFICULTY_RANK: Record<Difficulty, number> = {
  beginner: 1,
  intermediate: 2,
  advanced: 3,
};

interface Props {
  card: CardModel;
  topicName: string;
  /** 0-359, null when the topic has explicitly opted out of coloring
   *  (ADR-0051), or undefined for a mixed/unknown topic — all three leave
   *  no `--topic-hue` set below, so --topic-accent falls back to the plain
   *  palette accent (ADR-0034) instead of every card converging on hue 0
   *  (red). */
  accentHue: number | null | undefined;
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
  // Seeded from the cross-instance store first (lib/engagementState.ts) so
  // a card already toggled by ANOTHER mounted Card for the same card_id
  // (e.g. unliked from LikedView while this Feed card is still mounted)
  // renders correctly on mount rather than defaulting stale. `initialLiked`/
  // `initialBookmarked` only wins when the store has nothing yet.
  const [liked, setLiked] = useState(() => likedStore.get(card.id) ?? initialLiked ?? false);
  const [bookmarked, setBookmarked] = useState(
    () => bookmarkedStore.get(card.id) ?? initialBookmarked ?? false,
  );
  const [noteOpen, setNoteOpen] = useState(initialNoteOpen ?? false);
  const [noteDraft, setNoteDraft] = useState(card.note ?? "");
  const [savedNote, setSavedNote] = useState(card.note ?? null);
  const [noteSaving, setNoteSaving] = useState(false);
  const [everExpanded, setEverExpanded] = useState(isHero);
  const [focused, setFocused] = useState(true);
  const [shareOpen, setShareOpen] = useState(false);
  const [copyingImage, setCopyingImage] = useState(false);
  const [copiedImage, setCopiedImage] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);
  const shareWrapRef = useRef<HTMLDivElement>(null);
  const reportWrapRef = useRef<HTMLDivElement>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState<CardReportReason | null>(null);
  const [reportNote, setReportNote] = useState("");
  const [reportBusy, setReportBusy] = useState(false);
  const [reported, setReported] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [askOpen, setAskOpen] = useState(false);
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

  // A caller that passes `initialLiked`/`initialBookmarked` explicitly
  // (LikedView, SavedView) actually knows the server state -- its own list
  // membership implies it -- so it's authoritative and pushed into the
  // shared store for any other mounted instance of this same card to pick
  // up. A caller that omits the prop (Feed, Notes, Share) contributes
  // nothing here and instead reads whatever the store already has.
  useEffect(() => {
    if (initialLiked !== undefined) likedStore.set(card.id, initialLiked);
  }, [card.id, initialLiked]);
  useEffect(() => {
    if (initialBookmarked !== undefined) bookmarkedStore.set(card.id, initialBookmarked);
  }, [card.id, initialBookmarked]);

  // Stay in sync with every OTHER mounted Card for this same card_id --
  // see lib/engagementState.ts for why more than one can be mounted at once.
  useEffect(() => likedStore.subscribe(card.id, setLiked), [card.id]);
  useEffect(() => bookmarkedStore.subscribe(card.id, setBookmarked), [card.id]);

  useEffect(() => {
    if (!shareOpen) return;
    const onPointer = (e: PointerEvent) => {
      if (shareWrapRef.current && !shareWrapRef.current.contains(e.target as Node)) {
        setShareOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShareOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [shareOpen]);

  useEffect(() => {
    if (!reportOpen) return;
    const close = () => {
      setReportOpen(false);
      setReportError(null);
    };
    const onPointer = (e: PointerEvent) => {
      if (reportWrapRef.current && !reportWrapRef.current.contains(e.target as Node)) {
        close();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [reportOpen]);

  const submitReport = async () => {
    if (!reportReason || reportBusy) return;
    setReportBusy(true);
    setReportError(null);
    try {
      await api.reportCard(card.id, {
        reason: reportReason,
        note: reportNote.trim() || null,
      });
      // Flagged, and it stays flagged for the rest of this session: the icon
      // keeps its filled/accent state and re-opening just shows the
      // acknowledgement, not another form. (Persisting across reloads needs a
      // `reported_by_me` flag on the card payload — not yet.)
      setReported(true);
      setTimeout(() => setReportOpen(false), 1400);
    } catch (e) {
      // Keep the popover open so they can retry — but say what went wrong.
      // A 404 means this card row was superseded (a repair/revert landed)
      // while the feed still held it, so the report has nowhere to attach.
      setReportError(
        e instanceof ApiError && e.status === 404
          ? "This card was just updated — reload to report the current version."
          : "Couldn’t send that report. Try again in a moment.",
      );
    } finally {
      setReportBusy(false);
    }
  };

  const copyCardImage = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const el = article.current;
    if (!el || copyingImage) return;
    setCopyingImage(true);
    try {
      const { toBlob } = await import("html-to-image");
      const blob = await toBlob(el, {
        pixelRatio: 2,
        backgroundColor: getComputedStyle(document.body).backgroundColor || "#edf0ea",
        filter: (n) => {
          if (
            n instanceof HTMLElement &&
            (n.classList.contains("share-popover") || n.classList.contains("hero-tutorial-overlay"))
          ) {
            return false;
          }
          return true;
        },
      });
      if (blob) {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
        setCopiedImage(true);
        setTimeout(() => setCopiedImage(false), 2000);
      }
    } catch (err) {
      console.error("Failed to copy card image:", err);
    } finally {
      setCopyingImage(false);
    }
  };

  const copyShareLink = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const url = `${window.location.origin}/share/${card.id}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 2000);
    } catch (err) {
      console.error("Failed to copy link:", err);
    }
  };

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
  //
  // It now also has to be *earned*: an impression marks the card shown, which
  // makes it DEFERRED server-side and takes it out of rotation until this
  // difficulty's cycle comes round again. Firing the instant 50% of the card
  // crosses the viewport would let one fast flick burn a whole slate, so the
  // card must hold that visibility continuously for IMPRESSION_DWELL_MS. Scroll
  // away before then and the timer is cleared and re-armed next time.
  useEffect(() => {
    const el = article.current;
    if (el === null || impressed.current) return;

    let timer: ReturnType<typeof setTimeout> | null = null;
    const clear = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    };

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) {
          clear();
          return;
        }
        if (impressed.current || timer !== null) return;
        timer = setTimeout(() => {
          timer = null;
          impressed.current = true;
          engagement.record(card.id, "impression");
          observer.disconnect();
        }, IMPRESSION_DWELL_MS);
      },
      { threshold: 0.5 },
    );

    observer.observe(el);
    return () => {
      clear();
      observer.disconnect();
    };
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
      ([entry]) => {
        // An expanded card or hero card is in active reading mode — it must
        // NOT turn dull/scale down while the reader is scrolling through its
        // body, even if the top or bottom of the card is scrolled past.
        // It stays focused as long as it intersects the viewport.
        // Collapsed cards require at least 30% visibility to claim focus.
        if (expanded || isHero) {
          setFocused(entry.isIntersecting);
        } else {
          setFocused(entry.intersectionRatio > 0.3);
        }
      },
      { threshold: [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.75, 1] },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [expanded, isHero]);

  // Tap genuinely empty space — outside every card, not just this one — to
  // close it, and Escape too.
  //
  // A *tap*, matched across pointerdown/pointerup, not a bare pointerdown.
  // The feed scrolls at the window level, so the gaps between cards and the
  // page margins are also where a scroll gesture most often starts: on
  // pointerdown alone, one flick that happened to land 10px below a card
  // collapsed EVERY open card at once, and the thread jumped up by their
  // combined height mid-scroll. Requiring the pointer to come back up near
  // where it went down, quickly, separates "I tapped the background" from
  // "I started scrolling" without giving up the gesture on either mouse or
  // touch. Both ends are checked so a press that starts outside and drags
  // across the card still doesn't close it, which is what the old capture-
  // phase pointerdown listener was there to guarantee.
  //
  // A tap on a *different* card does NOT close this one — cards can be
  // expanded independently and simultaneously. Only one that lands outside
  // every `.card` (the gaps, the masthead, the margins) collapses this one.
  useEffect(() => {
    if (!expanded || isHero) return;

    let downX = 0;
    let downY = 0;
    let downTime = 0;

    const onPointerDown = (e: PointerEvent) => {
      // Only primary mouse button or touch.
      if (e.button !== 0) return;
      downX = e.clientX;
      downY = e.clientY;
      downTime = performance.now();
    };

    const onPointerUp = (e: PointerEvent) => {
      if (downTime === 0) return;
      const elapsed = performance.now() - downTime;
      downTime = 0;
      // Too slow to be a tap — likely the end of a scroll gesture.
      if (elapsed > TAP_MAX_MS) return;
      const dx = e.clientX - downX;
      const dy = e.clientY - downY;
      // Pointer moved too far — a drag/flick, not a tap in place.
      if (dx * dx + dy * dy > TAP_SLOP_PX * TAP_SLOP_PX) return;

      const target = e.target as HTMLElement | null;
      if (target === null) return;
      // Tapped inside ANY card or interactive UI (modals, dropdowns, actions)? Leave it alone.
      if (target.closest(".card, .modal-panel, .popover, .action, .topic-discovery-modal") !== null) {
        return;
      }
      collapse();
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") collapse();
    };

    window.addEventListener("pointerdown", onPointerDown, { capture: true });
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("keydown", onKeyDown);

    return () => {
      window.removeEventListener("pointerdown", onPointerDown, { capture: true });
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [expanded, isHero, collapse]);

  // Card dwell timer: accumulates time spent visible in the viewport, records
  // an engagement `dwell` event on unmount/visibility loss, and marks the card
  // seen once it has been read for DWELL_COMPLETE_MS continuously (ADR-0011).
  useEffect(() => {
    // Dwell timer ONLY runs when the card is expanded by the user (and not hero).
    // Unopened cards must NEVER be auto-marked as read.
    if (!expanded || isHero) return;

    const el = node.current;
    if (el === null) return;

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
  // testing branch — see lib/api.ts).
  const rawArt = card.visual_id !== null ? card.visual_slots?.art : undefined;
  const asciiArt = rawArt !== undefined && rawArt.trim() !== "" ? stripFenceWrapper(rawArt) : null;
  // The card's ONE lead visual. Rendered right after the title at full
  // height — collapsed and expanded alike — and suppressed from the body
  // render via `skipFenceKey`, so a diagram/code/art card never shows the
  // same block twice (see `resolveHero`).
  const hero = useMemo(
    () => resolveHero(archetype, card.body, asciiArt),
    [archetype, card.body, asciiArt],
  );

  return (
    <motion.div
      ref={node}
      className="node"
      data-read={seen}
      layout="position"
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
          style={
            accentHue !== null && accentHue !== undefined
              ? ({ "--topic-hue": accentHue } as CSSProperties)
              : undefined
          }
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

          {/* The lead visual sits where the summary/teaser normally goes — the
              FIRST thing after the title, standing in for the collapsed hook
              entirely. It is the SAME block the body would otherwise render,
              at its real height, not a one-line stand-in for it: `Markdown`
              below is told to skip that fence, so the card shows it exactly
              once whether collapsed or expanded. A card carrying more than
              one block still leads with only its primary type; the rest stay
              in the body where they were. */}
          {hero !== null ? (
            <HeroVisual hero={hero} alt={card.visual_slots?.alt} />
          ) : archetype === "comparison" ? (
            !expanded ? <ComparisonTeaser /> : null
          ) : (
            <p className="card-summary">{inline(normalizeText(card.summary))}</p>
          )}

          {/* `inert` while collapsed. Clipping to zero height hides the body
              visually but leaves it in the tab order, so keyboard users would
              otherwise tab through every collapsed card's hidden content. */}
          <div className="card-reveal" data-open={expanded} inert={!expanded}>
            <div className="card-reveal-body">
              <div className="card-body">
                <Markdown source={card.body} skipFenceKey={hero?.skipKey ?? null} />
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
                  // Write through so every OTHER mounted Card for this same
                  // card_id (Feed, Notes, Share...) updates immediately too
                  // -- see lib/engagementState.ts.
                  likedStore.set(card.id, !wasLiked);
                  // Let the caller's own optimistic removal (and any undo
                  // offer it makes) run BEFORE engagement.record, whose
                  // "unlike"/"unbookmark" branch synchronously invalidates
                  // the "liked" scope -- a caller that captures its row
                  // after that point would find its own state already
                  // cleared by the resulting refetch.
                  if (wasLiked) onUnliked?.(card.id);
                  engagement.record(card.id, wasLiked ? "unlike" : "like");
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
                  // Same write-through as the like button above.
                  bookmarkedStore.set(card.id, !wasBookmarked);
                  // Same ordering reason as the like button above, for the
                  // "saved" scope.
                  if (wasBookmarked) onUnbookmarked?.(card.id);
                  engagement.record(card.id, wasBookmarked ? "unbookmark" : "bookmark");
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

            <div className="share-action-wrap" ref={reportWrapRef}>
              <button
                className="action"
                data-on={reportOpen || reported}
                aria-label="Report this card"
                aria-expanded={reportOpen}
                onClick={(e) =>
                  act(e, () =>
                    setReportOpen((open) => {
                      if (open) setReportError(null);
                      return !open;
                    }),
                  )
                }
                type="button"
              >
                <FlagIcon />
              </button>
              {reportOpen ? (
                <div className="share-popover report-popover" onClick={(e) => e.stopPropagation()}>
                  {reported ? (
                    <div className="report-done">
                      <CheckIcon />
                      <span>Thanks — flagged for review.</span>
                    </div>
                  ) : (
                    <>
                      <div className="report-popover-head">What’s wrong with this card?</div>
                      {REPORT_REASONS.map((r) => (
                        <button
                          key={r.value}
                          type="button"
                          className="share-popover-item report-reason"
                          data-picked={reportReason === r.value}
                          onClick={() => {
                            setReportReason(r.value);
                            setReportError(null);
                          }}
                        >
                          <span className="report-dot" />
                          <span className="share-popover-text">{r.label}</span>
                        </button>
                      ))}
                      <textarea
                        className="report-note"
                        placeholder="What looks wrong? (optional)"
                        value={reportNote}
                        onChange={(e) => setReportNote(e.target.value)}
                        rows={2}
                      />
                      {reportError ? (
                        <div className="report-error" role="alert">
                          {reportError}
                        </div>
                      ) : null}
                      <div className="report-actions">
                        <button
                          type="button"
                          className="report-btn"
                          onClick={() => {
                            setReportOpen(false);
                            setReportError(null);
                          }}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className="report-btn report-btn-primary"
                          disabled={!reportReason || reportBusy}
                          onClick={() => void submitReport()}
                        >
                          {reportBusy ? "…" : "Report"}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ) : null}
            </div>

            <button
              className="action"
              data-on={askOpen}
              aria-label="Ask AI"
              aria-expanded={askOpen}
              onClick={(e) =>
                act(e, () => {
                  setAskOpen((open) => !open);
                  if (!askOpen) engagement.record(card.id, "ask_ai");
                })
              }
              type="button"
            >
              <SparkIcon />
            </button>

            <div className="share-action-wrap" ref={shareWrapRef}>
              <button
                className="action"
                aria-label="Share"
                aria-expanded={shareOpen}
                onClick={(e) =>
                  act(e, () => {
                    setShareOpen((open) => !open);
                    engagement.record(card.id, "share");
                  })
                }
                type="button"
              >
                <ShareIcon />
              </button>
              {shareOpen ? (
                <div className="share-popover" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    className="share-popover-item"
                    onClick={copyCardImage}
                    disabled={copyingImage}
                  >
                    <span className="share-popover-icon">
                      {copiedImage ? <CheckIcon /> : <PhotoIcon />}
                    </span>
                    <span className="share-popover-text">
                      {copyingImage ? "Rendering image…" : copiedImage ? "Image copied!" : "Copy as image"}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="share-popover-item"
                    onClick={copyShareLink}
                  >
                    <span className="share-popover-icon">
                      {copiedLink ? <CheckIcon /> : <LinkIcon />}
                    </span>
                    <span className="share-popover-text">
                      {copiedLink ? "Link copied!" : "Copy link"}
                    </span>
                  </button>
                </div>
              ) : null}
            </div>

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

          {/* AskAI panel — same always-mounted grid-rows reveal as the note
              panel above, for the same Framer-layout reason. */}
          <div
            className="card-note card-ask"
            data-open={askOpen}
            inert={!askOpen}
            onClick={(e) => e.stopPropagation()}
          >
            <AskPanel
              topicId={card.topic_id}
              cardId={card.id}
              topicName={topicName}
              active={askOpen}
            />
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
 *  exists here purely to pick which fenced block leads the card.
 *  `card.archetype` (server-derived) remains the single source of truth for
 *  WHICH archetype a card is; this never overrides it. */
const DIAGRAM_LANG_TAGS = new Set(["diagram", "text", "ascii", "table", ""]);
const DIAGRAM_CHARS_RE = /[─│┌└┐┘├┤┬┴┼→▶►]|-->|==>|──>|\+[-+]+\+|\|.*\|/;
const MERMAID_KEYWORDS_RE = /^\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|journey|gantt|pie|quadrantChart|requirementDiagram|gitGraph|mindmap|timeline|sankey-beta|xychart-beta|block-beta)\b/m;

function isMermaidFence(lang: string, content?: string): boolean {
  const normalized = lang.toLowerCase();
  if (normalized === "mermaid" || normalized === "flowchart") return true;
  if (content && MERMAID_KEYWORDS_RE.test(content)) return true;
  return false;
}

function isDiagramFence(lang: string, content: string): boolean {
  const normalized = lang.toLowerCase();
  if (normalized === "diagram" || normalized === "mermaid" || normalized === "flowchart") return true;
  if (MERMAID_KEYWORDS_RE.test(content)) return true;
  if (!DIAGRAM_LANG_TAGS.has(normalized)) return false;
  return DIAGRAM_CHARS_RE.test(content);
}

const FENCE_RE = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g;

interface Fence {
  lang: string;
  content: string;
  kind: "code" | "diagram";
}

function firstFenceOfKind(body: string, kind: "code" | "diagram"): Fence | null {
  for (const fence of fences(body)) {
    if (fence.kind === kind) return fence;
  }
  return null;
}

function firstFence(body: string): Fence | null {
  for (const fence of fences(body)) return fence;
  return null;
}

function* fences(body: string): Generator<Fence> {
  for (const match of normalizeText(body).matchAll(FENCE_RE)) {
    const [, lang, content] = match;
    yield {
      lang,
      content: content.replace(/\n$/, ""),
      kind: isDiagramFence(lang, content) ? "diagram" : "code",
    };
  }
}

/** Identity of a fenced block, independent of the trailing whitespace and
 *  fence wrapper that differ between `visual_slots.art` and the same scene
 *  as it appears inside `body`. Two blocks with the same key are the same
 *  block, so only one of them gets rendered — see `resolveHero`. */
function fenceKey(text: string): string {
  return text
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n")
    .trim();
}

/** Same question, asked loosely. `visual_slots.art` and the body's copy of
 *  the same scene routinely disagree about indentation and blank lines —
 *  they came out of two different generation slots. Two blocks made of the
 *  same non-whitespace characters in the same order are the same block, and
 *  a card must never show one twice. */
function looseFenceKey(text: string): string {
  return text.replace(/\s+/g, "");
}

/** Non-whitespace character count — a cheap proxy for "how much of the scene
 *  is actually drawn here", used to lead with the fuller of two copies. */
function nonWhitespaceLength(text: string): number {
  return text.replace(/\s+/g, "").length;
}

/** True when `visual_slots.art` and a body fence are the same drawing put
 *  into two different generation slots. Compared as whitespace-split token
 *  sets: the two copies routinely disagree on indentation, line breaks, and
 *  the odd character (`*slap*!` vs `*stap*!`), but share almost every token.
 *  A four-token floor on the smaller side stops a one-glyph art slot from
 *  colliding with an unrelated code fence. */
function sameScene(a: string, b: string): boolean {
  const tok = (s: string) => new Set(s.split(/\s+/).filter(Boolean));
  const ta = tok(a);
  const tb = tok(b);
  if (ta.size < 4 || tb.size < 4) return false;
  let shared = 0;
  for (const t of tb) if (ta.has(t)) shared++;
  return shared / Math.min(ta.size, tb.size) >= 0.6;
}

/** `visual_slots.art` is meant to hold raw ASCII, but the generator
 *  intermittently leaves the ```lang fence it drew the scene inside. Left
 *  alone those backticks render as literal text at the top of the card — the
 *  broken "Shared Storage: The Pod Volume" scene. Stripped here rather than
 *  in the prompt, per CLAUDE.md's "trusted for taste, never for constraints". */
function stripFenceWrapper(art: string): string {
  const text = normalizeText(art).replace(/^\n+/, "").replace(/\n+$/, "");
  const fenced = /^```[a-zA-Z0-9_-]*\n([\s\S]*?)\n?```$/.exec(text.trim());
  return fenced !== null ? fenced[1] : text;
}

/** The one visual block a card leads with. `skipKey` is what `Markdown`
 *  matches against so the body drops its own copy of the very same block. */
type HeroVisualBlock = { captioned?: boolean } & (
  | { kind: "ascii"; content: string; skipKey: string }
  | { kind: "diagram"; lang: string; content: string; skipKey: string }
  | { kind: "code"; lang: string; content: string; skipKey: string }
);

/** Picks the single block that leads the card, and nothing else — a card
 *  carrying both a code fence and a diagram leads with its PRIMARY type only
 *  (`getPrimaryArchetype`'s order), leaving the secondary block in the body
 *  where it already was.
 *
 *  A fenced block in `body` OUTRANKS `visual_slots.art`, and that ordering is
 *  the fix for a specific, real symptom rather than a preference. The two are
 *  filled by different generation slots and the model routinely draws the
 *  same picture into both — once in full in `body`, once abbreviated into
 *  `art` ("[ EPISTEMOLOGY ] (What do we know?)" becoming "[ EPIST. ] (What
 *  know?)"). Nothing here ever truncated anything: leading with `art` simply
 *  led with the model's own shorter redraw, which read as the app cropping
 *  the preview. The body's copy is the complete one, so it is the one shown,
 *  and `art` leads only when the body has no block of its own. */
function resolveHero(
  archetype: ArchetypeTag | "combo" | "default",
  body: string,
  art: string | null,
): HeroVisualBlock | null {
  const kind =
    archetype === "combo" || archetype === "code"
      ? "code"
      : archetype === "diagram"
        ? "diagram"
        : null;

  // Same scene in both slots: the model routinely draws one picture into
  // `visual_slots.art` AND into a body fence, one copy fuller than the other.
  // Lead with whichever is more complete, carry the caption, and let the body
  // drop its copy (`skipKey` targets the BODY fence either way). This replaces
  // the blanket "body always outranks art" rule, which broke on the cards
  // where the art slot held the full scene and the body held the short redraw.
  const lead = firstFence(body);
  if (art !== null && lead !== null && sameScene(art, lead.content)) {
    const skipKey = fenceKey(lead.content);
    if (nonWhitespaceLength(art) >= nonWhitespaceLength(lead.content)) {
      return { kind: "ascii", content: art, skipKey, captioned: true };
    }
    return lead.kind === "diagram"
      ? { kind: "diagram", lang: lead.lang, content: lead.content, skipKey, captioned: true }
      : { kind: "code", lang: lead.lang, content: lead.content, skipKey, captioned: true };
  }

  // Two reasons this falls through to ANY fence rather than stopping at
  // `kind`: an `art` slot present means the body fence is likely the fuller
  // twin of the same scene, worth preferring even off-kind; and a server/
  // client classification disagreement (`card.archetype` says "diagram" but
  // this component's own `isDiagramFence` reads the same fence differently)
  // must never mean the card loses its visual outright — it should show
  // WHATEVER fence body actually has, not fall back to a bare summary line.
  const fence =
    (kind !== null ? firstFenceOfKind(body, kind) : null) ??
    (art !== null || kind !== null ? firstFence(body) : null);

  if (fence !== null) {
    const skipKey = fenceKey(fence.content);
    return fence.kind === "diagram"
      ? { kind: "diagram", lang: fence.lang, content: fence.content, skipKey }
      : { kind: "code", lang: fence.lang, content: fence.content, skipKey };
  }

  if (art !== null) return { kind: "ascii", content: art, skipKey: fenceKey(art), captioned: true };
  return null;
}

/** `alt` is rendered as a visible caption under the lead visual (task F3) —
 *  but only when the visual actually IS the `visual_slots` scene: the plain
 *  `ascii` art, or a body fence resolved to be that same scene (`captioned`).
 *  A body fence that merely happens to lead an unrelated card gets no caption,
 *  since `alt` describes the art slot, not it. */
function HeroVisual({ hero, alt }: { hero: HeroVisualBlock; alt: string | undefined }) {
  const visual =
    hero.kind === "ascii" ? (
      <AsciiArt art={hero.content} alt={alt} />
    ) : hero.kind === "diagram" ? (
      <DiagramBlock lang={hero.lang} content={hero.content} />
    ) : (
      <CodeBlock lang={hero.lang} content={hero.content} />
    );
  return (
    <>
      {visual}
      {hero.captioned && alt ? <p className="card-visual-caption">{alt}</p> : null}
    </>
  );
}

/** Renders a card's ASCII scene (ADR-0021, or free-form model-drawn art).
 *  `role="img"` means a screen reader announces the `aria-label` rather than
 *  the raw `<pre>` glyphs. The visible caption is `HeroVisual`'s job now, so
 *  it can caption a same-scene diagram/code hero too, not just this branch. */
function AsciiArt({ art, alt }: { art: string; alt: string | undefined }) {
  return (
    <div className="card-ascii" role="img" aria-label={alt || "A hand-drawn ASCII scene"}>
      <pre>{art}</pre>
    </div>
  );
}

/** Minimal by design (ADR-0017 follow-up): the actual claim text is raw,
 *  occasionally-unparsed markdown from the generator, so the collapsed
 *  teaser shows only that a comparison exists, not its content. The full
 *  claim renders properly via ProseBlocks once expanded — a comparison's
 *  content IS the body, so unlike a diagram or code fence there is no
 *  standalone block to lift to the top without duplicating the whole card. */
function ComparisonTeaser() {
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
 *
 * `skipFenceKey` drops the FIRST fence whose content matches it — the card's
 * lead visual, already rendered above the body by `HeroVisual`. Only the
 * first: a body that genuinely repeats the same block twice keeps its second
 * copy, since that is the author's content, not this component's duplication.
 */
export function Markdown({ source, skipFenceKey }: { source: string; skipFenceKey?: string | null }) {
  const all = tokenize(source);
  const tokens: Token[] = [];
  let skipped = skipFenceKey === null || skipFenceKey === undefined;
  const loose = skipped ? "" : looseFenceKey(skipFenceKey!);
  for (const token of all) {
    if (!skipped && token.type === "fence" && looseFenceKey(token.content) === loose) {
      skipped = true;
      continue;
    }
    tokens.push(token);
  }

  return (
    <>
      {tokens.map((token, index) =>
        token.type === "fence" ? (
          token.kind === "diagram" ? (
            <DiagramBlock key={index} lang={token.lang} content={token.content} />
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
            <span className="comparison-tone-badge" data-tone={row.tone}>
              <span className="comparison-tone-icon">{row.tone === "bad" ? "❌" : "✅"}</span>
              <span className="comparison-tone-label">{row.tone === "bad" ? "Myth" : "Fact"}</span>
            </span>
            <div className="comparison-content">{inline(row.text)}</div>
          </div>
        ))}
      </div>,
    );
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.length === 0) {
      let nextNonEmpty = -1;
      for (let j = i + 1; j < lines.length; j++) {
        if (lines[j].trim().length > 0) {
          nextNonEmpty = j;
          break;
        }
      }
      if (
        nextNonEmpty !== -1 &&
        (/^❌\s*/.test(lines[nextNonEmpty].trim()) || /^✅\s*/.test(lines[nextNonEmpty].trim()))
      ) {
        i++;
        continue;
      }
      flushPairs();
      i++;
      continue;
    }

    // Comparison row (❌ / ✅)
    const badMatch = /^❌\s*([\s\S]*)$/.exec(trimmed);
    const goodMatch = /^✅\s*([\s\S]*)$/.exec(trimmed);
    if (badMatch !== null || goodMatch !== null) {
      let rowText = (badMatch ?? goodMatch)![1].trim();
      let nextI = i + 1;
      while (nextI < lines.length) {
        const nextTrimmed = lines[nextI].trim();
        if (
          nextTrimmed.length === 0 ||
          nextTrimmed.startsWith("❌") ||
          nextTrimmed.startsWith("✅") ||
          /^#{1,6}\s+/.test(nextTrimmed) ||
          /^[-*•]\s+/.test(nextTrimmed) ||
          /^\d+[.)]\s+/.test(nextTrimmed) ||
          nextTrimmed.startsWith(">") ||
          nextTrimmed.startsWith("$$") ||
          nextTrimmed.startsWith("\\[") ||
          (nextTrimmed.startsWith("|") && nextTrimmed.endsWith("|"))
        ) {
          break;
        }
        rowText += " " + nextTrimmed;
        nextI++;
      }
      pairBuffer.push({
        tone: badMatch !== null ? "bad" : "good",
        text: rowText,
      });
      i = nextI;
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

function DiagramBlock({ lang, content }: { lang: string; content: string }) {
  const [expanded, setExpanded] = useState(false);

  // A mermaid fence is a diagram whose layout the CLIENT owns, so it skips
  // the monospace box entirely rather than rendering its source as art.
  if (isMermaidFence(lang, content)) {
    return (
      <div className="diagram-block diagram-block-mermaid">
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
        <MermaidBlock source={content} />
        {expanded ? (
          <BlockModal title="Diagram" onClose={() => setExpanded(false)}>
            <div className="diagram-block diagram-block-mermaid">
              <MermaidBlock source={content} />
            </div>
          </BlockModal>
        ) : null}
      </div>
    );
  }

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
