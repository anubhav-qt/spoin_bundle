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

import re

from spoin.content.archetype import classify_archetype
from spoin.domain.enums import VisualKind
from spoin.generation.base import CardDraft
from spoin.generation.pipeline.state import is_technical_topic

_ASCII_MAX_WIDTH = 40


def passes_minimal_gate(
    draft: CardDraft, *, topic_name: str | None = None
) -> tuple[bool, str | None]:
    """Structural validation only. Returns (passed, reason_if_rejected).

    `CardDraft`'s own field constraints (max/min length) already reject malformed
    items before they reach `BatchResult.items` (ADR-0005) — this is the thin layer
    of checks that need the *combination* of fields, which Pydantic field
    constraints alone can't express.
    """

    if not draft.body.strip():
        return False, "empty body"

    # Reading length discipline: measure prose text only (excluding diagrams and code fences)
    prose_body = re.sub(r"```[\s\S]*?```", "", draft.body).strip()
    if len(prose_body) > 1200:
        return False, f"body is a text wall ({len(prose_body)} prose chars > 1200 max)"

    # Non-technical topic rule: code blocks are strictly forbidden (code: 0)
    if topic_name is not None and not is_technical_topic(topic_name):
        tags = classify_archetype(draft.body)
        if "code" in tags:
            return (
                False,
                f"code blocks are strictly forbidden for non-technical topic {topic_name!r}",
            )

    # Editorial leakage guard: correction notes must never appear in body
    if re.search(r"(?i)(\*Source Note|\*\*Key Correction|\*\*Correction:)", draft.body):
        return False, "body contains leaked editorial correction notes"

    # ASCII Box Rule & Library Policy Invariants (ADR-0021, ADR-0079, ADR-0099)
    if draft.visual_kind is VisualKind.ASCII or (
        isinstance(draft.visual_slots, dict) and "art" in draft.visual_slots
    ):
        slots = draft.visual_slots or {}
        art = str(slots.get("art", ""))
        if not art.strip():
            return False, "ASCII art is empty"

        # 1. Box Rule: Every line <= 40 columns
        for n, line in enumerate(art.split("\n"), start=1):
            if len(line) > _ASCII_MAX_WIDTH:
                return (
                    False,
                    f"ASCII box rule violated: line {n} exceeds {_ASCII_MAX_WIDTH} cols "
                    f"({len(line)} chars: {line[:45]!r})",
                )

        # 2. Caption Invariant: Must carry non-empty alt caption
        if not str(slots.get("alt", "")).strip():
            return False, "ASCII box rule violated: missing alt caption"

    return True, None
