# Task 0033: Grow the curated ASCII library over time

**Owner:** Anubhav (same human-judgment reason as [Task 0030](0030-manual-review-curated-ascii-library.md))
**Blocked on:** [Task 0030](0030-manual-review-curated-ascii-library.md) reaching a
usable state first — verify what's there before adding more on top of it.
**Timebox:** none — this is a standing, long-horizon task, revisited in small
batches whenever there's appetite, not a one-sitting piece of work.

## The problem

The curated ASCII library (`apps/helpers/use_for_gags.txt` — 888 entries;
`apps/helpers/use_for_informative_visualization.txt` — 1,599 entries; packaged
copy under `apps/api/src/spoin/content/ascii_library_data/`) is a fixed snapshot
from one large scrape-and-curate batch. Task 0029's retrieval now draws every
ASCII-archetype card's art from it, so its *coverage* is a ceiling on how well
`asset_direction` descriptions can be matched: a topic or gag with no
near-neighbour in the library falls back to a weaker candidate or none.

Two moves keep the library healthy, in this order:

1. **First, finish enough of [Task 0030](0030-manual-review-curated-ascii-library.md)**
   — the manual pass over titles and art clarity — that the existing corpus is
   trustworthy. Adding new entries onto an un-reviewed base just grows the pile
   of things to review.
2. **Then, keep adding**, in small curated batches, targeting the gaps that
   real usage exposes.

## What "keep adding" means

- **Let retrieval usage data drive it.** Once Task 0029 has run against the live
  feed for a while, look at which `asset_direction` descriptions retrieved a
  poor best-match (low similarity) or nothing — those are the concrete gaps.
  Add art for *those*, not for whatever is easy to find.
- **Same bar as Task 0030's review.** Every new entry: art renders as the thing
  its title claims, alignment intact, recognizable at a glance, ≤40 monospace
  columns; title phrased the way a search query would plausibly say it (it is
  matched by embedding similarity against `asset_direction`), not just
  descriptive after the fact. Keep/fix/reject each candidate the same way.
- **Sources and tooling** already exist: `apps/helpers/scrape_ascii_art.py`,
  `apps/helpers/curate_spoin_art.py`, and the curation workflow in
  [`apps/helpers/curation/README.md`](../../apps/helpers/curation/README.md).
  A new batch goes through the same scrape → curate → manual-review path.
- **Re-copy to the packaged location.** An edit or addition in `apps/helpers/`
  does nothing until it is copied to
  `apps/api/src/spoin/content/ascii_library_data/` (the Dockerfile doesn't ship
  `apps/helpers/`). Task 0030 already notes this and flags automating it with a
  `make` target — do that once either task is regularly touching the files.
- **Attribution and licensing.** The existing entries carry an `ARTIST` field.
  New entries keep that discipline — record provenance, and only pull from
  sources whose terms allow redistribution.

## Why it matters

The library is trusted content, not a mechanically-valid pile (CLAUDE.md: "the
generator is trusted for taste, never for constraints" — the art it draws from
has to be good, because retrieval will offer it and the model may pick it). A
static library slowly falls behind the topics the corpus actually grows into;
a library that grows against measured gaps keeps ASCII cards from silently
degrading to "closest weak match" as coverage thins.

## What to hand back

Per batch: the new entries (in both the `apps/helpers/` source and the packaged
copy), a note of which retrieval gaps they were chosen to fill, and the
keep/fix/reject decisions logged the same way Task 0030 logs its pass
(`apps/helpers/curation/decisions/`).

## What NOT to do

- Don't let an LLM judge "is this good art" — same reason as Task 0030: a model
  re-reviewing scraped/curated art is the least trustworthy check for the exact
  failure this guards against.
- Don't bulk-add thousands more entries in one go to "get ahead of it" — that
  just recreates Task 0030's problem at a larger scale. Small, reviewed,
  gap-targeted batches only.
