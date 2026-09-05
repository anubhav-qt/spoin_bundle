# ADR-0098: The ASCII box rule is measured before it is enforced

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** project owner

> **See also [ADR-0099](0099-ascii-scenes-carry-their-own-explanation.md) (2026-09-05):** it applies this ADR's measure-first posture to the neighbouring question of text ON the art, and adds to `_ASCII_BOX` the one fact the box rule never stated — that height is unbounded, so a caption that will not fit beside a figure moves to its own line instead of being cut.

## Context

`ASCII_INSTRUCTIONS` rule 3 (BOX INTEGRITY, STRICT) says the art is a rigid box:
nothing edited inside it, nothing inserted to its **left** — which misaligns every
monospace column below the insertion — captions only top, bottom, or appended right,
total width ≤ 40 columns.

It is enforced **by prompt instruction alone.** The neighbouring rule about width is
not: `_ascii_over_budget_lines` measures every line server-side, and
[ADR-0066](0066-redraw-over-budget-ascii-art.md) hands an over-budget drawing back to be
redrawn rather than dropping the visual. So one half of the same instruction block has a
real check and a redraw loop, and the other half ships whatever the model returns.

That is CLAUDE.md's "the generator is trusted for taste, never for constraints" pointing
at a live gap. Box integrity is not taste — it is either true of a drawing or it is not,
and a violation is *silent*: misaligned art renders as art, just wrong, on a phone-width
column where nobody is looking closely. [ADR-0090](0090-hybrid-gemini-mistral-generation.md)
sharpens it: a smaller drafting model is exactly the condition under which
instruction-only rules start failing, and the hybrid plan puts one on the drafting path.

**The asymmetry that shapes every option.** For a **fetched** scene
([ADR-0080](0080-ascii-fetcher-node.md)) the original library
art exists and the card records its `src_id`, so a violation is *precisely* checkable —
a byte diff, no judgement. For a **free-drawn** fallback scene there is no source to
compare against, and any check has to guess which lines are art and which are caption.

## Decision

**Nothing is enforced yet. Phase 6's run records box-rule violation counts, and the
mechanism is chosen from that data.**

Task 0038 put five options on the table — diff against the library entry, a
bounding-box heuristic, a redraw loop, dropping the visual, or measuring first. The
owner chose measuring first. No check, no redraw loop and no rejection is added to the
generation path today; the prompt instruction stands as the only control until there
are numbers.

What Phase 6 must record, and this ADR commits to:

- **Fetched scenes: a real violation count.** The card carries `src_id`, so the check is
  a diff against that library entry — every original line surviving byte-identical
  including its leading whitespace, additions allowed only as whole new lines above or
  below, or as suffixes on an existing line. Counted and logged, **never rejected**.
- **Counted separately from every other rejection reason**, per CLAUDE.md: a card whose
  art broke the box is not the same fact as a call that never returned.

## Consequences

**What this buys.** No speculative machinery on the generation path before the first
grounded run, and no threshold or heuristic invented against zero observations — the
mistake the gemini-saga was four weeks of. If the violation rate turns out to be near
zero, the whole question closes for the cost of a counter.

**What it costs, honestly: violations ship in the meantime.** Every card generated
before the mechanism lands can carry misaligned art, and nothing will say so. The
corpus is not disposable — cards written now are the cards users read — so this is a
real, accepted cost and not a deferral into a vacuum.

**"Measure first" is only cheap on one of the two paths.** The fetched path measures
itself with a diff. The free-drawn path has **no source**, so measuring it needs exactly
the art-versus-caption heuristic that option (b) was hesitated over — the measurement
instrument and the enforcement mechanism are the same object there. So Phase 6 will
produce a violation rate for fetched scenes and, unless something else is built, no
number at all for free-drawn ones. Whoever picks the mechanism should know they are
choosing on half the data, and that the half they are missing is the half with no
safety net.

**A counter is not free of judgement either.** The diff defines "violation" as
byte-identity of every source line. A model that re-indents the whole block uniformly —
harmless, since monospace alignment is preserved — counts as a violation under that
rule. Expect the raw number to overstate the problem, and read a sample rather than the
count alone.

## Alternatives considered

**Diff against the source library entry, with a redraw loop** (task 0038's options a+c).
Precise, deterministic, and it composes with ADR-0066's existing posture — a violation
hands the art back rather than dropping the visual. Rejected *for now*, not on merit:
it enforces only where a source exists, and the owner's call was to size the problem
before building the machinery. This is the option the data most likely selects.

**A bounding-box heuristic** (option b). Covers free-draw too, by computing the art's
left edge and rejecting anything that shifts it. Rejected: it has to guess what is art
and what is caption, and a wrong guess rejects a good card silently — trading a silent
quality failure for a silent availability one.

**Drop the visual, keep the card** (option d). Cheapest to build. Rejected: ADR-0066
already moved away from exactly this for the width rule, on the grounds that a card
that lost its art is a worse card and the model can simply be asked again. Re-adopting
it for box integrity would walk that back.

## Revisit when

- **Phase 6 reports its counts.** That is the trigger this ADR exists to create. A
  non-trivial fetched-scene violation rate selects the diff-and-redraw mechanism.
- **A smaller model reaches the drafting path** ([ADR-0090](0090-hybrid-gemini-mistral-generation.md)).
  Instruction-only compliance is a property of the model following it, so the
  measurement does not transfer across a model swap — it has to be re-read.
- **Anyone notices misaligned art in the feed before then.** One real example is worth
  more than the counter, and means the cost above stopped being hypothetical.

## Related

- [ADR-0066](0066-redraw-over-budget-ascii-art.md) — the width rule's check and redraw
  loop, the posture this one is deliberately not yet copying
- [ADR-0080](0080-ascii-fetcher-node.md) — fetched scenes, and
  why `src_id` makes the fetched path checkable at all
- [ADR-0021](0021-ascii-scene-library.md) — the scene library and why reuse is counted
  server-side rather than asked for in the prompt
- [ADR-0096](0096-canon-is-pinned-not-retrieved.md) — the box rule is pinned into every
  art-editing prompt; that is what makes instruction-only enforcement *possible*, not
  what makes it sufficient
- [Task 0038](../tasks/0038-frog-rag-and-hybrid-generation.md) — Phase 6, where the
  counting happens
