"""Contextual chunk headers (rag-design-space 3.8).

Cheap to get right and expensive to notice when wrong: a missing header does not fail,
it just makes a chunk marginally harder to retrieve and impossible for a reading model
to attribute. That is the failure shape these tests exist for.
"""

from __future__ import annotations

from frog.ingest.chunking import chunk_texts, contextual_text
from frog.ingest.contract import parse_document

VALID = b"""---
title: CSS layout and stacking contexts
kind: topic_source
category: computer science
scope: survey
source: https://www.w3.org/TR/css-position-3/
topic_tags:
  - css
---

## The stacking context trap

The root cause is that z-index does not operate globally across the document.

## CSS layout and stacking contexts

A section whose heading restates the document title.
"""


def test_the_header_names_the_document_and_the_section() -> None:
    """The prose in the first section never says CSS, frontend, or which document it
    came from — which is exactly the case the header exists for."""

    document, errors = parse_document("x.md", VALID)

    assert not errors
    assert document is not None
    first = chunk_texts(document)[0]
    assert first.startswith("CSS layout and stacking contexts — The stacking context trap\n\n")
    assert "z-index does not operate globally" in first


def test_a_heading_that_restates_the_title_is_not_repeated() -> None:
    """Spending prompt tokens saying the same thing twice is the one cost of the
    header, and it is avoidable."""

    document, _ = parse_document("x.md", VALID)

    assert document is not None
    second = chunk_texts(document)[1]
    assert second.startswith("CSS layout and stacking contexts\n\n")
    assert "—" not in second.split("\n\n")[0]


def test_the_header_is_part_of_the_stored_text() -> None:
    """Owner's decision, 2026-09-05: the header is stored, not merely embedded.

    Embedding a string the stored text does not contain is the silent-divergence shape
    ADR-0092 was written about — the vector and the prompt would describe different
    things and nothing would raise. Re-ingestion is minutes on a GPU, so the cost of
    this choice is a rebuild the corpus is designed for.
    """

    document, _ = parse_document("x.md", VALID)

    assert document is not None
    text = contextual_text(document, "The stacking context trap", "Body prose.")
    assert text == "CSS layout and stacking contexts — The stacking context trap\n\nBody prose."


def test_one_chunk_per_section_in_document_order() -> None:
    """`ordinal` is what makes a chunk citable as "part 3 of" and lets retrieval widen
    a hit to its neighbours later without guessing."""

    document, _ = parse_document("x.md", VALID)

    assert document is not None
    assert len(chunk_texts(document)) == len(document.sections) == 2
