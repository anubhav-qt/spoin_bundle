"""Pure-function tests for the deterministic checks in langchain_impl.py that
back ADR-0067's mermaid diagrams and the ASCII duplicate/fence-wrapper fixes.

Kept separate from test_langchain_impl.py (which is already large and mostly
exercises `GeminiContentGenerator` end to end with a mocked chat model) --
these have no mocking, no async, nothing but input in and output out.
"""

from __future__ import annotations

from spoin.generation.langchain_impl import (
    _mermaid_structural_issue,
    _strip_ascii_fence_wrapper,
    _strip_duplicate_scene_from_body,
)

# -- _strip_ascii_fence_wrapper ---------------------------------------------


def test_strips_fence_wrapper_around_ascii_art() -> None:
    wrapped = "```text\n(o_o) POOF!\n / | \\\nMY DATA!\n```"
    assert _strip_ascii_fence_wrapper(wrapped) == "(o_o) POOF!\n / | \\\nMY DATA!"


def test_strips_fence_wrapper_with_no_language_tag() -> None:
    wrapped = "```\nhello\n```"
    assert _strip_ascii_fence_wrapper(wrapped) == "hello"


def test_leaves_unwrapped_art_untouched() -> None:
    art = "(o_o) POOF!\n / | \\"
    assert _strip_ascii_fence_wrapper(art) == art


def test_does_not_strip_backticks_that_are_not_a_wrapping_fence() -> None:
    # A scene that legitimately contains a code-like snippet in its caption
    # must not be treated as fence-wrapped just because it has backticks.
    art = "some art\n`inline code` in a caption"
    assert _strip_ascii_fence_wrapper(art) == art


# -- _strip_duplicate_scene_from_body ----------------------------------------


def test_removes_body_fence_matching_art_exactly() -> None:
    art = "(o_o) POOF!\nMY DATA!"
    body = "Some prose.\n\n```text\n(o_o) POOF!\nMY DATA!\n```\n\nMore prose."
    result = _strip_duplicate_scene_from_body(body, art)
    assert "POOF" not in result
    assert "Some prose." in result
    assert "More prose." in result


def test_removes_body_fence_matching_art_loosely_despite_whitespace_diffs() -> None:
    # Real generator output: the two slots routinely disagree on indentation
    # and blank lines while drawing the identical scene.
    art = "(o_o) POOF!\n / | \\\nMY DATA!"
    body = "Prose.\n\n```text\n  (o_o) POOF!\n\n  / | \\\n   MY DATA!\n```\n"
    result = _strip_duplicate_scene_from_body(body, art)
    assert "POOF" not in result


def test_leaves_body_unchanged_when_no_fence_matches() -> None:
    art = "(o_o) POOF!"
    body = "Prose.\n\n```python\nprint('hi')\n```\n"
    assert _strip_duplicate_scene_from_body(body, art) == body


def test_leaves_body_unchanged_when_art_is_empty() -> None:
    body = "Prose.\n\n```python\nprint('hi')\n```\n"
    assert _strip_duplicate_scene_from_body(body, "") == body


def test_only_removes_the_first_matching_fence_not_every_fence() -> None:
    # A genuinely different second fence (real content, not a duplicate) must
    # survive even though it shares a language tag with the removed one.
    art = "(o_o) POOF!"
    body = (
        "```text\n(o_o) POOF!\n```\n\n"
        "Some prose in between.\n\n"
        "```text\nSOMETHING ELSE ENTIRELY\n```\n"
    )
    result = _strip_duplicate_scene_from_body(body, art)
    assert "POOF" not in result
    assert "SOMETHING ELSE ENTIRELY" in result


# -- _mermaid_structural_issue ------------------------------------------------


def test_valid_flowchart_has_no_issue() -> None:
    source = "flowchart TD\n  A[Client] --> B[Server]\n  B --> C[(DB)]"
    assert _mermaid_structural_issue(source) is None


def test_valid_sequence_diagram_has_no_issue() -> None:
    source = "sequenceDiagram\n  Alice->>Bob: hello\n  Bob-->>Alice: hi"
    assert _mermaid_structural_issue(source) is None


def test_valid_state_diagram_has_no_issue() -> None:
    source = "stateDiagram-v2\n  [*] --> Pending\n  Pending --> Done"
    assert _mermaid_structural_issue(source) is None


def test_valid_timeline_has_no_issue() -> None:
    source = "timeline\n  title Roadmap\n  2020 : launch"
    assert _mermaid_structural_issue(source) is None


def test_empty_source_is_an_issue() -> None:
    assert _mermaid_structural_issue("") is not None
    assert _mermaid_structural_issue("   \n  \n") is not None


def test_unknown_diagram_type_is_an_issue() -> None:
    source = "banana TD\n  A --> B"
    issue = _mermaid_structural_issue(source)
    assert issue is not None
    assert "known mermaid diagram type" in issue


def test_flowchart_with_no_edges_is_an_issue() -> None:
    source = "flowchart TD\n  A[Client]\n  B[Server]"
    issue = _mermaid_structural_issue(source)
    assert issue is not None
    assert "no edges" in issue


def test_unbalanced_brackets_is_an_issue() -> None:
    source = "flowchart TD\n  A[Client --> B[Server]"
    issue = _mermaid_structural_issue(source)
    assert issue is not None
    assert "unbalanced" in issue
