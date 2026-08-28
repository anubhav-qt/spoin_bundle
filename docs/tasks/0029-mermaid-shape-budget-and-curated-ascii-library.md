# Task 0029: Deterministic mermaid shape budget, and wire the curated ASCII library into the prompt

**Owner:** unassigned
**Blocked on:** nothing structurally for the remaining half; it wants real v3
generation output to tune thresholds against before the check gets strict.

**Status: half done.** §2 (curated-library retrieval) is implemented —
`spoin.content.ascii_library.top_candidates`, wired into `_format_plans` in
`langchain_impl.py`, tests in `tests/test_ascii_library.py` and
`test_langchain_impl.py::test_generate_cards_with_ascii_plan_shows_retrieved_candidates`.
See [ADR-0068](../adr/0068-curated-ascii-art-library-and-worked-few-shot-generator.md)'s
"Implementation note" for exactly how, and its **open conflict with §2** — that ADR's
own "pictorial-only" rule and ADR-0067's form-free decision disagree, unresolved. §1
below (mermaid shape) is still open.

## The problem

Two things from [ADR-0067](../adr/0067-mermaid-diagrams-and-form-free-ascii.md) and
`apps/helpers/TODO_GENERATOR_PROMPTS.md` are currently **prompt-only** — stated as
instructions the model should follow, with nothing outside the model checking that it
did. Per CLAUDE.md's "the generator is trusted for taste, never for constraints", both
want the same treatment ADR-0066 gave the ASCII width budget and ADR-0067 gave mermaid
syntax: a deterministic check, with a defined consequence when it fails.

### 1. The "roughly square" diagram shape

`CARDS_DIAGRAM_SYSTEM` (cards.py) asks for `flowchart TD` by default, ~4-8 nodes,
2-4 rows deep, 2-3 nodes at the widest row, short labels — so a diagram fills a phone
card without becoming a one-node-per-row column or a horizontal strip. Node count and
label length are both countable from the mermaid source. Nothing counts them today.

What's missing:
- A pure function (same shape as `_ascii_over_budget_lines` /
  `_mermaid_structural_issue` in `langchain_impl.py`) that parses node declarations out
  of a `flowchart`/`graph` block and reports node count, max label length, and — if
  it's cheap enough to get right — the graph's rough depth (longest path from a root).
- A decision on consequence: reject the card outright (ADR-0066's model — redraw, then
  reject if still over), or log a warning and let it through (the softer treatment,
  since "square" is closer to taste than to a hard invariant like the 40-column budget,
  and a false-positive rejection here costs a whole card over a soft-boundary heuristic
  a plain-text parser is not authoritative about).
- Whichever is chosen, wire it into `generate_cards`'s existing per-card mermaid check
  (`_mermaid_structural_issue`'s call site) rather than a second separate pass.

This needs real v3 output to calibrate the thresholds against before it's strict —
tightening a node-count cutoff from a guess risks rejecting diagrams that are
genuinely fine.

### 2. ~~The curated ASCII library isn't wired into anything~~ — DONE

Implemented: `spoin.content.ascii_library` parses the curated library (a packaged
copy under `apps/api/src/spoin/content/ascii_library_data/`, since the Dockerfile
never `COPY`s the sibling `apps/helpers/` tooling directory), embeds every entry's
TITLE once per process via the same local `get_embedder()` every other similarity
feature already uses, and `top_candidates(query, k=10)` returns the nearest titles by
cosine similarity. Wired into `_format_plans` in `langchain_impl.py`: an `ascii`-typed
planned card's `asset_direction` is the query, and the top 10 (title + art) are shown
in that card's own brief as reference material to adapt or ignore — never a forced
pick. Tests: `tests/test_ascii_library.py`,
`test_langchain_impl.py::test_generate_cards_with_ascii_plan_shows_retrieved_candidates`.

Left open by this implementation, not by design:

- **The `apps/helpers/` → packaged-copy sync is manual.** Editing
  `apps/helpers/use_for_gags.txt` (e.g. during
  [Task 0030](0030-manual-review-curated-ascii-library.md)'s review) does nothing to
  generation until someone re-copies it into `content/ascii_library_data/`. Worth
  automating (a `make` target, or a CI check that fails on drift) once Task 0030 is
  underway and edits are actually happening.
- **§2 vs §3 of ADR-0068 disagree with ADR-0067**, and retrieval was wired to match
  what's actually in `ASCII_INSTRUCTIONS` (form-free, per ADR-0067) rather than
  ADR-0068 §2's "must strictly contain pictorial artworks" — see ADR-0068's
  "Implementation note" for the specifics. This is a real unresolved question, not
  a rounding error; someone needs to pick a side.
- **Only the planned-card path (ADR-0059) gets candidates.** The unplanned
  `CARDS_ASCII_SYSTEM` route (used when a whole batch is forced to type `ascii`, or
  the hero call) has no `asset_direction` to embed against, so it still generates
  unaided. Extending retrieval there would need a different query — the subtopic
  title/description, most likely — and is a separate, smaller follow-up.
- **Unbenchmarked.** Nothing yet measures whether cards written with a retrieved
  candidate score better (fewer quality-gate rejections, more likes/screenshots) than
  cards drawn unaided. Worth checking once enough v3 cards exist.
- **The planner writing `asset_direction` is still blind to the library.** Retrieval
  rescues whatever `asset_direction` the planner happens to write, matched against
  what actually exists — it doesn't help the planner write a BETTER one by knowing
  the library's shape in the first place. See
  [Task 0031](0031-planner-visibility-into-ascii-library-breakdown.md), blocked on
  Task 0030 finishing first.

## Why it matters

Both are the same shape of gap CLAUDE.md warns about directly: "when you catch
yourself adding a 'please keep this under N' line to a prompt, you want a check, not a
sentence." The square-shape guidance and the curated-library two-pass scan are both
currently sentences.

## What NOT to do

- Don't paste the full library into every prompt call "to be safe" — it doesn't fit,
  and even the two curated subsets are too large. This needs retrieval, not brute force.
- Don't tighten the square-shape node-count/label-length thresholds before there's real
  v3 diagram output to check them against — a guessed cutoff risks rejecting diagrams
  that are actually fine.
- Don't touch `spoin_db` to backfill either check onto existing cards — per CLAUDE.md,
  new cards get the improvement; old cards are not wrong, they're old.
