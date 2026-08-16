"""Classifies which content shapes a card's `body` actually contains.

ADR-0017. Deterministic, not LLM-judged: unlike `difficulty` (a subjective call,
which is why `judge_difficulty` exists as an independent rating rather than a
self-report — see generation/base.py), "does this body contain a fenced code
block" is objectively true or false from the text itself. Asking a model to also
tag it would just be a second, occasionally-wrong source of truth for something
a regex gets right for free.

A card can carry more than one tag — a card can genuinely have prose, a code
snippet, AND a diagram. Rendering (the web client) picks a priority order for
the COLLAPSED-state teaser only; the expanded view always shows the full body,
so every tag's content is visible regardless of which one "won" the teaser.
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"```([a-zA-Z0-9_-]*)\n(.*?)```", re.DOTALL)

#: A fenced block explicitly tagged as a diagram, or one whose content is
#: mostly box-drawing/arrow characters rather than a real language.
_DIAGRAM_LANG_TAGS = {"diagram", "text", "ascii", ""}
_DIAGRAM_CHARS = re.compile(r"[─│┌└┐┘├┤┬┴┼→▶►]|-->|==>|──>")

_COMPARISON_MARKERS = ("❌", "✅")


def classify_archetype(body: str) -> list[str]:
    """Pure function: `body` in, tags out. No I/O, no model call."""

    tags: list[str] = []

    has_code = False
    has_diagram = False
    for lang, content in _FENCE.findall(body):
        lang = lang.lower()
        if lang not in _DIAGRAM_LANG_TAGS:
            has_code = True
        elif _DIAGRAM_CHARS.search(content) or lang == "diagram":
            has_diagram = True
        elif content.strip():
            # A fenced block with no language tag and no diagram characters —
            # still a code block (e.g. a shell transcript without ```bash).
            has_code = True

    # Diagram characters can also appear outside a fence in a body that's
    # otherwise prose-plus-arrows; still worth flagging as a diagram archetype.
    if not has_diagram and _DIAGRAM_CHARS.search(body):
        has_diagram = True

    if has_code:
        tags.append("code")
    if has_diagram:
        tags.append("diagram")
    if all(marker in body for marker in _COMPARISON_MARKERS):
        tags.append("comparison")

    return tags
