"""The quality gate — minimal pass-through version.

content-model.md specifies four checks: near-duplicate detection, topic conformance,
independent difficulty/factual-accuracy judging. **None of those are implemented
here.** This module only does structural validation — the checks that are cheap,
local, and already possible with today's schema — so the first generation vertical
slice has *something* standing between a `CardDraft` and `active` status rather than
nothing, while the real gate (local embeddings, intra-batch dedup, the batch judge)
is built as its own step. See docs/tasks for that follow-up.

A card that fails here is simply never inserted — there is no `draft` holding pattern
today because there is nothing yet that would later promote a `draft` to `active`.
That step returns once the real gate exists.
"""

from __future__ import annotations

from slocho.generation.base import CardDraft


def passes_minimal_gate(draft: CardDraft) -> tuple[bool, str | None]:
    """Structural validation only. Returns (passed, reason_if_rejected).

    `CardDraft`'s own field constraints (max/min length) already reject malformed
    items before they reach `BatchResult.items` (ADR-0005) — this is the thin layer
    of checks that need the *combination* of fields, which Pydantic field
    constraints alone can't express.
    """

    if not draft.body.strip():
        return False, "empty body"
    return True, None
