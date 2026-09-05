# ADR-0079: The ASCII art library is gags-only; every ASCII card is a joke

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Anubhav
- **Amends:** [ADR-0068](0068-curated-ascii-art-library-and-worked-few-shot-generator.md)
  -- its point 1 partitioned the curated library into a gag file and an
  informative-visualisation file, and point 4's worked few-shot set carried one
  "informative" example per topic. The informative half is dropped as a runtime
  source. Point 2 (no text-only flowcharts in ASCII slots) and the 40-column
  invariant are unchanged.
- **Related:** [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md),
  [ADR-0067](0067-mermaid-diagrams-and-form-free-ascii.md),
  [ADR-0059](0059-card-planning-pass-and-prompt-versioning.md)

> **Amended by [ADR-0099](0099-ascii-scenes-carry-their-own-explanation.md) (2026-09-05):** a scene must now carry text on it — labels naming its parts and a line of dialogue or a caption — because the scene is the hook and wordless art cannot be read. `visual_slots.alt` is now the reader-facing caption printed under the drawing, not screen-reader alt text.

## Context

ADR-0068 split the curated ASCII reference library into two files:
`use_for_gags.txt` (comedic scenes, characters, pop-culture) and
`use_for_informative_visualization.txt` (hardware, tools, real-world objects,
educational illustrations). `content/ascii_library.py` loaded both, tagged each
entry with a `source` of `"gags"` or `"info"`, and the planner prompt carried a
"at least 70% gags / at most 30% informative visualisations" ratio.

Two things made the informative half not worth keeping:

- **The product's ASCII slot is a hook, not a reference plate.** CLAUDE.md's rule
  is that silliness lives in the hook layer -- title, summary, ASCII art -- and an
  informative diagram of a GPU or a socket wrench is neither a joke nor structure
  the client can lay out; it is a static picture that a `diagram` (mermaid) or a
  `prose` card does better. The scenes people screenshot are the funny ones.
- **The gag file just got a hard quality pass.** The 2026-09-01 manual curation
  (`use_for_gags.txt`, down to ~248 hand-verified, hand-titled entries) leaves a
  pool that is small but entirely good. There is no matching pass on the
  informative file, and pointing retrieval at unreviewed entries to pad a count
  is the failure mode the curation was meant to end.

Separately, the "70/30" ratio was only ever expressed as prose in `PLAN_SYSTEM`
and as headers in `format_library_catalog_for_planner()` -- a function with **no
caller** (the planner prompt never injected the catalog). So the ratio was an
instruction the planner could not act on against a breakdown it never saw.

## Decision

**Every ASCII card is a gag.** The ASCII card type means a humorous scene -- a
comedic reaction, a funny character, a silly physical metaphor, an absurd object,
a joke-timeline, a checklist with a punchline. An idea that only wants a neutral
illustration is a `diagram` or `prose` card, not an `ascii` one.

Concretely:

- `content/ascii_library.py`'s `_LIBRARY_FILES` is now `("use_for_gags.txt",)`.
  `use_for_informative_visualization.txt` stays on disk (nothing is deleted) but
  is not loaded. `AsciiLibraryEntry` drops its `source` field; the dead
  `get_library_titles_by_source()` and `format_library_catalog_for_planner()` are
  removed.
- `PLAN_SYSTEM` (`prompts/cards.py`): the "70% gags / 30% informative
  visualisations" ratio is replaced with "always a gag", plus an explicit "if the
  idea only wants a neutral illustration and no joke, it is a diagram or prose
  card". `ASCII_INSTRUCTIONS` loses "genuinely informative" in favour of "always
  a joke -- dramatize the concept AND land a laugh".
- The writer's retrieval path (`langchain_impl.py`, `top_candidates()`) is
  unchanged in shape -- it just searches a smaller, all-gag pool now.

`prompt_version` is **not** bumped. ADR-0059's version axis tracks the
plan-then-write split; this is a content-scope narrowing within v2, and the gate
already re-rates every card regardless.

## Consequences

**Easier.** One idea of what an ASCII card is, in the planner prompt, the writer
prompt, and the library -- no ratio to balance, no `source` to thread through.
The candidate pool is 100% hand-verified. Dead code is gone.

**Harder.** The library is now ~248 entries, not ~2,487. A broad topic will hit
`asset_direction` ideas that match nothing and fall back to unaided generation
more often -- acceptable, because unaided generation is a correct fallback
(ADR-0042) and a bad retrieved match is worse than none. [Task 0033](../tasks/0033-grow-the-curated-ascii-library-over-time.md)
(grow the library) matters more now, and its scope is gags only.

**A reversal cost is banked, not paid.** If informative ASCII visuals are ever
wanted back, the file is still there -- re-add the filename to `_LIBRARY_FILES`
and restore a `source`-style tag. This ADR bets that won't happen.

## Alternatives considered

**Keep both files, fix the 70/30 so the planner can actually act on it**
(Task 0031's original shape -- inject a library breakdown into `PLAN_SYSTEM`).
Rejected: it invests in making the informative half usable when the simpler
finding is that the informative half does not fit the product's ASCII slot at
all. Task 0031's core idea -- the planner writing a better `asset_direction`
because it knows the library's shape -- still stands, now scoped to the gag pool.

**Delete `use_for_informative_visualization.txt` outright.** Rejected for now:
keeping it costs nothing (it is not loaded, not shipped in a prompt) and makes
the decision cheap to revisit. Delete it later if this holds.

**Bump `prompt_version` to 3.** Rejected: the plan/write architecture ADR-0059
versions is unchanged, and a v2-vs-v3 split over "slightly narrower ASCII scope"
would measure noise.

## Revisit when

- The gag library stays small enough, or a topic broad enough, that ASCII cards
  routinely fall back to unaided generation and the unaided art is visibly worse
  than a near-miss retrieval would have been.
- Engagement data shows informative/neutral ASCII visuals were actually pulling
  their weight before this -- the signal to reload the file rather than grow the
  gag pool.
