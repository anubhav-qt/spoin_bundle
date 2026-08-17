"""Hand-curated, topic-agnostic examples of each difficulty tier (ADR-0030).

Schema/plumbing exists now; the catalog itself does not -- same "build the schema
half now" pattern as ADR-0021's ASCII scene catalog. `get_difficulty_examples()`
returns an empty list per tier until docs/tasks/0011 authors real content; callers
must treat that as "no examples available," never as an error.

Only meaningful for STANDALONE subtopic-tiers (no sibling tiers sharing the same
`subtopic_group_id`). A LINKED tier already gets real, concept-specific calibration
for free from `builds_on` (ADR-0026) -- its own actual lower-tier cards -- which
beats a generic example. See generation/pipeline.py's `_is_standalone` usage.
"""

from __future__ import annotations

from spoin.domain.enums import Difficulty


def get_difficulty_examples() -> dict[Difficulty, list[str]]:
    return {difficulty: [] for difficulty in Difficulty}
