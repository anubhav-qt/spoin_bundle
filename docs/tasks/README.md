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
| [0016](0016-cockroachdb-spike.md) | CockroachDB viability spike -- **go/no-go gate for ADR-0048** | unassigned |
| [0017](0017-sql-portability-fixes.md) | Fix the Postgres-only SQL the spike found | blocked on 0016 |
| [0018](0018-alembic-on-cockroachdb.md) | Make the Alembic chain apply cleanly on CockroachDB | blocked on 0016 |
| [0019](0019-transaction-retry-boundary.md) | A transaction retry boundary for CockroachDB's `40001` errors | blocked on 0016 |
| [0020](0020-corpus-migration-and-parity.md) | Move the live corpus to CockroachDB, and prove nothing was lost | blocked on 0017-0019 |
| [0021](0021-cockroachdb-cutover.md) | Cut over to CockroachDB Basic, and instrument both meters | blocked on 0020 |

Tasks 0016-0021 are one sequence, gated on 0016. Read
[ADR-0048](../adr/0048-cockroachdb-over-neon.md) before starting any of them, and
[ADR-0049](../adr/0049-no-message-broker-in-v1.md) before proposing to add Kafka to it.

## Closed

| # | Task | Outcome |
|---|---|---|
| [0014](0014-unbounded-drafting-rounds.md) | Remove artificial drafting round constraints and allow unbounded completion | Done -- 2026-08-21 |
| [0006](0006-curated-hero-cards.md) | A real curated `is_hero` flag, replacing the "first in station" heuristic | Done -- 2026-08-20, see ADR-0042 |
| [0007](0007-rename-to-spoin.md) | Execute the Slocho → Spoin rename | Done -- 2026-08-17 |
| [0001](0001-topic-threshold-calibration.md) | Topic similarity threshold calibration | Obsolete -- 2026-08-17, superseded by ADR-0025 |
| [0009](0009-batched-topic-matching.md) | Implement batched LLM topic matching (ADR-0025) | Done -- 2026-08-17 |
| [0010](0010-one-shot-pipeline-redesign.md) | Redesign the generation pipeline for one-shot completion (ADR-0026) | Done -- 2026-08-17 |
| [0008](0008-wire-generation-job-worker.md) | Wire `apps/worker` to the generation pipeline | Done -- 2026-08-17 |
