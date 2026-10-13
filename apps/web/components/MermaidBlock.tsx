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

/** Every flowchart is drawn the same way whatever the palette (the owner,
 *  2026-10-13): a white ground, unfilled boxes outlined in black, black text
 *  and black lines. Only the typeface follows the theme. */
const INK = "#000000";
const PAPER = "#ffffff";

function themeVariables(el: HTMLElement): Record<string, string> {
  const font = getComputedStyle(el).getPropertyValue("--font-mono").trim();
  return {
    background: PAPER,
    primaryColor: PAPER,
    primaryTextColor: INK,
    primaryBorderColor: INK,
    secondaryColor: PAPER,
    tertiaryColor: PAPER,
    lineColor: INK,
    textColor: INK,
    mainBkg: PAPER,
    nodeBorder: INK,
    nodeTextColor: INK,
    clusterBkg: PAPER,
    clusterBorder: INK,
    edgeLabelBackground: PAPER,
    titleColor: INK,
    fontFamily: font || "ui-monospace, monospace",
    fontSize: "13px",
    actorBkg: PAPER,
    actorBorder: INK,
    actorTextColor: INK,
    activationBkgColor: PAPER,
    noteBkgColor: PAPER,
    noteTextColor: INK,
    noteBorderColor: INK,
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
          // "antiscript" cleans input using DOMPurify without creating
          // sandboxed iframes that get blocked by browser CORS/security
          // restrictions when accessing over local network/mobile HTTP.
          securityLevel: "antiscript",
          theme: "base",
          themeVariables: themeVariables(el),
          flowchart: { htmlLabels: false, useMaxWidth: true },
          sequence: { useMaxWidth: true },
          gantt: { useMaxWidth: true },
        });
        // Parse first with errors suppressed: generated diagram source is not
        // trusted to be valid mermaid (see the file docstring), and a failed
        // parse here is an EXPECTED outcome, not an exception. Going straight
        // to the fallback avoids `mermaid.render` throwing — which in Next dev
        // surfaces its internal `console.error` as a red error overlay for a
        // condition this component already handles.
        const ok = await mermaid.parse(source, { suppressErrors: true });
        if (!ok) {
          console.warn("Mermaid source did not parse; showing raw diagram source.");
          if (live) setFailed(true);
          return;
        }
        const { svg: rendered } = await mermaid.render(`spoin-mmd-${renderSeq++}`, source);
        if (live) setSvg(rendered);
      } catch (err) {
        console.warn("Mermaid render fell back to raw source:", err);
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
