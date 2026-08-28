# Task 0031: Give the planner a breakdown of what's actually in the curated ASCII library

**Owner:** unassigned
**Blocked on:** [Task 0030](0030-manual-review-curated-ascii-library.md) — do this AFTER
the manual review, not before. A breakdown built from unreviewed entries teaches the
planner to reach for content that might get fixed or deleted out from under it.

## The problem

[Task 0029](0029-mermaid-shape-budget-and-curated-ascii-library.md)'s retrieval finds
candidates for the WRITER — the call that already knows a specific `asset_direction`
and gets shown the 10 closest-matching library pieces for it. It does nothing for the
PLANNER (`PLAN_SYSTEM`/`PLAN_USER` in `cards.py`), which is the call that actually
*writes* `asset_direction` in the first place, one subtopic's worth of briefs at a
time, with zero visibility into what the library even contains.

Concretely: the planner is asked to write "a scene an ascii gag should stage" for
whichever ideas in a subtopic call for one. It's writing that blind — it doesn't know
whether the library is stronger on reaction faces, animals, hardware, or 1970s
household objects, so it can't aim `asset_direction` at what's actually likely to
retrieve well versus what will fall back to original generation every time. Retrieval
(Task 0029) rescues a bad `asset_direction` after the fact by matching on whatever the
library actually has — but the planner writing a BETTER `asset_direction` in the first
place, because it knows the shape of the library, is a different and complementary
improvement retrieval alone can't provide.

## What this task should produce

A written breakdown — most likely a block added to `PLAN_SYSTEM`'s ASCII guidance
(the same `## SHAPE` section that currently just says "ascii: an idea a small, funny
drawn scene would genuinely dramatize... whatever form makes the joke land") — that
gives the planner a genuine sense of the library's SHAPE, not its full inventory
(2,532 entries obviously can't be pasted in). Concretely:

1. **The category/subcategory breakdown**, so the planner knows what's actually deep
   vs. thin. A rough starting point from the two curated files as they stand today
   (re-run after Task 0030 — deletions/retitles will shift these numbers):
   - `use_for_gags.txt` (888 entries, 22 categories): heaviest in `animals` (315),
     `cartoons` (85), `people` (74), `television` (67), `mythology` (64) — 145
     subcategories total.
   - `use_for_informative_visualization.txt` (1,599 entries, 27 categories): heaviest
     in `animals` (211), `miscellaneous` (121), `sports-and-outdoors` (108),
     `art-and-design` (103), `computers`/`electronics` (101/100), `plants` (99) — 263
     subcategories total.
2. **A handful of representative titles per major category** (not full art — titles
   alone are enough to give a sense of range), so "animals" reads as "yes, this
   covers everything from a coiled snake to a confused-looking llama" rather than a
   bare number.
3. **An honest note on what's THIN**, so the planner doesn't reach for
   `asset_direction` ideas the library has little chance of matching (e.g. if there
   are only a handful of `video-games` or `weapons` entries after Task 0030's cuts,
   say so, rather than let the planner assume even coverage from category names alone).

## Why this shape and not something bigger

- **Not a live query.** The planner call has no tool access and shouldn't gain one for
  this — a static, hand-written (or generated-once-and-pasted) summary block is
  simpler, cheaper, and the library doesn't change fast enough to need a live lookup
  baked into every planning call.
- **Not the full library.** Same reasoning as Task 0029's retrieval design — 2,532
  entries doesn't fit a prompt budget, and the planner doesn't need every entry, only
  a sense of where the mass is.
- **Regenerate the numbers after Task 0030**, not before — building this against
  entries that are about to be retitled or deleted just means redoing it.

## Why it matters

This is the same "generator trusted for taste, never for constraints" shape as
everything else in this area, but pointed the other way: the CONSTRAINT (which
candidates actually exist) is Task 0029's job and is already enforced outside the
model. This task is about giving the model better TASTE inputs — information that
helps it make a better judgment call, not a rule to check afterward. Skipping it
doesn't produce wrong output the way skipping a constraint would; it just means the
planner keeps aiming somewhat blind, and `asset_direction` stays less useful as a
retrieval query than it could be.

## What NOT to do

- Don't build this before Task 0030 finishes — see "Blocked on" above.
- Don't wire a live database/embedding lookup into the planner call for this; a
  written summary is the right shape (see above).
- Don't let this become a second full copy of the library summarized differently —
  if the temptation is to include hundreds of titles "just in case," that's a sign
  the retrieval step (Task 0029) should be doing more work, not the planner's
  static context.
