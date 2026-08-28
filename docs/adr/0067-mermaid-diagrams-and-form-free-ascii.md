# ADR-0067: Mermaid for diagrams, and no required form for ASCII scenes

- **Status:** Accepted
- **Date:** 2026-08-28
- **Amends:** [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md) (the stickman
  requirement), [ADR-0017](0017-card-archetypes.md) (what a `diagram` card contains)
- **Related:** [ADR-0021](0021-ascii-scene-library.md), [ADR-0066](0066-redraw-over-budget-ascii-art.md)

## Context

Two problems surfaced together in the same feed session, and they turned out to have
the same root.

**Diagrams drawn as ASCII break silently.** The generator was asked to hand-draw
box-and-arrow diagrams into a ```text / ```diagram fence, aligning them by eye against
a column count it cannot see. That works in the model's own output and fails on a
phone: at roughly 38-42 monospace columns a box-drawn diagram does not reflow, it is
destroyed. ADR-0066 added a redraw pass for over-budget *ASCII scenes*, but a diagram
is the wrong thing to be solving with a width budget at all — the constraint is not
"fit in 40 columns", it is "the client should decide the layout".

**Every ASCII scene was the same joke.** ADR-0042's prompt made stick figures
mandatory ("using stick figures is a MUST"). One cast, one gag shape, on every card in
the corpus. The instruction was written to guarantee the art was *something*; what it
actually guaranteed was that it was always the same something.

A third, smaller thing fell out of the same review: the generator routinely drew the
same picture into both `visual_slots.art` and `body`, once in full and once
abbreviated — so the card led with the model's own shorter redraw and read as though
the app were cropping its own preview.

## Decision

**1. Diagram cards emit mermaid.** `CARDS_DIAGRAM_SYSTEM` now requires a ```mermaid
fence. The prompt describes what connects to what; it never draws the picture. The
client renders it (`apps/web/components/MermaidBlock.tsx`, dynamically imported so a
card without a diagram never pays for the library).

The prompt carries an explicit **shape** target, which matters as much as the content:
aim for a roughly square diagram — `flowchart TD` as the default primary axis, then
branch sideways so it does not degenerate into a narrow column; roughly 4-8 nodes,
2-4 rows deep, 2-3 nodes at the widest row; short labels. A card is taller than it is
wide, so vertical flow is right, but a one-node-per-row column is an endless scroll and
a left-to-right strip overflows. Square fills the card.

**2. Tables stay markdown.** Mermaid has no table diagram. Genuinely tabular material
uses a normal markdown pipe table, which already renders as a real `<table>`; ASCII
tables drawn from dashes and pipes are out for the same reason ASCII diagrams are.

**3. ASCII scenes have no required form.** The stickman requirement is removed
everywhere — planning, card generation, hero cards, curriculum, quality review. A scene
may be characters, a checklist, a before/after pair, a timeline whose ordering is the
joke, a tiny hash-bar chart, an object misbehaving, or pure typography. Faces are one
option among many. `ASCII_INSTRUCTIONS` now teaches this through seven worked examples
drawn from seven live topics (Gym, Gilgamesh, German, PostgreSQL, Financial Literacy,
10m Air Pistol, How Everyday Things Work), each a *different shape* of joke, each
annotated with what it is doing and why. The two hard rules (40 columns, works
stand-alone as a collapsed-card preview) are unchanged and still enforced outside the
model per CLAUDE.md's "trusted for taste, never for constraints".

**4. One block per card, and it is the full one.** `resolveHero` in `Card.tsx` picks a
single lead visual, renders it once at the top in both the collapsed and expanded
state, and suppresses the body's copy of it. A fenced block in `body` outranks
`visual_slots.art`, because when both are filled with the same picture the body's is
the complete one. The prompt also now says outright not to reproduce the scene in
`body`.

## Consequences

**Backward compatible by construction, no migration.** Dispatch is on the fence's
language tag. Every existing card's ```text / ```diagram block still renders in the
monospace box exactly as it did; only a ```mermaid fence takes the new path. The ~9,000
cards already in `spoin_db` are untouched and nothing is re-generated. The corpus will
carry both shapes indefinitely, which is correct — an old card is not wrong, it is old.

**Mermaid is generated content and is not trusted.** It renders with
`securityLevel: "strict"` (no click handlers, no inline HTML in labels), and a diagram
that fails to parse falls back to showing its source in the monospace box rather than
rendering blank. A malformed diagram degrades to exactly what an ASCII diagram would
have been.

**Theming follows the palette.** Mermaid's theme variables are filled from the live
CSS tokens at render time rather than hardcoded, so a diagram tracks the five shipped
palettes (ADR-0012), a custom theme, and the per-topic accent (ADR-0034).

**The width-redraw pass (ADR-0066) now applies only to ASCII scenes**, which is the
only place a column budget still means anything. It is not weakened; its scope simply
stopped including diagrams.

## Alternatives considered

**Keep ASCII diagrams and lean harder on the redraw pass.** Rejected: the redraw fixes
a line that is too wide, but the underlying model still has to do layout arithmetic
blind. Mermaid removes the arithmetic instead of correcting it after the fact — the
same reasoning as deriving `archetype` rather than asking for it (ADR-0017).

**Render mermaid server-side and store the SVG.** Rejected for now: it would put a
rendering dependency in the write path and freeze the diagram's theme at generation
time, which breaks palette switching. Client-side rendering keeps the stored content as
structure, which is the thing worth storing.

**Migrate existing ASCII diagrams to mermaid.** Rejected: it means an LLM pass over
~9,000 production cards to convert content that currently renders fine, against
CLAUDE.md's rules on touching real data. New cards get the better shape; old cards keep
working.
