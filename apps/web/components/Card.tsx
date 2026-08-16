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
 * anywhere OUTSIDE the card, or Escape all close it.  Swiping right is
 * an ALTERNATE gesture for the same "mark seen" action as the checkmark
 * (ADR-0017) — not a new business rule — but it additionally removes the
 * card from view (`onDismiss`), which tapping the checkmark does not do.
 *
 * This component owns the interaction, never the rules. What counts as SEEN and
 * what the dwell threshold means belong to the API. It reports what happened,
 * honestly and separately:
 *
 *   expand            -> sent promptly; progression depends on it
 *   explicit_complete -> they tapped "Got it" OR swiped to dismiss
 *   dwell_complete    -> they stayed past the threshold
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { motion, type PanInfo } from "framer-motion";

import type { ArchetypeTag, Card as CardModel, Difficulty } from "@/lib/api";
import { DwellTimer, engagement } from "@/lib/engagement";
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

/** Mirrors SLOCHO_DWELL_COMPLETE_MS. The server stays the authority; this only
 *  decides when the client stops waiting and reports. */
const DWELL_COMPLETE_MS = 8000;

/** Swipe-right threshold to count as a dismiss rather than an incidental drag. */
const DISMISS_OFFSET_X = 120;
const DISMISS_VELOCITY_X = 500;

const DIFFICULTY_RANK: Record<Difficulty, number> = {
  beginner: 1,
  intermediate: 2,
  advanced: 3,
};

interface Props {
  card: CardModel;
  topicName: string;
  seen: boolean;
  onSeen: (cardId: string) => void;
  onUnseen: (cardId: string) => void;
  onDismiss: (cardId: string) => void;
  /** "First card in this station" — a feed-layout placeholder for real
   *  curation, not a property of the card (ADR-0017, docs/tasks/0006). */
  isHero: boolean;
}

export function Card({ card, topicName, seen, onSeen, onUnseen, onDismiss, isHero }: Props) {
  // Hero never collapses: starting `expanded` (and `everExpanded`) true and
  // making `toggle` a no-op for hero reuses every bit of existing dwell/reveal
  // logic below instead of forking a parallel code path for it.
  const [expanded, setExpanded] = useState(isHero);
  const [liked, setLiked] = useState(false);
  const [bookmarked, setBookmarked] = useState(false);
  const [everExpanded, setEverExpanded] = useState(isHero);
  const [focused, setFocused] = useState(true);

  const dwell = useRef(new DwellTimer());
  const article = useRef<HTMLElement>(null);
  const node = useRef<HTMLDivElement>(null);
  const impressed = useRef(false);
  const dragging = useRef(false);

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
    if (!expanded) return;

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
  // than the card itself" cases this doesn't. No-op for hero (never collapses)
  // and swallowed right after a genuine drag release, so a swipe doesn't also
  // register as a tap.
  const toggle = () => {
    // Opens a collapsed card. Once expanded, a tap on the body is a no-op —
    // closing happens only via the explicit × (below) or clicking outside.
    if (isHero || dragging.current || expanded) return;
    setExpanded(true);
    setEverExpanded(true);
    engagement.record(card.id, "expand");
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

  const onDragEnd = (_event: PointerEvent | MouseEvent | TouchEvent, info: PanInfo) => {
    const wasDragging = dragging.current;
    // Cleared on a delay rather than immediately — the synthetic click that
    // follows a drag release fires right after this, and `toggle` checks the
    // ref synchronously in that click's handler.
    setTimeout(() => {
      dragging.current = false;
    }, 0);
    if (!wasDragging) return;

    if (info.offset.x > DISMISS_OFFSET_X || info.velocity.x > DISMISS_VELOCITY_X) {
      if (!seen) {
        engagement.record(card.id, "explicit_complete", dwell.current.elapsedMs);
        onSeen(card.id);
      }
      onDismiss(card.id);
    }
  };

  const archetype = getPrimaryArchetype(card.archetype);

  return (
    <motion.div
      ref={node}
      className="node"
      data-read={seen}
      layout
      drag={isHero ? false : "x"}
      dragDirectionLock
      dragConstraints={{ left: 0, right: 0 }}
      dragElastic={{ left: 0.15, right: 0.6 }}
      onDragStart={() => {
        dragging.current = true;
      }}
      onDragEnd={onDragEnd}
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

          <h2 className="card-title">{card.title}</h2>

          {archetype === "default" ? (
            <p className="card-summary">{card.summary}</p>
          ) : !expanded ? (
            <ArchetypeTeaser archetype={archetype} body={card.body} />
          ) : null}

          {/* `inert` while collapsed. Clipping to zero height hides the body
              visually but leaves it in the tab order, so keyboard users would
              otherwise tab through every collapsed card's hidden content. */}
          <div className="card-reveal" inert={!expanded}>
            <div>
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
                  setLiked(!liked);
                  engagement.record(card.id, liked ? "unlike" : "like");
                })
              }
              type="button"
            >
              <HeartIcon />
            </button>

            <button
              className="action"
              data-on={bookmarked}
              aria-pressed={bookmarked}
              aria-label="Save"
              onClick={(e) =>
                act(e, () => {
                  setBookmarked(!bookmarked);
                  engagement.record(card.id, bookmarked ? "unbookmark" : "bookmark");
                })
              }
              type="button"
            >
              <BookmarkIcon />
            </button>

            <button
              className="action"
              aria-label="Note"
              onClick={(e) => act(e, () => engagement.record(card.id, "note"))}
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
        </article>
      </div>
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

/** Presentation-only mirror of content/archetype.py's diagram heuristic — it
 *  exists here purely to pick which fenced block to preview in the collapsed
 *  teaser. `card.archetype` (server-derived) remains the single source of
 *  truth for WHICH archetype a card is; this never overrides it. */
const DIAGRAM_LANG_TAGS = new Set(["diagram", "text", "ascii", ""]);
const DIAGRAM_CHARS_RE = /[─│┌└┐┘├┤┬┴┼→▶►]|-->|==>|──>/;

function isDiagramFence(lang: string, content: string): boolean {
  const normalized = lang.toLowerCase();
  if (normalized === "diagram") return true;
  if (!DIAGRAM_LANG_TAGS.has(normalized)) return false;
  return DIAGRAM_CHARS_RE.test(content);
}

const FENCE_RE = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g;

function firstFenceOfKind(body: string, kind: "code" | "diagram"): { lang: string; content: string } | null {
  for (const match of body.matchAll(FENCE_RE)) {
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
  const boldClaim = new RegExp(`${marker}\\s*\\*\\*([^*]+)\\*\\*`).exec(body);
  if (boldClaim !== null) return boldClaim[1].trim();

  const line = new RegExp(`${marker}\\s*([^\\n]+)`).exec(body);
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

/**
 * The smallest markdown renderer covering what the generator emits: headings,
 * paragraphs, bullets, bold, inline code, fenced code/diagram blocks, and
 * ❌/✅ comparison pairs (ADR-0017).
 *
 * A full library is ~40kB for features we do not use, and this never touches
 * `innerHTML` — worth caring about when card bodies come from a model.
 */
function Markdown({ source }: { source: string }) {
  const tokens = tokenize(source.trim());

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

/** Fences are extracted BEFORE paragraph splitting — a fenced block's own
 *  blank lines would otherwise get corrupted by the `\n{2,}` prose splitter.
 *
 *  Only the FIRST fence of each kind (code/diagram) becomes a token — content
 *  generation should never stuff more than one of either into a single card,
 *  but if it does, silently rendering nothing for the extras keeps the card
 *  predictable instead of guessing which one "deserves" the space or falling
 *  back to raw fenced text as prose. */
function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let lastIndex = 0;
  const seen: Record<"code" | "diagram", boolean> = { code: false, diagram: false };

  for (const match of source.matchAll(FENCE_RE)) {
    const [full, lang, content] = match;
    const index = match.index ?? 0;
    if (index > lastIndex) tokens.push({ type: "prose", text: source.slice(lastIndex, index) });

    const kind = isDiagramFence(lang, content) ? "diagram" : "code";
    if (!seen[kind]) {
      seen[kind] = true;
      tokens.push({ type: "fence", lang, content: content.replace(/\n$/, ""), kind });
    }

    lastIndex = index + full.length;
  }

  if (lastIndex < source.length) tokens.push({ type: "prose", text: source.slice(lastIndex) });
  return tokens;
}

function ProseBlocks({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/).filter((block) => block.trim().length > 0);
  const nodes: React.ReactNode[] = [];
  let pairBuffer: { tone: "bad" | "good"; text: string }[] = [];

  const flushPair = (key: string) => {
    if (pairBuffer.length === 0) return;
    const rows = pairBuffer;
    pairBuffer = [];
    nodes.push(
      <div className="comparison-pair" key={key}>
        {rows.map((row, i) => (
          <div className="comparison-row" data-tone={row.tone} key={i}>
            {inline(row.text)}
          </div>
        ))}
      </div>,
    );
  };

  blocks.forEach((block, index) => {
    const bad = /^❌\s*([\s\S]*)$/.exec(block);
    const good = /^✅\s*([\s\S]*)$/.exec(block);
    if (bad !== null || good !== null) {
      pairBuffer.push({ tone: bad !== null ? "bad" : "good", text: (bad ?? good)![1] });
      return;
    }
    flushPair(`pair-${index}`);

    const heading = /^(#{1,3})\s+(.*)$/.exec(block);
    if (heading !== null) {
      const Tag = `h${heading[1].length}` as "h1" | "h2" | "h3";
      nodes.push(<Tag key={index}>{inline(heading[2])}</Tag>);
      return;
    }

    if (/^[-*]\s+/m.test(block)) {
      const items = block.split("\n").filter((line) => /^[-*]\s+/.test(line));
      nodes.push(
        <ul key={index}>
          {items.map((item, i) => (
            <li key={i}>{inline(item.replace(/^[-*]\s+/, ""))}</li>
          ))}
        </ul>,
      );
      return;
    }

    nodes.push(<p key={index}>{inline(block)}</p>);
  });
  flushPair("pair-final");

  return <>{nodes}</>;
}

function inline(text: string): React.ReactNode[] {
  // Bold matches before single-asterisk emphasis in the alternation — for a
  // `**bold**` run, the engine tries `\*\*...\*\*` at that position first and
  // it succeeds, so the single-star pattern never gets a chance to split it
  // into two bogus emphasis runs.
  return text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return <code key={index}>{part.slice(1, -1)}</code>;
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
