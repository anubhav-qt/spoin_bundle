"""The one cross-file check: every `sources` path must exist under the corpus tree.

Still no database and no model -- just a walk of two directories.
"""

from __future__ import annotations

from pathlib import Path

from frog.curriculum.runner import validate_curricula

CURRICULUM = """---
topic: Rust
description: Systems programming with ownership and borrowing
is_survey: false
subtopics:
  - title: Ownership
    description: One owner per value
    prerequisites: []
    sources:
      - {source}
    tiers:
      beginner:
        target_cards: 5
        card_types: {{ prose: 5 }}
---
"""


def _tree(tmp_path: Path, source_in_file: str, *, create_source: bool) -> tuple[Path, Path]:
    curricula = tmp_path / "curricula"
    corpus = tmp_path / "corpus"
    (curricula / "rust").mkdir(parents=True)
    (corpus / "computer-science").mkdir(parents=True)
    (curricula / "rust" / "curriculum.md").write_text(
        CURRICULUM.format(source=source_in_file), encoding="utf-8"
    )
    if create_source:
        (corpus / "computer-science" / "ownership.md").write_text("x", encoding="utf-8")
    return curricula, corpus


def test_existing_source_passes(tmp_path: Path) -> None:
    curricula, corpus = _tree(tmp_path, "computer-science/ownership.md", create_source=True)
    passed, failures = validate_curricula(curricula, corpus)
    assert failures == []
    assert [c.topic for c in passed] == ["Rust"]
    assert passed[0].source_path == "rust/curriculum.md"


def test_missing_source_fails_with_the_subtopic_and_path(tmp_path: Path) -> None:
    curricula, corpus = _tree(tmp_path, "computer-science/typo.md", create_source=True)
    passed, failures = validate_curricula(curricula, corpus)
    assert passed == []
    assert len(failures) == 1
    assert any(
        "subtopic 'Ownership': source 'computer-science/typo.md' does not exist" in p
        for p in failures[0].problems
    )


def test_no_curricula_is_clean(tmp_path: Path) -> None:
    (tmp_path / "curricula").mkdir()
    (tmp_path / "corpus").mkdir()
    passed, failures = validate_curricula(tmp_path / "curricula", tmp_path / "corpus")
    assert passed == []
    assert failures == []
