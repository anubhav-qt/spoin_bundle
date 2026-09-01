# Tasks

Self-contained pieces of work, written so someone can pick one up and finish it without
asking questions first.

A task doc lives here rather than in a chat message because chat messages get lost, cannot
be revised, and are invisible to anyone who joins later.

## Format

Each task states: the problem, why it matters, what to do, what to hand back, and a
timebox. If a task cannot be described that way, it is not ready to be handed to anyone.

## Open

| # | Task | Owner |
|---|---|---|
| [0002](0002-palette-selection-ui.md) | Palette selection UI -- onboarding picker + settings switcher | unassigned |
| [0003](0003-personalized-topic-recommendations.md) | Personalized "for you" topic recommendations | unassigned |
| [0004](0004-notes-in-one-place.md) | A single view of all your notes | unassigned |
| [0005](0005-remove-seed-subscriber-baseline.md) | Remove the seeded `subscriber_count` baseline | unassigned |
| [0011](0011-difficulty-example-catalog.md) | Author the difficulty example catalog (ADR-0030) | unassigned |
| [0012](0012-question-generation-failure-visibility.md) | Diagnose silent question-generation failures for specific subtopics | mostly resolved, see doc |
| [0013](0013-card-preview-swap-not-animated.md) | Collapsed-state preview swaps instantly while the body around it animates | unassigned |
| [0015](0015-topic-mastery-and-retention-mode.md) | Topic mastery message + retention/spaced-repetition mode once a topic is fully read | unassigned |
| [0017](0017-sql-portability-fixes.md) | Fix the Postgres-only SQL the spike found | unassigned -- unblocked, 0016 returned GO |
| [0018](0018-alembic-on-cockroachdb.md) | Make the Alembic chain apply cleanly on CockroachDB | unassigned -- unblocked; smaller than written, see 0016 hand-back |
| [0019](0019-transaction-retry-boundary.md) | A transaction retry boundary for CockroachDB's `40001` errors + worker job-claim redesign | unassigned -- unblocked; scope grew, see 0016 hand-back |
| [0020](0020-corpus-migration-and-parity.md) | Move the live corpus to CockroachDB, and prove nothing was lost | blocked on 0017-0019 |
| [0021](0021-cockroachdb-cutover.md) | Cut over to CockroachDB Basic, and instrument both meters | blocked on 0020 |
| [0022](0022-slug-collision-skips-alias.md) | Slug-collision fallback in topic matching skips alias recording (ADR-0025) | unassigned |
| [0023](0023-generation-completed-status-hides-gate-attrition.md) | "Ready" status doesn't reflect actual card completion, and the idle scanner's backfill never reconciles with it | unassigned |
| [0024](0024-reintroduce-custom-topic-limit.md) | Re-introduce the custom-topic limit, removed 2026-08-24, as a premium gate | unassigned |
| [0025](0025-quota-governor-as-a-library.md) | Extract the quota governor into a standalone library -- deferred past spoin v1 | unassigned |
| [0026](0026-few-shot-examples-from-manual-review.md) | Add worked good/bad examples to the card prompts, from hand review of v2 cards (ADR-0059) | unassigned |
| [0028](0028-responsive-right-rail-and-controls.md) | The right rail's own restructure from the responsive redesign (ADR-0064's deferred half) | unassigned -- items 1-2 shipped on `responsive-mobile-shell`; density pass + Popular/For You toggle left |
| [0029](0029-mermaid-shape-budget-and-curated-ascii-library.md) | Deterministic mermaid shape budget (node count/label length) | unassigned -- curated-library retrieval half shipped, see doc |
| [0030](0030-manual-review-curated-ascii-library.md) | Manually review the curated ASCII library entries for art clarity and title accuracy before retrieval leans on them | Anubhav -- gag file curated to ~248 entries 2026-09-01 (ADR-0079); informative file no longer loaded |
| [0031](0031-planner-visibility-into-ascii-library-breakdown.md) | Give the card planner a category/example breakdown of the curated ASCII library, so `asset_direction` is written with a sense of what's actually available | unassigned -- blocked on 0030; scope narrowed to gags-only by ADR-0079 |
| [0033](0033-grow-the-curated-ascii-library-over-time.md) | Standing task: keep adding new curated ASCII gag art in small gap-targeted batches as usage exposes coverage holes (gags-only, ADR-0079) | Anubhav -- long-horizon, blocked on 0030 |
| [0035](0035-admin-role-and-production-admin-surface.md) | A real admin-role gate for `/admin/*` and `/dev/*`, so B4's quota view can run in production without an `env` special-case | unassigned |
| [0036](0036-grow-and-tune-the-accent-color-vocabulary.md) | Standing task: verify hues, widen domain coverage, and spot-check `accent_color_data/colors.json` against real embeddings (B6 / ADR-0075 shipped a first list) | Anubhav -- long-horizon |

Tasks 0016-0021 are one sequence. **0016 returned GO (2026-08-31)** — see its
hand-back for the classified findings that scope 0017-0019. 0017-0019 can run in
parallel; 0020 is gated on all three, 0021 on 0020. Read
[ADR-0048](../adr/0048-cockroachdb-over-neon.md) before starting any of them, and
[ADR-0049](../adr/0049-no-message-broker-in-v1.md) before proposing to add Kafka to it.

## Closed

| # | Task | Outcome |
|---|---|---|
| [0016](0016-cockroachdb-spike.md) | CockroachDB viability spike -- go/no-go gate for ADR-0048 | **GO** -- 2026-08-31, `feat/v1-finish-line`. Full findings + scope for 0017-0019 in the doc's hand-back. Harness (compose `crdb` service + `cockroachdb` pyproject extra) committed. |
| [0034](0034-collectionview-rework-saved-notes-liked.md) | Extract one shared `CollectionView` from Liked / Revisit / Notes, sweep the dead `.saved-*` grid CSS (ADR-0072) | Done -- 2026-08-31, `feat/v1-finish-line` (`3bf8373`) -- net -1441/+211 across the 3 views + globals.css, +CollectionView.tsx |
| [0014](0014-unbounded-drafting-rounds.md) | Remove artificial drafting round constraints and allow unbounded completion | Done -- 2026-08-21 |
| [0006](0006-curated-hero-cards.md) | A real curated `is_hero` flag, replacing the "first in station" heuristic | Done -- 2026-08-20, see ADR-0042 |
| [0007](0007-rename-to-spoin.md) | Execute the Slocho → Spoin rename | Done -- 2026-08-17 |
| [0001](0001-topic-threshold-calibration.md) | Topic similarity threshold calibration | Obsolete -- 2026-08-17, superseded by ADR-0025 |
| [0009](0009-batched-topic-matching.md) | Implement batched LLM topic matching (ADR-0025) | Done -- 2026-08-17 |
| [0010](0010-one-shot-pipeline-redesign.md) | Redesign the generation pipeline for one-shot completion (ADR-0026) | Done -- 2026-08-17 |
| [0008](0008-wire-generation-job-worker.md) | Wire `apps/worker` to the generation pipeline | Done -- 2026-08-17 |
| [0027](0027-mobile-shell.md) | A mobile shell -- a floating pill nav, and the right rail becomes a topics sheet | Reverted, then superseded -- see ADR-0063 / [ADR-0064](../adr/0064-mobile-shell-tab-bar.md) / task 0028 |
| [0032](0032-batch-topic-requests.md) | Several custom topics in one batched submission, each with an optional description | Done -- 2026-08-30, `feat/v1-finish-line` (`1f72fc6` API + `3c699fb` web) |

**v1 finish line:** [`docs/handoff/v1-finish-line-plan.md`](../handoff/v1-finish-line-plan.md)
is the build/review/deploy plan for closing out v1 — the remaining frontend and backend
items, the six-pass quality review, and the deployment options. Read its Phase 0 before
picking anything up: several items on it are already shipped.

**Handoff brief:** [`docs/handoff/v3-generation-readiness.md`](../handoff/v3-generation-readiness.md) sequences tasks 0029-0032 plus the corpus backup, embedder fix and prompt-version bump into the order they have to happen for a real generation run.
