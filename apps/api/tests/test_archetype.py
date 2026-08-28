"""content/archetype.py -- deterministic classification, no fixtures needed.

Written alongside the ADR-0067 mermaid fix: `classify_archetype` had never had
a dedicated test, and mermaid's absence from `_DIAGRAM_LANG_TAGS` shipped
unnoticed as a result -- a ```mermaid fence classified as `code`, not
`diagram`, because a real-looking language tag fell into the "else has_code"
branch. That misclassification fed the pipeline's per-tier quota accounting
(pipeline/state.py's `_card_matches_type`) and the feed's archetype-diversity
spread (feed/ranking.py's `_primary_archetype`), so a wrong tag here has real
consequences downstream, not just a cosmetic one.
"""

from __future__ import annotations

from spoin.content.archetype import classify_archetype


def test_mermaid_flowchart_is_diagram_not_code() -> None:
    body = "```mermaid\nflowchart TD\n  A[Client] --> B[Server]\n```"
    assert classify_archetype(body) == ["diagram"]


def test_mermaid_sequence_diagram_is_diagram_without_ascii_arrows() -> None:
    # sequenceDiagram uses `->>`, not `-->` -- the old code path only reached
    # `has_diagram` via `_DIAGRAM_CHARS`, which this text never matches.
    body = "```mermaid\nsequenceDiagram\n  Alice->>Bob: hello\n```"
    assert classify_archetype(body) == ["diagram"]


def test_mermaid_timeline_is_diagram_with_no_arrows_at_all() -> None:
    body = "```mermaid\ntimeline\n  title Roadmap\n  2020 : launch\n```"
    assert classify_archetype(body) == ["diagram"]


def test_legacy_ascii_diagram_fence_still_classifies_as_diagram() -> None:
    body = "```text\nClient --> [LB]\n```"
    assert classify_archetype(body) == ["diagram"]


def test_real_code_fence_still_classifies_as_code() -> None:
    body = "```python\ndef f():\n    return 1\n```"
    assert classify_archetype(body) == ["code"]


def test_card_with_both_code_and_mermaid_gets_both_tags() -> None:
    body = "```python\nprint('hi')\n```\n\n```mermaid\nflowchart TD\n  A --> B\n```"
    assert set(classify_archetype(body)) == {"code", "diagram"}


def test_comparison_marker_pair_still_tags_comparison() -> None:
    body = "❌ **Myth**: wrong\n✅ **Fact**: right"
    assert classify_archetype(body) == ["comparison"]


def test_plain_prose_has_no_tags() -> None:
    assert classify_archetype("Just an explanation, no fences, no markers.") == []
