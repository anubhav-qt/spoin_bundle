# ADR-0099: An ASCII scene carries its own explanation, and a card is as tall as its content

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** project owner

## Context

The first grounded generation run ([task 0038](../tasks/0038-frog-rag-and-hybrid-generation.md)
Phase 4) produced 86 Rust cards, 24 of them carrying a curated ASCII scene. Reading them in
the real card chrome surfaced three problems that all trace back to the same place: **the
scene is the hook ([ADR-0021](0021-ascii-scene-library.md), [ADR-0079](0079-ascii-library-is-gags-only.md)),
so it is the first thing a reader meets — and several scenes could not be understood at
all.**

**1. The prompt asked for text on the art and warned against it in the same breath.**
`ASCII_FETCH_SYSTEM` said *"Add short captions, labels, or speech callouts that tie it to
THIS card"*, and the bullet immediately under it said *"Count the columns after adapting. A
caption is the usual way a line goes over budget; tighten it rather than shipping it."*
`_ASCII_BOX` reinforced the constraint side and closed on the penalty — one over-budget line
discards the whole card, title and body with it ([ADR-0066](0066-redraw-over-budget-ascii-art.md)).

Nothing anywhere told the model that **height is free**. The 40-column budget is per line;
`_ascii_over_budget_lines` measures line width and nothing measures a drawing's height.
There has never been a vertical constraint in the code. Faced with a rule that read as
all-constraint, the model minimised the thing that was actually wanted, and shipped
wordless art.

The room was there the whole time. Measured across the run's 24 scenes (225 art lines):
median line **23 of 40 columns**, p90 31, widest 38. A typical line has ~17 free columns to
its right, and lines above and below cost nothing at all.

**2. The caption asked for the wrong artefact.** `ascii_alt` was specified at all five
prompt sites as *"one plain sentence describing the scene for a screen reader"*. But the
card renders it as `.card-visual-caption`, printed under the scene, to a **sighted reader
who could not parse the drawing** — a different job from alt text, and one that wants the
joke explained rather than the shapes enumerated.

**3. A card clipped its own body.** `.card-body` carried `max-height: 520px; overflow-y:
auto`, arriving in `90c87eb` with no comment and no ADR in a stylesheet that explains
everything load-bearing. It put a second scroller inside a card that already sits inside
the feed's scroller, so a long card read as cut off mid-sentence — and a tall scene pushed
the prose explaining it into the hidden region. `.card-ascii` directly above it is
*deliberately* uncapped, with a comment saying why.

## Decision

**Every ASCII scene ships with text on it, and the prompts say where the room is.**

- `_ASCII_BOX` states that there is **no limit on height** — the budget is per line, so a
  line added above or below is free — and that a label which will not fit beside a figure
  **gets its own line rather than being shortened away**. It cites the measured ~23-of-40
  typical width, so the model knows short labels usually fit to the right as well.
- The fetch prompt **requires** two things of every returned scene: **labels naming the
  parts** (which figure is the king, which box is the heap, what the arrow does) and **at
  least one line of dialogue, stage direction, or caption** that lands the gag for this
  card. Overflow is redirected to a new line, never to a trim.
- The same requirement is stated on the **draw-your-own** path and, critically, on the
  **ADR-0066 redraw** path — a redraw that fixes columns by deleting the text would
  reintroduce exactly the failure this closes.

**`ascii_alt` is a reader-facing caption, not screen-reader alt text.** Same field, same
schema, different job: say what the drawing shows *and what the joke is*, in one plain
sentence, so a reader who cannot make sense of the art gets both.

**A card is as tall as its content.** The `.card-body` height cap is removed, for the
reason `.card-ascii` never had one.

**This is prompt guidance, not a server-side check** — deliberately, and consistent with
[ADR-0098](0098-measure-the-ascii-box-rule-before-enforcing-it.md), which settled the
neighbouring box rule as measure-first. A check that rejected wordless art would reject
cards on an already throughput-starved pool, and we do not yet know the rate. Measure, then
decide.

## Consequences

**Easier.** A scene explains itself to the reader who cannot decode it, which is the point
of a hook. The model stops being asked for two contradictory things, and the axis with
genuine room — height — is finally named.

**Harder.** Scenes get taller and text-heavier, which is more surface for the model to get
wrong and more columns near the budget. The `generate_cards:ascii` canon preamble is now
closer to its 1200-token ceiling (`test_canon_preambles.py`) — the first draft of this
change blew it at 1218 and had to be condensed, so the next rule added here has less room
than the last one did. Removing the body cap makes long cards genuinely long in the feed;
if that reads badly at scroll, it is a feed-layout problem to solve in the feed, not by
re-clipping the card.

**Committed to.** ASCII art that says something. The 24 scenes already generated carry the
old screen-reader-style alts and are not backfilled — they correct when those cards
regenerate.

## Alternatives considered

**A server-side check that rejects wordless art.** Rejected for now: it is the enforcement
this codebase normally prefers, but ADR-0098 just settled the adjacent rule as
measure-first for a specific reason — an unmeasured check on the visual path costs whole
cards (ADR-0066 rejects the card, not just the art) at a moment when the pool lands ~7
calls a minute. The check is the right *next* step once the rate is known.

**Require text on the curated library entries instead.** Rejected by the owner: the art
should not have to carry words on its own — a wordless drawing can be perfectly good raw
material. The text belongs to the *adaptation*, where it can name this card's concepts,
rather than being frozen into a library entry that must then suit every future card.

**A separate `ascii_caption` field beside `ascii_alt`.** Rejected: it means a schema
change, a migration, a wire-model change, and a second field the model can get wrong, to
serve two audiences that want the same sentence. One sentence explaining the drawing serves
the screen reader too.

**Raise the 1200-token preamble ceiling.** Rejected: that budget exists for ADR-0089's
throughput arithmetic — a preamble is paid on every call of its type before a single
retrieved fact is added — so slack there comes straight out of the grounding budget.
Condensed the text instead.

**Keep the body cap and let tall scenes scroll internally.** Rejected: a scroller inside a
scroller is where the clipping came from, and the reader has no way to tell a card that
ended from a card that was cut.

## Revisit when

- A run produces a measurable rate of wordless or near-wordless scenes despite the prompt.
  That is the signal to promote this from guidance to a check — with the rate in hand,
  which ADR-0098 asks for.
- Over-budget redraw rates climb after this change. Taller, text-heavier scenes push more
  lines toward 40 columns, and ADR-0066 rejections cost whole cards.
- Long cards read badly in the feed once there are enough of them to judge. The answer then
  is feed layout, not a height cap on the card.
