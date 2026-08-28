# ADR-0069: Client-side Mermaid rendering resilience, and card focus/dwell guards

- **Status:** Accepted
- **Date:** 2026-08-29
- **Deciders:** Anubhav
- **Amends:** [ADR-0067](0067-mermaid-diagrams-and-form-free-ascii.md) (mermaid rendering),
  [ADR-0017](0017-card-archetypes.md) (card focus pull and read lifecycle)
- **Related:** [ADR-0011](0011-engagement.md), [ADR-0064](0064-mobile-shell-tab-bar.md)

## Context

Three distinct problems surfaced during the first mobile feed session after the
Bhagvad Geeta and Rust topic generation runs, all on mobile Safari over a local
network address (`http://192.168.1.34`).

**1. Mermaid diagrams rendered as raw source code.**  Every ```mermaid fence showed
its raw `flowchart TD …` text inside a monospace box instead of an SVG diagram.
Two causes combined:

- **`securityLevel: "strict"` creates a sandboxed `<iframe>`.**  Mermaid v11's
  "strict" mode evaluates diagram source inside a sandboxed iframe.  On a mobile
  browser accessing the app over HTTP on a local IP, the iframe's cross-origin
  sandbox blocked access to the host document's stylesheets, throwing an error.
  The `MermaidBlock.tsx` catch block swallowed the error silently and fell back to
  the `<pre>` source box — the design-time "malformed diagram" path, now firing
  on every valid diagram.

- **`mermaid` was not installed inside the Docker container.**  The web container's
  `node_modules` volume was built before `mermaid` was added to `package.json`,
  so the dynamic `import("mermaid")` inside the production bundle threw
  `Cannot find module 'mermaid'`.

- **Fence-tag detection was too narrow.**  `isMermaidFence` only matched the
  literal language tag `mermaid`.  The generator sometimes emits a ```flowchart
  or an unlabelled fence whose body starts with `flowchart TD`, `graph LR`,
  `sequenceDiagram`, etc.  Those fell through to `CodeBlock` instead of
  `DiagramBlock → MermaidBlock`.

**2. Expanded cards turned dull while scrolling.**  The focus-pull
`IntersectionObserver` required `intersectionRatio > 0.6` unconditionally — a
60% visibility threshold.  An expanded card is taller than the viewport, so
scrolling its body past the midpoint caused the card to dim (`scale: 0.97`,
`opacity: 0.6`) while the reader was actively reading it.

**3. Unopened cards were auto-marked as read.**  The dwell timer effect lost its
`if (!expanded || isHero) return;` guard during the focus-pull refactor.  Every
card in the viewport — collapsed or expanded — started accumulating dwell time,
marking collapsed cards as read after 10 seconds of being visible in the feed
without the reader ever opening them.

**4. Content jump on mark-read.**  Framer Motion's `layout` prop on the outer
`.node` wrapper tracked both position and size.  When the `· Read` badge appeared
in the card header, the height change triggered a layout animation that visibly
shifted the card body downward.

**5. Mobile Safari zoom on notes input.**  The notes `<textarea>` had
`font-size: 13px`.  iOS Safari auto-zooms the viewport on any input with a font
size below 16px, making the screen jump when the user tapped to type a note.

## Decision

### Mermaid rendering (amends ADR-0067)

1. **Switch `securityLevel` from `"strict"` to `"antiscript"`.**  `"antiscript"`
   uses DOMPurify to sanitize diagram output directly in the main document,
   without creating a sandboxed iframe.  Click handlers and inline HTML in labels
   remain stripped — the security posture for generated content is unchanged;
   only the transport mechanism (iframe vs. DOMPurify) is different.

2. **Install `mermaid` inside the running container**, and ensure future
   container builds include it.  (The host `package.json` already listed it; the
   issue was the stale container volume.)

3. **Broaden `isMermaidFence` to detect diagram syntax by content.**  A new
   `MERMAID_KEYWORDS_RE` regex matches the first line of the fence body against
   all standard Mermaid diagram types (`flowchart`, `graph`, `sequenceDiagram`,
   `classDiagram`, `stateDiagram`, `erDiagram`, `journey`, `gantt`, `pie`,
   `quadrantChart`, `requirementDiagram`, `gitGraph`, `mindmap`, `timeline`,
   `sankey-beta`, `xychart-beta`, `block-beta`).  The lang tag `"flowchart"` is
   also accepted directly.  This runs on both `isMermaidFence` and
   `isDiagramFence`.

4. **Log render errors.**  The `catch` block in `MermaidBlock.tsx` now
   `console.error`s the error before falling back — a silent swallow made the
   original iframe failure invisible.

### Card focus pull (amends ADR-0017)

5. **An expanded or hero card stays focused while any part of it is visible.**
   The `IntersectionObserver` callback now checks `entry.isIntersecting` (any
   pixel on screen) for expanded/hero cards, rather than requiring 60% coverage.
   Collapsed cards use a 30% threshold — relaxed from 60% to avoid premature
   dimming during normal browsing.

6. **The observer re-subscribes when `expanded` or `isHero` changes**, so the
   threshold switch takes effect immediately on expand/collapse.

### Dwell timer guard

7. **The dwell timer exits early when the card is not expanded or is a hero.**
   `if (!expanded || isHero) return;` is restored as the first line of the dwell
   effect.  Collapsed cards never accumulate dwell time and are never
   auto-marked as read.

### Layout stability

8. **Framer Motion uses `layout="position"` instead of `layout` (full).**
   Position-only layout animation tracks where the card moves but not its size,
   so internal height changes (the `· Read` badge appearing, note area opening)
   no longer trigger a visible content jump.

9. **The `· Read` badge is hidden on expanded cards at mobile widths.**  A
   `@media (max-width: 768px)` rule sets `display: none` on
   `.card[data-expanded="true"] .card-read`.  This eliminates the header-row
   reflow that was the remaining source of the content shift on mobile.

### Mobile input zoom

10. **Notes textarea font-size raised to 16px.**  iOS Safari's auto-zoom
    threshold is 16px; anything below triggers a viewport scale change on focus.

11. **Viewport meta adds `maximum-scale=1`.**  The `layout.tsx` viewport export
    now includes `width: "device-width"`, `initialScale: 1`, `maximumScale: 1`,
    preventing double-tap and input-focus zoom entirely.

## Consequences

- Mermaid diagrams render as interactive SVGs on every browser and network
  context tested (mobile Safari over HTTP LAN, desktop Chrome, Firefox).
- A card whose body is taller than the viewport can be scrolled through without
  dimming or losing focus.
- Collapsed cards in the feed are never auto-marked as read by dwell time;
  only the explicit ✓ button or expanded-dwell completes them.
- The `· Read` badge remains visible on collapsed cards (both mobile and desktop)
  and on expanded cards on desktop; it is hidden on expanded cards on mobile
  only, where the header-row width is too narrow for it to sit without causing
  reflow.
- Mobile notes input no longer triggers viewport zoom.
- `securityLevel: "antiscript"` is marginally less strict than `"strict"` in
  theory (no iframe sandbox boundary), but DOMPurify's sanitization covers the
  same attack surface for generated content that never contains user-authored
  script.  Revisit if user-authored mermaid is ever accepted.

## Files changed

| File | What changed |
|---|---|
| `apps/web/components/MermaidBlock.tsx` | `securityLevel` → `"antiscript"`, error logging |
| `apps/web/components/Card.tsx` | `isMermaidFence` broadened with `MERMAID_KEYWORDS_RE`; focus observer threshold split by expanded/hero; dwell timer guard restored; `layout` → `layout="position"`; `isMermaidFence` call passes content |
| `apps/web/app/globals.css` | `.card-read` hidden on expanded cards at ≤768px; `.card-note-input` font-size → 16px |
| `apps/web/app/layout.tsx` | Viewport adds `width`, `initialScale`, `maximumScale` |

## Revisit when

- User-authored mermaid content is accepted (re-evaluate `"antiscript"` vs.
  `"strict"` or `"sandbox"`).
- A container orchestration layer (Kubernetes, Fly) manages image builds — the
  manual `npm install mermaid` inside the running container is a one-time fix;
  the Dockerfile should be the single source of truth for dependencies.
