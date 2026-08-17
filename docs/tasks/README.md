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
| [0002](0002-palette-selection-ui.md) | Palette selection UI — onboarding picker + settings switcher | unassigned |
| [0003](0003-personalized-topic-recommendations.md) | Personalized "for you" topic recommendations | unassigned |
| [0004](0004-notes-in-one-place.md) | A single view of all your notes | unassigned |
| [0005](0005-remove-seed-subscriber-baseline.md) | Remove the seeded `subscriber_count` baseline | unassigned |
| [0006](0006-curated-hero-cards.md) | A real curated `is_hero` flag, replacing the "first in station" heuristic | unassigned |
| [0008](0008-wire-generation-job-worker.md) | Wire `apps/worker` to the generation pipeline (depends on 0009, 0010) | unassigned |
| [0009](0009-batched-topic-matching.md) | Implement batched LLM topic matching (ADR-0025) | unassigned |
| [0010](0010-one-shot-pipeline-redesign.md) | Redesign the generation pipeline for one-shot completion (ADR-0026) | unassigned |

## Closed

| # | Task | Outcome |
|---|---|---|
| [0007](0007-rename-to-spoin.md) | Execute the Slocho → Spoin rename | Done — 2026-08-17 |
| [0001](0001-topic-threshold-calibration.md) | Topic similarity threshold calibration | Obsolete — 2026-08-17, superseded by ADR-0025 |
