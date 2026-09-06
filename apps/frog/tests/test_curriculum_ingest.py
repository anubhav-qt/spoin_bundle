"""Ingesting curricula into `the_spoin_universe`: idempotent, and a revision replaces.

Database-backed because that is what is under test -- `source_path` UNIQUE, the
`ondelete=CASCADE` on `curriculum_subtopic`, and re-ingest writing nothing. Skipped when
`SPOIN_UNIVERSE_TEST_DATABASE_URL` is unset; see conftest.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from frog.curriculum.models import Curriculum, CurriculumSubtopic
from frog.curriculum.runner import ingest_curricula

_CORPUS_DOC = """---
kind: topic_source
title: Rust reference material
source: The Rust Reference
scope: topic
category: computer-science
topic_tags: [rust]
---
## {heading}
Reference prose for the {heading} section.
"""

_TEMPLATE = """---
topic: Rust
description: {description}
is_survey: false
subtopics:
  - title: Ownership
    description: One owner per value
    prerequisites: []
    tiers:
      beginner:
        target_cards: 6
        card_types: {{ prose: 4, code: 2 }}
        grounding:
          - "cs/ownership.md#Ownership"
  - title: Smart Pointers
    description: Heap and shared ownership
    prerequisites: [Ownership]
    tiers:
      intermediate:
        target_cards: 8
        card_types: {{ prose: 5, code: 3 }}
        grounding:
          - "cs/pointers.md#Smart Pointers"
---
"""


def _tree(tmp_path: Path, *, description: str = "Systems programming") -> tuple[Path, Path]:
    curricula = tmp_path / "curricula"
    corpus = tmp_path / "corpus"
    (curricula / "rust").mkdir(parents=True)
    (corpus / "cs").mkdir(parents=True)
    for name, heading in (("ownership.md", "Ownership"), ("pointers.md", "Smart Pointers")):
        (corpus / "cs" / name).write_text(_CORPUS_DOC.format(heading=heading), encoding="utf-8")
    (curricula / "rust" / "curriculum.md").write_text(
        _TEMPLATE.format(description=description), encoding="utf-8"
    )
    return curricula, corpus


async def _counts(session: AsyncSession) -> tuple[int, int]:
    curricula = await session.scalar(select(func.count()).select_from(Curriculum))
    subtopics = await session.scalar(select(func.count()).select_from(CurriculumSubtopic))
    return curricula or 0, subtopics or 0


@pytest.mark.asyncio
async def test_ingest_then_reingest_is_a_noop(session: AsyncSession, tmp_path: Path) -> None:
    curricula, corpus = _tree(tmp_path)

    first = await ingest_curricula(session, curricula, corpus)
    await session.commit()
    assert first.ingested == 1
    assert await _counts(session) == (1, 2)

    second = await ingest_curricula(session, curricula, corpus)
    await session.commit()
    assert second.ingested == 0
    assert second.unchanged == 1
    assert await _counts(session) == (1, 2)


@pytest.mark.asyncio
async def test_revision_replaces_subtopics_in_place(session: AsyncSession, tmp_path: Path) -> None:
    curricula, corpus = _tree(tmp_path)
    await ingest_curricula(session, curricula, corpus)
    await session.commit()
    original_id = await session.scalar(select(Curriculum.id))

    # Rewrite the file: one subtopic instead of two, and a changed description.
    (curricula / "rust" / "curriculum.md").write_text(
        """---
topic: Rust
description: Now with fewer subtopics
is_survey: false
subtopics:
  - title: Ownership
    description: One owner per value
    prerequisites: []
    tiers:
      beginner:
        target_cards: 6
        card_types: { prose: 6 }
        grounding: ["cs/ownership.md#Ownership"]
---
""",
        encoding="utf-8",
    )

    report = await ingest_curricula(session, curricula, corpus)
    await session.commit()
    assert report.ingested == 1

    # Same curriculum row (id preserved), subtopics rebuilt, orphan CASCADE-deleted.
    assert await session.scalar(select(Curriculum.id)) == original_id
    curriculum = await session.scalar(select(Curriculum))
    assert curriculum is not None
    assert curriculum.description == "Now with fewer subtopics"
    assert await _counts(session) == (1, 1)
    remaining = await session.scalar(select(CurriculumSubtopic))
    assert remaining is not None
    assert remaining.title == "Ownership"
    assert remaining.tiers == {
        "beginner": {
            "target_cards": 6,
            "card_types": {"prose": 6},
            #: The declared scope rides in the tier JSONB, which is what the projection
            #: reads to fill `subtopic.grounding_refs`.
            "grounding": ["cs/ownership.md#Ownership"],
        }
    }


@pytest.mark.asyncio
async def test_invalid_curriculum_is_reported_not_written(
    session: AsyncSession, tmp_path: Path
) -> None:
    curricula, corpus = _tree(tmp_path)
    (curricula / "broken").mkdir()
    (curricula / "broken" / "curriculum.md").write_text(
        "---\ntopic: Broken\ndescription: d\nis_survey: false\nsubtopics: []\n---\n",
        encoding="utf-8",
    )

    report = await ingest_curricula(session, curricula, corpus)
    await session.commit()
    assert report.ingested == 1
    assert report.failed == 1
    assert report.has_failures
    assert await _counts(session) == (1, 2)  # only the valid one landed
