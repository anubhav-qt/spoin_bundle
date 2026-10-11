# ADR-0066: Over-budget ASCII art is redrawn, then rejected with its card — never silently dropped

- **Status:** Accepted
- **Changed in the harness (2026-10-12, task 0045):** designer_toad draws a card's art after
  the gate, renders it and improves it until it looks right; a card waits for its art rather
  than being rejected over it ([harness-tools.md](../architecture/harness-tools.md)).
- **Date:** 2026-08-27
- **Deciders:** Anubhav
- **Amends:** [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md) — replaces its
  deterministic "drop the visual, keep the card" rule for the width violation. Touches the
  same card-prompt surface as [ADR-0059](0059-card-planning-pass-and-prompt-versioning.md)
  and bumps `CARD_PROMPT_VERSION` 2 → 3.

## Context

The generator draws ASCII scenes directly (ADR-0042). A phone renders roughly 38–42
monospace columns and art that wraps is destroyed rather than degraded, so a **40-column
budget** is enforced server-side in `langchain_impl.py` — the model is trusted for taste
(whether to draw, what to draw), never for the constraint. ADR-0042 inherited ADR-0021's
response to a violation: `_ascii_visual_fields()` returned `(None, None)`, dropping the
drawing and shipping the card as plain text.

Running the pipeline against the live corpus, that drop fires constantly — many scenes per
minute, several per `generate_cards` batch (`generate_cards: dropping ascii art %r -- a
line exceeds the 40-column budget`). Every one is a scene the model committed real effort
to that no reader ever sees, and the card silently loses the element that would have made
it worth screenshotting. ADR-0021's degrade-to-"no art" posture was designed for a
finite hand-authored catalog where a near-fit was the worst case; against freehand output
that overshoots the budget by a few columns, throwing the whole drawing away is the wrong
trade. The product wants *more* art-bearing cards, not a mechanism that quietly removes the
art that gets drawn.

The 40-column cap itself is not in question — it is a real rendering constraint and it
stays. What changes is what happens when a drawing violates it.

## Decision

**A drawing over the 40-column budget is handed back to the generator to redraw within
budget. Only a drawing still over budget after every redraw attempt causes its card to be
rejected — the visual is never silently dropped, and over-width art is never shipped.**

1. **Batched redraw inside `generate_cards`.** After the card batch returns,
   `_resolve_ascii_art()` partitions drawn scenes into within-budget and over-budget. If
   any are over budget, it issues **one** batched structured-output call
   (`_WireAsciiRedrawBatch`, prompt `CARDS_ASCII_REDRAW_SYSTEM`) covering all of them at
   once — never one call per card (ADR-0005). The prompt names the offending lines and
   how many columns each is over, and instructs the model to re-fit the *same* scene
   (same gag, same characters), or return empty art if it genuinely cannot.

2. **`Settings.ascii_redraw_attempts` (default 2) redraw rounds.** The second and later
   attempts carry escalated feedback ("a previous redraw still came back too wide — be
   more aggressive"). Each round re-checks width against the model's latest output and
   only re-sends the scenes still failing. `0` disables redrawing (straight to reject).

3. **Still over budget after the last attempt → reject the whole card.** The card is
   excluded from `BatchResult.items` and a reason is appended to `BatchResult.failures`
   (`ascii art '<label>' still exceeded 40 cols after redraw -- card rejected`). The
   per-tier redraft loop (ADR-0057) then refills the tier's deficit on a later round, the
   same as for any other card that did not survive generation. There is no
   drop-the-visual fallback.

4. **The model is still trusted for taste only, never the constraint.** Width is
   re-verified after every redraw; a card is rejected precisely when the model cannot
   comply, exactly ADR-0042's "trusted for taste, never for constraints" posture — the
   loop just gives it two chances before that verdict.

5. **`failed` and `rejected` stay separate numbers** (CLAUDE.md). A card dropped because
   its art would not fit after two redraws is a **rejection**, logged with that reason. A
   redraw call that never returned a verdict (quota exhaustion re-raises; any other error
   breaks the loop and logs) is a **failure** — its scenes are rejected with their cards
   and the reason string says so, distinct from "the art was judged unfixable".

**The prompts also ask for more art.** `ASCII_INSTRUCTIONS` no longer opens with "not
every card, only when a concept genuinely lends itself to it" — it now tells the writer to
reach for a scene often and skip it only when nothing about the idea suits a picture. The
curriculum `ascii` card-type quota guidance goes from "1–2 … in every subtopic tier" to
"2–3 … lean generous". This is a deliberate move away from ADR-0042's "used sparingly"
framing, on the bet that art-bearing cards earn their place (ADR-0042's own "Revisit
when").

## Consequences

**Easier**

- Art the model draws survives — re-fitted when it overshoots — instead of being removed
  from the card with no trace.
- More cards carry a scene, from the prompt and quota changes, not just from retention.
- The 40-column guarantee is unchanged and still enforced outside the model; no
  over-width or wrapped art can reach a card.

**Harder**

- **Extra calls.** A card batch containing any over-budget art now costs up to
  `ascii_redraw_attempts` additional batched calls (1–2). On the current free-tier
  per-minute quota wall this is a real slowdown, concentrated exactly on the batches that
  draw the most art. Budget: the redraw call goes through the same `_invoke_with_retry`
  ladder as every other call, so it competes for the same cells.
- **Good prose can be thrown away over an undrawable scene.** A card whose body was fine
  but whose art cannot be fit in 40 columns after two redraws is rejected whole — its
  explanation is lost and the redraft loop writes a fresh card for the slot. This was
  chosen over keeping the card without its art; the bet is that the redraw loop makes
  genuine "cannot fit" rare.
- **The detector gap ADR-0042 named is untouched.** A drawing that fits 40 columns but
  looks like nothing still ships with nothing to catch it. Redrawing narrows the width
  failure, not the "does it look like anything" failure.
- **v3 corpora carry a higher art share** and must not be pooled with v2 when judging
  quality — hence the `CARD_PROMPT_VERSION` bump. No backfill of existing `gen_meta`
  (CLAUDE.md database rule).

## Alternatives considered

- **Keep dropping the visual (ADR-0042 as-is).** The status quo. Rejected: the live drop
  rate is high enough that it is materially degrading the corpus's art coverage, and the
  product wants more art, not a mechanism that removes it.
- **Route over-budget art through the per-tier redraft loop instead of a call inside
  `generate_cards`.** Treat it as a gate-style rejection: persist the card, record
  feedback, let `_redraft_until_bar` draft a replacement next round. Rejected: it does not
  fix *that* drawing — it discards the card and hopes the replacement's art fits — and it
  adds whole redraft rounds (each a full draft + gate pass) rather than one targeted call.
  Width is a deterministic check that needs no gate round-trip.
- **Keep drop-the-visual as the final fallback after the redraws.** Redraw twice, then
  ship the card without art if still failing. Rejected by the owner in favour of
  reject-whole: a card that keeps failing to draw its own scene is a weaker card than the
  redraft loop's replacement would be, and shipping it half-formed normalises the
  half-formed state.
- **Widen the cap, or have `Card.tsx`'s `AsciiArt` box shrink font to fit.** Higher
  leverage — it would cut the violation rate at the source. Deferred: it pulls `apps/web`
  into scope and needs its own rendering/testing pass. The 40-column budget is a
  defensible constraint on its own; revisit if redraw success proves poor.
- **One redraw attempt, not two.** Rejected: the first redraw with plain feedback has a
  meaningful miss rate; the escalated second attempt is cheap insurance before the
  expensive outcome (rejecting the card).

## Revisit when

- Redraw success rate is low enough that most over-budget art ends in rejection anyway —
  that means current models genuinely cannot do 40-column art, and the cap/renderer
  question above reopens (widen the budget, or auto-fit in the renderer).
- The redraw call volume becomes a measurable share of the generation quota spend — worth
  a per-batch cap or a cheaper model tier for the redraw specifically.
- The reject-whole rate on otherwise-good cards is high enough to notice — the deferred
  "keep the card without art" fallback comes back on the table.
- Engagement data shows the higher art share is not paying off (ADR-0042's "Revisit
  when", still the governing signal for the frequency half of this decision).
