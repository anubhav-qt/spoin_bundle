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
from spoin.content.readability import flesch_kincaid_grade
from spoin.core.config import get_settings
from spoin.domain.enums import VisualKind
from spoin.generation.base import CardDraft
from spoin.generation.pipeline.state import is_technical_topic

_ASCII_MAX_WIDTH = 40

#: Codepoints that render TWO monospace columns while counting as one character.
#:
#: This is why the width check above was passing on visibly broken art: a line of 38
#: characters containing three emoji draws as 44 columns, and nothing measuring
#: `len(line)` can see it. The rule is stated to the writer in the ASCII box canon and
#: enforced here, which is CLAUDE.md's "a hard rule gets enforced, never merely
#: documented".
#:
#: Ranges rather than a library: this needs no network, no data file and no dependency
#: in the api image (ADR-0094), and the East Asian Wide/Fullwidth blocks plus the emoji
#: planes are the whole of what a drafting model actually reaches for.
_DOUBLE_WIDTH_RANGES = (
    (0x1100, 0x115F),  # Hangul Jamo
    (0x2600, 0x27BF),  # Misc symbols and dingbats
    (0x2E80, 0xA4CF),  # CJK radicals through Yi
    (0xAC00, 0xD7A3),  # Hangul syllables
    (0xF900, 0xFAFF),  # CJK compatibility ideographs
    (0xFE30, 0xFE4F),  # CJK compatibility forms
    (0xFF00, 0xFF60),  # Fullwidth forms
    (0xFFE0, 0xFFE6),
    (0x1F000, 0x1FAFF),  # Emoji planes
)


def _double_width_chars(text: str) -> list[str]:
    """Every double-width character in `text`, in order, deduplicated."""

    found: list[str] = []
    for char in text:
        point = ord(char)
        if any(low <= point <= high for low, high in _DOUBLE_WIDTH_RANGES) and char not in found:
            found.append(char)
    return found


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

    #: Register discipline (ADR-0104). The SAME ceiling at all three tiers, because
    #: difficulty is what a card covers and never how hard it reads. Rejected here
    #: rather than merely asked for in the prompt: the canon has told the writer not
    #: to inherit its grounding material's register for as long as grounding has
    #: existed, and Astronomy's cards came out at college register at every tier
    #: anyway. A prompt rule with no check is a wish (CLAUDE.md).
    #:
    #: The reason lands in `rejection_feedback` and is shown to the next attempt, so
    #: this is a correcting signal rather than a wall.
    #: `<= 0` means "not calibrated yet" and skips the check entirely -- see the
    #: setting's own comment for why shipping a guessed ceiling is worse than
    #: shipping none.
    ceiling = get_settings().register_max_grade
    grade = flesch_kincaid_grade(draft.body) if ceiling > 0 else None
    if grade is not None and grade > ceiling:
        return (
            False,
            f"reads at grade {grade:.1f}, above the grade {ceiling:.1f} ceiling that applies "
            f"at every tier -- shorter sentences, plainer words, address the reader as "
            f"'you'; an advanced idea is still written plainly",
        )

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

        #: Checked BEFORE the width loop, because it is the reason the width loop
        #: could report a pass on art that is visibly over budget.
        wide = _double_width_chars(art)
        if wide:
            return (
                False,
                f"ASCII box rule violated: {''.join(wide)!r} render two monospace columns "
                f"each, so the 40-column budget is broken without the character count "
                f"showing it -- draw with plain ASCII",
            )

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
