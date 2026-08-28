# Task 0030: Manually review every entry in the curated ASCII library

**Owner:** Anubhav (needs human judgment — clarity and "is this actually funny/legible"
are not things to automate this pass)
**Blocked on:** nothing — can start immediately, independent of
[Task 0029](0029-mermaid-shape-budget-and-curated-ascii-library.md)'s retrieval wiring.

## The problem

`apps/helpers/use_for_gags.txt` (927 entries) and
`apps/helpers/use_for_informative_visualization.txt` (1,605 entries) — 2,532 pieces
total — were curated and titled in one large batch (`apps/helpers/curate_spoin_art.py`,
`apps/helpers/scrape_ascii_art.py`, see the commit that added them). Every entry
satisfies the mechanical constraint (≤40 monospace columns), and `apps/helpers/
TODO_GENERATOR_PROMPTS.md` already flags several specific known-bad entries by example
(Example 27's broken Yoda ear alignment, Example 13's Pinky-and-the-Brain irrelevance,
Example 22's ambiguous boxing gloves, Example 1's off-topic Homer Simpson) — proof the
batch curation missed real problems, not just edge cases.

Once [Task 0029](0029-mermaid-shape-budget-and-curated-ascii-library.md) wires this
library into retrieval, EVERY card generated with an ASCII archetype is a candidate to
draw from it — so a bad entry here doesn't stay a one-off curation miss, it becomes a
recurring defect surfacing across the live feed. This needs a full manual pass before
retrieval goes live against it, not just a fix-the-examples-someone-already-flagged
pass.

## What "manually verify" means here

For every one of the 2,532 entries, two things need a human eye, not a script:

1. **Does the art itself actually render as the thing the title claims?** — alignment
   intact (no broken ears, no drifted panels), recognizable at a glance, not just
   "technically ≤40 columns."
2. **Is the title accurate and would it actually retrieve well?** — Task 0029's
   retrieval matches a planner's `asset_direction` description against these titles by
   embedding similarity; a vague or wrong title means a genuinely well-suited piece
   never surfaces as a candidate, silently. A title has to be the thing a search query
   would plausibly say, not just descriptive after the fact.

Per entry: keep as-is, fix (retitle and/or hand-correct the art), or delete. This is
the "keep/delete curation" the TODO already asked for on three named subcategories
(Mermaids: 22, Graduation Caps: 12, Dilbert: 4) — this task is that same review,
scoped to the entire library rather than three subcategories.

## Why it matters

CLAUDE.md's "the generator is trusted for taste, never for constraints" cuts both
ways: the retrieval system (Task 0029) is right not to force the model to pick a
candidate, but that only protects against a bad candidate being *forced* onto a card —
it does nothing to stop a bad candidate from being offered and picked voluntarily
because it plausibly matched. The library itself has to be trustworthy content, not
just a mechanically-valid one.

## One more step now that retrieval is live

[Task 0029](0029-mermaid-shape-budget-and-curated-ascii-library.md)'s retrieval reads
from `apps/api/src/spoin/content/ascii_library_data/` — a packaged COPY of these two
files, not `apps/helpers/` directly (the Dockerfile doesn't ship `apps/helpers/`).
**An edit here does nothing until it's re-copied there.** After any batch of fixes,
copy the corrected `apps/helpers/use_for_gags.txt` and
`apps/helpers/use_for_informative_visualization.txt` over the packaged copies before
the next generation run picks up the changes. Worth automating (a `make` target) once
this review is actually in progress rather than doing it by hand every time.

## What unblocks once this is done

[Task 0031](0031-planner-visibility-into-ascii-library-breakdown.md) — giving the card
planner a category/example breakdown of the library so it writes `asset_direction`
with a sense of what's actually available — is deliberately blocked on this task
finishing. Building that breakdown against entries that are about to be retitled or
deleted just means redoing it.

## What NOT to do

- Don't attempt to automate the "is this good" judgment — an LLM re-reviewing its own
  (or a similar model's) curated batch is the least trustworthy check available for
  exactly the failure mode this task exists to catch.
- Don't block Task 0029's retrieval wiring on this task finishing 100% — the two can
  proceed in parallel; retrieval can go live against the library as it stands and
  improve as entries get cleaned up, same as CLAUDE.md's stance elsewhere that an old
  card is not wrong, it is old, applies here too. But do prioritize whichever
  subcategories retrieval draws from most first, once Task 0029 has real usage data
  on which candidates actually get picked.
