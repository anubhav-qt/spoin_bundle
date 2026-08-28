"use client";

/**
 * Renders a ```mermaid fence as a real diagram.
 *
 * Mermaid replaces hand-drawn ASCII box art for anything whose meaning is in
 * how parts connect — see the diagram instructions in
 * `generation/prompts/cards.py`. ASCII diagrams were the previous shape and
 * they fail in a way that is invisible to the model writing them: alignment
 * that holds in the model's own head breaks at a phone's ~40 monospace
 * columns, and a wrapped box-drawing is corrupted, not merely reflowed.
 * A mermaid graph carries the STRUCTURE and lets the client lay it out at
 * whatever width it actually has.
 *
 * The library is ~500KB, so it is imported dynamically inside the effect
 * rather than at module scope: a card with no mermaid fence never pays for
 * it, and the feed's first paint never waits on it.
 *
 * A diagram that fails to parse falls back to showing its source in the
 * monospace box, exactly as an ASCII diagram would have rendered. Generated
 * content is not trusted to be syntactically valid, and a card whose diagram
 * is malformed must still be readable rather than blank.
 */

import { useEffect, useRef, useState } from "react";

/** Bumped per render so two diagrams on one page never collide on the id
 *  mermaid uses internally for its own `<svg>` and its defs. */
let renderSeq = 0;

/** Mermaid's own palette knobs, filled from the live palette's tokens
 *  (ADR-0012/0034) rather than hardcoded, so a diagram follows the same
 *  theme switch every other surface does — including the five shipped
 *  palettes and any custom one from CustomThemeModal. */
function themeVariables(el: HTMLElement): Record<string, string> {
  const style = getComputedStyle(el);
  const token = (name: string, fallback: string) =>
    style.getPropertyValue(name).trim() || fallback;

  const fg = token("--fg", "#262a22");
  const fg2 = token("--fg-2", "#565f51");
  const bg2 = token("--bg-2", "#e2e7de");
  const bg3 = token("--bg-3", "#d6ddd1");
  const line = token("--line-strong", "rgba(38,42,34,0.26)");
  const accent = token("--topic-accent", "") || token("--accent", "#c1442b");

  return {
    background: "transparent",
    primaryColor: bg3,
    primaryTextColor: fg,
    primaryBorderColor: line,
    secondaryColor: bg2,
    tertiaryColor: bg2,
    lineColor: fg2,
    textColor: fg,
    mainBkg: bg3,
    nodeBorder: line,
    clusterBkg: bg2,
    clusterBorder: line,
    edgeLabelBackground: bg2,
    titleColor: fg,
    fontFamily: token("--font-mono", "ui-monospace, monospace"),
    fontSize: "13px",
    // Sequence/flowchart accents, so an "active" or highlighted node picks up
    // the card's own topic hue instead of mermaid's default blue.
    actorBkg: bg3,
    actorBorder: accent,
    activationBkgColor: bg2,
    noteBkgColor: bg2,
    noteTextColor: fg,
    noteBorderColor: line,
  };
}

export function MermaidBlock({ source }: { source: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = host.current;
    if (el === null) return;
    let live = true;

    void (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          // Generated content: never let a diagram inject markup into the
          // feed. "strict" also disables click handlers and inline HTML in
          // labels, neither of which a learning card has any use for.
          securityLevel: "strict",
          theme: "base",
          themeVariables: themeVariables(el),
          flowchart: { htmlLabels: false, useMaxWidth: true },
          sequence: { useMaxWidth: true },
          gantt: { useMaxWidth: true },
        });
        const { svg: rendered } = await mermaid.render(`spoin-mmd-${renderSeq++}`, source);
        if (live) setSvg(rendered);
      } catch {
        // Malformed diagram source — fall through to the raw-source box below.
        if (live) setFailed(true);
      }
    })();

    return () => {
      live = false;
    };
  }, [source]);

  if (failed) {
    return (
      <div className="diagram-block">
        <pre>{source}</pre>
      </div>
    );
  }

  return (
    <div className="mermaid-block" ref={host}>
      {svg === null ? (
        // Reserves height while the library loads, so a card doesn't jump
        // once the diagram paints — same reason CardSkeleton exists.
        <div className="mermaid-block-loading mono" aria-hidden="true">
          drawing…
        </div>
      ) : (
        <div className="mermaid-block-svg" dangerouslySetInnerHTML={{ __html: svg }} />
      )}
    </div>
  );
}
