"""Contract validation for authored curricula: what the projection accepts, and what
`make curriculum-check` hands back as a work item.

No database and no model -- the parser is pure by design, the same as the corpus
contract parser, which is what lets the curriculum-authoring track run it while writing.
"""

from __future__ import annotations

from frog.curriculum.contract import (
    MAX_TARGET_CARDS,
    ParsedCurriculum,
    parse_curriculum,
)

VALID = b"""---
topic: Rust
description: Systems programming with ownership, borrowing and fearless concurrency
is_survey: false
subtopics:
  - title: Ownership & Move Semantics
    description: Why a value has exactly one owner, and what a move costs
    prerequisites: []
    sources:
      - computer-science/programming-languages/rust/foundations.md
    tiers:
      beginner:
        target_cards: 18
        card_types: { prose: 8, code: 6, comparison: 2, ascii: 2 }
      intermediate:
        target_cards: 14
        card_types: { prose: 5, code: 6, diagram: 1, ascii: 2 }
  - title: Smart Pointers
    description: Heap ownership, shared ownership, and what each pointer costs
    prerequisites: [Ownership & Move Semantics]
    sources:
      - computer-science/programming-languages/rust/smart-pointers.md
    tiers:
      intermediate:
        target_cards: 15
        card_types: { prose: 6, code: 7, ascii: 2 }
---
"""


def _parse(raw: bytes) -> tuple[ParsedCurriculum | None, list[str]]:
    curriculum, errors = parse_curriculum("rust/curriculum.md", raw)
    return curriculum, errors.problems


def test_valid_curriculum_parses_clean() -> None:
    curriculum, problems = _parse(VALID)
    assert problems == []
    assert curriculum is not None
    assert curriculum.topic == "Rust"
    assert curriculum.is_survey is False
    assert [s.title for s in curriculum.subtopics] == [
        "Ownership & Move Semantics",
        "Smart Pointers",
    ]
    first = curriculum.subtopics[0]
    assert {t.tier for t in first.tiers} == {"beginner", "intermediate"}
    assert first.tiers[0].card_types == {"prose": 8, "code": 6, "comparison": 2, "ascii": 2}
    assert curriculum.content_hash  # carried for task 2's idempotency


def test_no_front_matter() -> None:
    curriculum, problems = _parse(b"# Rust\n\njust prose\n")
    assert curriculum is None
    assert any("front matter" in p for p in problems)


def test_prose_body_after_front_matter_is_rejected() -> None:
    raw = VALID.rstrip() + b"\n\nSome stray authoring notes.\n"
    _, problems = _parse(raw)
    assert any("no prose body" in p for p in problems)


def test_missing_top_level_fields_all_reported_at_once() -> None:
    _, problems = _parse(b"---\nsubtopics: []\n---\n")
    joined = "\n".join(problems)
    assert "`topic` is missing" in joined
    assert "`description` is missing" in joined
    assert "`is_survey` is missing" in joined


def test_is_survey_must_be_bool() -> None:
    raw = VALID.replace(b"is_survey: false", b"is_survey: maybe")
    _, problems = _parse(raw)
    assert any("`is_survey` must be `true` or `false`" in p for p in problems)


def test_subtopics_must_be_non_empty() -> None:
    _, problems = _parse(b"---\ntopic: X\ndescription: y\nis_survey: false\nsubtopics: []\n---\n")
    assert any("`subtopics` must be a non-empty list" in p for p in problems)


def test_subtopic_missing_fields_named_with_the_subtopic() -> None:
    raw = b"""---
topic: Rust
description: d
is_survey: false
subtopics:
  - title: Ownership
    prerequisites: []
    sources: [computer-science/x.md]
---
"""
    _, problems = _parse(raw)
    assert any("subtopic 'Ownership': `description` is missing" in p for p in problems)
    assert any("subtopic 'Ownership': `tiers` is missing" in p for p in problems)


def test_unknown_tier_name() -> None:
    raw = VALID.replace(b"beginner:", b"novice:")
    _, problems = _parse(raw)
    assert any("unknown tier 'novice'" in p for p in problems)


def test_unknown_card_type() -> None:
    raw = VALID.replace(b"{ prose: 6, code: 7, ascii: 2 }", b"{ prose: 6, code: 7, meme: 2 }")
    _, problems = _parse(raw)
    assert any("unknown card type 'meme'" in p for p in problems)


def test_target_cards_below_band() -> None:
    raw = VALID.replace(b"target_cards: 15", b"target_cards: 3").replace(
        b"{ prose: 6, code: 7, ascii: 2 }", b"{ prose: 1, code: 1, ascii: 1 }"
    )
    _, problems = _parse(raw)
    assert any("outside the 5-25 band" in p for p in problems)


def test_target_cards_above_band() -> None:
    raw = VALID.replace(
        b"target_cards: 15", bytes(f"target_cards: {MAX_TARGET_CARDS + 1}", "ascii")
    )
    _, problems = _parse(raw)
    assert any("outside the 5-25 band" in p for p in problems)


def test_card_types_must_sum_to_target_cards() -> None:
    raw = VALID.replace(
        b"target_cards: 18\n        card_types: { prose: 8, code: 6, comparison: 2, ascii: 2 }",
        b"target_cards: 18\n        card_types: { prose: 8, code: 6, comparison: 2, ascii: 1 }",
    )
    _, problems = _parse(raw)
    assert any("sums to 17, not `target_cards` (18)" in p for p in problems)


def test_prerequisite_must_resolve_within_the_file() -> None:
    raw = VALID.replace(
        b"prerequisites: [Ownership & Move Semantics]", b"prerequisites: [Lifetimes]"
    )
    _, problems = _parse(raw)
    assert any("prerequisite 'Lifetimes' is not a subtopic" in p for p in problems)


def test_prerequisite_cycle_is_reported_as_a_path() -> None:
    raw = b"""---
topic: Rust
description: d
is_survey: false
subtopics:
  - title: A
    description: d
    prerequisites: [B]
    sources: [computer-science/x.md]
    tiers: { beginner: { target_cards: 5, card_types: { prose: 5 } } }
  - title: B
    description: d
    prerequisites: [A]
    sources: [computer-science/x.md]
    tiers: { beginner: { target_cards: 5, card_types: { prose: 5 } } }
---
"""
    _, problems = _parse(raw)
    assert any("prerequisite cycle:" in p and "->" in p for p in problems)


def test_self_prerequisite() -> None:
    raw = VALID.replace(
        b"prerequisites: [Ownership & Move Semantics]", b"prerequisites: [Smart Pointers]"
    )
    _, problems = _parse(raw)
    assert any("lists itself as a prerequisite" in p for p in problems)


def test_duplicate_titles() -> None:
    raw = VALID.replace(b"title: Smart Pointers", b"title: Ownership & Move Semantics")
    _, problems = _parse(raw)
    assert any("duplicate title" in p for p in problems)
