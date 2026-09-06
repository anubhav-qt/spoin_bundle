"""The one cross-file check: every `grounding` reference must exist under the corpus tree.

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
    tiers:
      beginner:
        target_cards: 5
        card_types: {{ prose: 5 }}
        grounding:
          - "{source}#Ownership Foundations"
---
"""

SAMPLE_CORPUS_DOC = """---
kind: topic_source
title: Ownership
source: Rust Reference
scope: topic
category: computer-science
topic_tags: [rust]
---
## Ownership Foundations
Every value in Rust has an owner that determines its lifespan.
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
        (corpus / "computer-science" / "ownership.md").write_text(
            SAMPLE_CORPUS_DOC, encoding="utf-8"
        )
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
        "grounding document 'computer-science/typo.md' does not exist" in p
        for p in failures[0].problems
    )


def test_missing_heading_fails(tmp_path: Path) -> None:
    curricula = tmp_path / "curricula"
    corpus = tmp_path / "corpus"
    (curricula / "rust").mkdir(parents=True)
    (corpus / "computer-science").mkdir(parents=True)
    bad_curriculum = CURRICULUM.replace("Ownership Foundations", "Nonexistent Heading").format(
        source="computer-science/ownership.md"
    )
    (curricula / "rust" / "curriculum.md").write_text(bad_curriculum, encoding="utf-8")
    (corpus / "computer-science" / "ownership.md").write_text(SAMPLE_CORPUS_DOC, encoding="utf-8")

    passed, failures = validate_curricula(curricula, corpus)
    assert passed == []
    assert len(failures) == 1
    assert any("has no `## Nonexistent Heading` section" in p for p in failures[0].problems)


def test_no_curricula_is_clean(tmp_path: Path) -> None:
    (tmp_path / "curricula").mkdir()
    (tmp_path / "corpus").mkdir()
    passed, failures = validate_curricula(tmp_path / "curricula", tmp_path / "corpus")
    assert passed == []
    assert failures == []


def test_a_prefix_of_a_real_heading_is_not_a_match(tmp_path: Path) -> None:
    """The bug a substring search has and a parser does not.

    `## Ownership Foundations` must NOT satisfy a reference to `#Ownership`. Searching
    the file for the heading text passes this; asking the same parser the ingester
    chunks with does not -- and agreeing with the chunker is the point, because a
    reference that validates here has to resolve to a row after ingestion.
    """

    curricula = tmp_path / "curricula"
    corpus = tmp_path / "corpus"
    (curricula / "rust").mkdir(parents=True)
    (corpus / "computer-science").mkdir(parents=True)
    (curricula / "rust" / "curriculum.md").write_text(
        CURRICULUM.replace("#Ownership Foundations", "#Ownership").format(
            source="computer-science/ownership.md"
        ),
        encoding="utf-8",
    )
    (corpus / "computer-science" / "ownership.md").write_text(SAMPLE_CORPUS_DOC, encoding="utf-8")

    passed, failures = validate_curricula(curricula, corpus)
    assert passed == []
    assert any("has no `## Ownership` section" in p for p in failures[0].problems)


def test_a_near_miss_heading_is_named(tmp_path: Path) -> None:
    """These references are long strings copied by hand; the likely failure is a
    truncation or a typo, not an invented section. Naming the near miss turns a
    delivery round-trip into a one-line fix."""

    curricula = tmp_path / "curricula"
    corpus = tmp_path / "corpus"
    (curricula / "rust").mkdir(parents=True)
    (corpus / "computer-science").mkdir(parents=True)
    (curricula / "rust" / "curriculum.md").write_text(
        CURRICULUM.replace("Ownership Foundations", "Ownership Foundatons").format(
            source="computer-science/ownership.md"
        ),
        encoding="utf-8",
    )
    (corpus / "computer-science" / "ownership.md").write_text(SAMPLE_CORPUS_DOC, encoding="utf-8")

    _passed, failures = validate_curricula(curricula, corpus)
    assert any("did you mean 'Ownership Foundations'?" in p for p in failures[0].problems)


def test_a_document_that_fails_the_corpus_contract_says_so(tmp_path: Path) -> None:
    """Distinct from a missing heading: the author's next move is different. A document
    the ingester will reject has no sections to name, so reporting "no such heading"
    would send them hunting for a typo that isn't there."""

    curricula = tmp_path / "curricula"
    corpus = tmp_path / "corpus"
    (curricula / "rust").mkdir(parents=True)
    (corpus / "computer-science").mkdir(parents=True)
    (curricula / "rust" / "curriculum.md").write_text(
        CURRICULUM.format(source="computer-science/ownership.md"), encoding="utf-8"
    )
    # No front matter at all -- `parse_document` refuses it.
    (corpus / "computer-science" / "ownership.md").write_text(
        "## Ownership Foundations\nprose\n", encoding="utf-8"
    )

    _passed, failures = validate_curricula(curricula, corpus)
    assert any("does not satisfy the corpus contract" in p for p in failures[0].problems)
