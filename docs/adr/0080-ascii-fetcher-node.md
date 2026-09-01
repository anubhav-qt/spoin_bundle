# ADR-0080: A dedicated ASCII fetcher node — retrieve, pick, caption, and never repeat an art within a topic

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Anubhav
- **Amends:** [ADR-0059](0059-card-planning-pass-and-prompt-versioning.md)
  (adds a third pre-write stage), [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md)
  / [ADR-0067](0067-mermaid-diagrams-and-form-free-ascii.md) (ASCII authorship
  moves off the writer for a matched card), [ADR-0079](0079-ascii-library-is-gags-only.md)
  (the free-draw path is now a fallback, not the default)
- **Related:** [ADR-0021](0021-ascii-scene-library.md) (its "selection + dialogue,
  never drawing" posture is what this restores, with an LLM picking from
  retrieval instead of from a description list), [Task 0029](../tasks/0029-mermaid-shape-budget-and-curated-ascii-library.md),
  [Task 0033](../tasks/0033-grow-the-curated-ascii-library-over-time.md)

## Context

Since [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md) the writer call
draws ASCII art free-hand. Task 0029 bolted retrieval onto that: an `ascii` plan's
`asset_direction` runs `top_candidates(k=10)` against the curated library and the
matches are appended to that card's brief in the *writer* prompt
(`_format_ascii_candidates`), which tells the writer "you MUST use one of these
ten as a base, adapt it, add captions, stay ≤40 columns" — inside the same call
that also writes `title`/`summary`/`body`.

Three things are wrong with that shape:

1. **No explicit accept/reject.** The writer is told to use a candidate but
   nothing records whether the chosen art actually fit or the writer forced a
   bad one because the prompt said it must. There is no clean "none of these
   work — draw something instead" branch.
2. **No per-topic dedup.** [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md)'s
   own "Harder" section flagged this: nothing stops two cards in one topic from
   landing on the same or near-identical scene. With the library now gags-only
   and small (~248 entries, [ADR-0079](0079-ascii-library-is-gags-only.md)), the
   same handful of strong matches will recur across a topic's tiers.
3. **It re-merges the jobs [ADR-0059](0059-card-planning-pass-and-prompt-versioning.md)
   split.** "Pick from ten, trim it, caption it, count the columns" is asset
   work; asking the writer to do it alongside prose is the multi-job prompt the
   planning pass exists to avoid.

## Decision

**Add an ASCII fetcher: one call per subtopic-tier on the FIRST pass, right after
`_plan_tier_cards`, over that tier's `ascii`-typed plans.** It runs on the
generator (cheap) ladder, same as the planner. New
`ContentGenerator.fetch_ascii_scenes` — a batch method
([ADR-0005](0005-batch-llm-calls.md)).

**Redraft rounds do NOT fetch.** A redraft's new cards get fresh briefs
(ADR-0059) but their ascii scenes free-draw (`ASCII_INSTRUCTIONS`) — re-running
retrieval to place one or two scenes against an already-thinned per-topic pool is
not worth the call.

### What it receives, per `ascii` plan

`canonical_title`, `asset_direction`, `content_direction`, and the top-10
`top_candidates(asset_direction, exclude_ids=<the topic's used set>)` — the
closest library scenes that have **not already been used in this topic**.

### What it does

1. **Pick exactly one** candidate whose drawing can carry this card's idea.
   Biased hard toward accepting: the ten are already the closest embedding
   matches, and a near-fit adapted with the right caption beats an unaided
   free-draw. Acceptance is the expected path.
2. **Author the final scene** from that candidate — keep or trim its lines, add
   captions / labels / speech callouts drawn from `asset_direction` and
   `content_direction`, every line ≤ 40 columns. This produces `ascii_art`,
   `ascii_label`, `ascii_alt`.
3. **Only when nothing fits**, return `no_match` for that plan. The card then
   flows to the writer's existing free-draw path (`ASCII_INSTRUCTIONS`,
   [ADR-0079](0079-ascii-library-is-gags-only.md)'s comedic-shape fallback) —
   the rare case, not the default.

### Authorship moves off the writer for a matched card

For a plan the fetcher matched, the writer no longer emits `ascii_art` /
`ascii_label` / `ascii_alt`; the pipeline attaches the fetcher's scene to the
`CardDraft` after the writer returns. The writer's brief for that card says "art
is handled — write title, summary, body only." `_format_ascii_candidates` is
removed from the writer prompt. `ASCII_INSTRUCTIONS` stays, reached only for a
`no_match` plan or an unplanned call (the hero card).

### Never the same art twice in a topic — persisted

The chosen library entry's `id` is stored on the card at
`visual_slots["src_id"]` (the existing nullable jsonb column — no migration).
At the start of **every** tier's fetch, the pipeline reads all `src_id`s already
recorded on the topic's active cards (`Card.visual_slots->>'src_id'`) *and* its
`RejectedCard` drafts (`RejectedCard.gen_meta->>'src_id'` — `RejectedCard` has no
`visual_slots` column, so a rejected ascii card's chosen id is stamped into its
`gen_meta` jsonb by `_rejected_card`), and passes them to `top_candidates` as
`exclude_ids` — so a used scene is filtered out of the candidate pool *before
ranking*, for the rest of that topic's life, across every later tier and every
later worker pass. A `_Runtime` in-memory set is a within-pass fast path layered
on the DB query, which is the cross-pass source of truth.

`top_candidates` grows an `exclude_ids: frozenset[str] = frozenset()` parameter
and filters the library before embedding comparison.

### Constraints stay outside the model (CLAUDE.md)

- The 40-column budget and [ADR-0066](0066-redraw-over-budget-ascii-art.md)'s
  redraw-then-reject guard run on the fetcher's `ascii_art` exactly as on
  writer-drawn art. "Pick one of these ten" is taste; "≤ 40 columns" is a check.
- "Not already used in this topic" is enforced by the retrieval layer applying
  `exclude_ids`, never by asking the model to remember what it picked.

### Prompt version → 5

`CARD_PROMPT_VERSION` is already `4` (ADR-0059 set 2, ADR-0066 → 3,
ADR-0067/0068 → 4). A new pre-write stage that reassigns a field's authorship,
plus the gags-only library ([ADR-0079](0079-ascii-library-is-gags-only.md)) and
the raised ascii curriculum floor, is exactly what the `gen_meta.prompt_version`
axis exists to make queryable. `= 5` on every card, question, and rejected draft
written after this; earlier versions unchanged.

## Consequences

**Easier**

- A real accept/reject verdict per ascii card, recorded, instead of a writer
  quietly forcing a candidate the prompt told it to use.
- Every ascii scene in a topic is a distinct library piece (or a deliberate
  free-draw). ADR-0042's open dedup gap is closed for the matched path.
- The writer's ascii cards become title/summary/body only — one job, same as
  ADR-0059's direction for every other prompt.

**Harder**

- **Still no detector for "does this drawing suit the concept."** Same gap
  [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md) named. The fetcher
  can pick a weak match; bias-to-accept makes a marginal library scene more
  likely than a free-draw. Caught only by eyeballing a real corpus, plus the
  `no_match` escape.
- **Per-topic exclusion drains a small library.** A broad topic will exhaust its
  strong matches and later tiers hit `no_match` — and therefore free-draw — more
  often. This is the intended degradation ([ADR-0079](0079-ascii-library-is-gags-only.md)
  already banked it); [Task 0033](../tasks/0033-grow-the-curated-ascii-library-over-time.md)
  (grow the gag library) is the pressure valve.
- **A rejected card's `src_id` stays excluded.** If a matched ascii card is
  later rejected by the gate, the art it used is still burned for the topic (the
  `RejectedCard` row carries the `src_id`). Deliberate — the scene was spent on
  an attempt — but a tier with heavy attrition loses pool faster than it lands
  cards. Revisitable.
- **One extra generator-ladder call per tier's first pass** with ≥1 ascii plan
  (redraft rounds excluded). Same magnitude and ladder as the planner; the
  thinking pool is untouched. The curriculum prompt's ascii floor was raised
  from "at least 2-3" to "at least 4-5" per subtopic tier in the same change, so
  nearly every first pass triggers a fetcher call and a 20-25 card tier carries
  ~8-12 ascii plans — a fetcher call there is ~15-18k input tokens, still
  trivial against the model's context.
- **`visual_slots["src_id"]` is load-bearing for dedup now.** Pre-ADR-0080 cards
  have none and are simply absent from the used set — correct, they drew
  original art and burned no library id.

**Committed to**

- The fetcher is pure: it retrieves, picks, and captions. It never draws an
  original scene — that stays the writer's free-draw path.
- The exclude set is applied by retrieval, not requested from the model.
- No migration: `src_id` rides the `visual_slots` jsonb the schema already has.

## Alternatives considered

**Keep retrieval in the writer call (status quo + Task 0029).** Rejected: no
explicit verdict, no per-topic dedup, and it is the multi-job prompt ADR-0059
split apart — "pick from ten, adapt, caption, count columns" next to prose.

**One fan-in fetch per topic instead of per tier.** Better dedup visibility in a
single call. Rejected (owner's call): per-tier keeps the wiring parallel to the
planner and needs no topic-wide plan aggregation the graph does not currently do.
The persisted `src_id` query gives per-tier fetches the same cross-tier view
anyway.

**The fetcher draws the fallback scene itself.** One node owns all ASCII output.
Rejected (owner's call): keep it a pure fetcher; the writer's free-draw path
already exists and [ADR-0079](0079-ascii-library-is-gags-only.md) defines its
shape.

**In-memory per-pass dedup only, no persistence.** Simpler. Rejected (owner's
call): a topic generates over many cron passes and the "never twice in a topic"
guarantee has to survive them.

**A soft "at most twice per topic" cap (ADR-0021's original rule) instead of hard
single-use.** Gentler on a small library. Rejected for now: the owner wants
genuine non-repetition; if free-draw fallback rate climbs too far, this is the
first knob to loosen.

## Revisit when

- **Free-draw fallback rate climbs** because per-topic exclusion drains the
  ~248-entry library — grow it ([Task 0033](../tasks/0033-grow-the-curated-ascii-library-over-time.md)),
  raise `k`, or loosen hard single-use to "at most twice."
- **The fetcher's picks are visibly poor** often enough to want a detector or a
  human review pass over matched ascii cards.
- **Tiers with heavy gate attrition** run out of pool because rejected cards'
  `src_id`s are permanently burned — return them to the pool on rejection.
