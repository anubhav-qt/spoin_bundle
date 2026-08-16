"use client";

/**
 * One card in the thread.
 *
 * The collapsed state carries the whole surface content-model.md asks for:
 * topic, difficulty, title, summary hook, read state, and all six actions —
 * like, bookmark, note, ask AI, share, got it. Nothing waits for expansion,
 * "got it" included: it is reachable as the circular icon at the far right
 * of the action row whether or not the card has ever been opened.
 *
 * Tapping the card toggles it open and closed. Tapping it again, tapping
 * anywhere outside it, or Escape all close it — expanded is a mode the
 * reader steps into and back out of, not a one-way reveal.
 *
 * This component owns the interaction, never the rules. What counts as SEEN and
 * what the dwell threshold means belong to the API. It reports what happened,
 * honestly and separately:
 *
 *   expand            -> sent promptly; progression depends on it
 *   explicit_complete -> they tapped "Got it"
 *   dwell_complete    -> they stayed past the threshold
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { Card as CardModel, Difficulty } from "@/lib/api";
import { DwellTimer, engagement } from "@/lib/engagement";
import { BookmarkIcon, CheckIcon, HeartIcon, NoteIcon, ShareIcon, SparkIcon } from "./icons";

/** Mirrors SLOCHO_DWELL_COMPLETE_MS. The server stays the authority; this only
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
  seen: boolean;
  onSeen: (cardId: string) => void;
  onUnseen: (cardId: string) => void;
}

export function Card({ card, topicName, seen, onSeen, onUnseen }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [liked, setLiked] = useState(false);
  const [bookmarked, setBookmarked] = useState(false);
  // Gates the action-row "Got it" icon: disabled until the card has been
  // opened at least once. Sticks after collapsing — this tracks "opened this
  // session", not "currently open". See ADR-0012's "Card interaction"
  // section: without this gate the icon lets SEEN happen with zero reading,
  // which is exactly what ADR-0010's "expansion is required" rule exists to
  // prevent.
  const [everExpanded, setEverExpanded] = useState(false);

  const dwell = useRef(new DwellTimer());
  const article = useRef<HTMLElement>(null);
  const impressed = useRef(false);

  const collapse = useCallback(() => {
    setExpanded(false);
    engagement.record(card.id, "collapse");
  }, [card.id]);

  // An impression is logged when the card actually enters the viewport, not on
  // render. Without a true denominator `card_quality` is not a rate, and a rate
  // is the only thing stopping old cards dominating the ranker forever.
  useEffect(() => {
    const node = article.current;
    if (node === null || impressed.current) return;

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

    observer.observe(node);
    return () => observer.disconnect();
  }, [card.id]);

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
    if (!expanded) return;

    const onPointerDown = (event: PointerEvent) => {
      const node = article.current;
      const target = event.target as HTMLElement;
      if (node !== null && !node.contains(target) && target.closest(".card") === null) {
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
  }, [expanded, collapse]);

  // Dwell accrues only while expanded AND the page is visible. A tab left open
  // overnight is not a nine-hour read.
  useEffect(() => {
    if (!expanded) return;

    const timer = dwell.current;
    timer.start();

    const onVisibility = () => {
      if (document.visibilityState === "hidden") timer.pause();
      else timer.start();
    };
    document.addEventListener("visibilitychange", onVisibility);

    const threshold = setTimeout(() => {
      if (document.visibilityState !== "visible") return;
      engagement.record(card.id, "dwell_complete", timer.elapsedMs);
      onSeen(card.id);
    }, DWELL_COMPLETE_MS);

    return () => {
      clearTimeout(threshold);
      document.removeEventListener("visibilitychange", onVisibility);
      timer.pause();
      if (timer.elapsedMs > 0) engagement.record(card.id, "dwell", timer.elapsedMs);
    };
  }, [expanded, card.id, onSeen]);

  // Clicking the card anywhere outside the action row toggles it — open if
  // collapsed, closed if already expanded. Symmetric with the click-outside
  // and Escape handlers above, which cover the "closed by something other
  // than the card itself" cases this doesn't.
  const toggle = () => {
    if (expanded) {
      collapse();
      return;
    }
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

  return (
    <div className="node" data-read={seen}>
      <article
        ref={article}
        className="card"
        data-expanded={expanded}
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
        </div>

        <h2 className="card-title">{card.title}</h2>
        <p className="card-summary">{card.summary}</p>

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
  );
}

/**
 * The smallest markdown renderer covering what the generator emits: headings,
 * paragraphs, bullets, bold, inline code.
 *
 * A full library is ~40kB for features we do not use, and this never touches
 * `innerHTML` — worth caring about when card bodies come from a model.
 */
function Markdown({ source }: { source: string }) {
  const blocks = source.trim().split(/\n{2,}/);

  return (
    <>
      {blocks.map((block, index) => {
        const heading = /^(#{1,3})\s+(.*)$/.exec(block);
        if (heading !== null) {
          const Tag = `h${heading[1].length}` as "h1" | "h2" | "h3";
          return <Tag key={index}>{inline(heading[2])}</Tag>;
        }

        if (/^[-*]\s+/m.test(block)) {
          const items = block.split("\n").filter((line) => /^[-*]\s+/.test(line));
          return (
            <ul key={index}>
              {items.map((item, i) => (
                <li key={i}>{inline(item.replace(/^[-*]\s+/, ""))}</li>
              ))}
            </ul>
          );
        }

        return <p key={index}>{inline(block)}</p>;
      })}
    </>
  );
}

function inline(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    return <span key={index}>{part}</span>;
  });
}
