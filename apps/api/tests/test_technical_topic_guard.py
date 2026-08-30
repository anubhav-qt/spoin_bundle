"""Tests for the non-technical code archetype guard (is_technical_topic,
_card_matches_type with topic_name) and the dynamic question budget
allocation (target_questions in _load_subtopic_plans).

Pure logic; no DB fixtures needed for the guard tests.
"""

from __future__ import annotations

import pytest

from spoin.domain.enums import CardType, Difficulty
from spoin.generation.base import CardDraft
from spoin.generation.pipeline.state import _card_matches_type, is_technical_topic

# ── is_technical_topic ───────────────────────────────────────────────

_TECHNICAL_TOPICS = [
    "Python Programming",
    "Data Structures and Algorithms",
    "Web Development with React",
    "Machine Learning Fundamentals",
    "Introduction to SQL",
    "Docker and Kubernetes",
    "Computer Science 101",
    "Advanced JavaScript",
]

_NON_TECHNICAL_TOPICS = [
    "Bhagvad Geeta in Easy Language",
    "World History",
    "Organic Chemistry",
    "Psychology 101",
    "Indian Classical Music",
    "Philosophy of Mind",
    "Art of War",
    "Stoic Philosophy",
]


@pytest.mark.parametrize("name", _TECHNICAL_TOPICS)
def test_technical_topic_recognized(name: str) -> None:
    assert is_technical_topic(name)


@pytest.mark.parametrize("name", _NON_TECHNICAL_TOPICS)
def test_non_technical_topic_recognized(name: str) -> None:
    assert not is_technical_topic(name)


def test_case_insensitive() -> None:
    assert is_technical_topic("PYTHON programming")
    assert is_technical_topic("python PROGRAMMING")


def test_java_trailing_space_avoids_japanese() -> None:
    assert not is_technical_topic("Japanese Culture")
    assert is_technical_topic("Java Fundamentals")


# ── _card_matches_type with topic guard ──────────────────────────────


def _code_draft() -> CardDraft:
    return CardDraft(
        title="Hello World",
        canonical_title="Hello World",
        summary="A basic program",
        body="```python\nprint('hello')\n```",
        difficulty=Difficulty.BEGINNER,
    )


def _prose_draft() -> CardDraft:
    return CardDraft(
        title="Karma Yoga",
        canonical_title="Karma Yoga",
        summary="The path of selfless action",
        body="Karma Yoga teaches that one should act without attachment to results.",
        difficulty=Difficulty.BEGINNER,
    )


def test_code_draft_matches_code_for_technical_topic() -> None:
    assert _card_matches_type(_code_draft(), CardType.CODE.value, topic_name="Python Programming")


def test_code_draft_rejected_for_non_technical_topic() -> None:
    assert not _card_matches_type(
        _code_draft(), CardType.CODE.value, topic_name="Bhagvad Geeta in Easy Language"
    )


def test_code_draft_matches_code_without_topic_name_backward_compat() -> None:
    assert _card_matches_type(_code_draft(), CardType.CODE.value)


def test_prose_draft_matches_prose_regardless_of_topic() -> None:
    assert _card_matches_type(_prose_draft(), CardType.PROSE.value, topic_name="Bhagvad Geeta")
    assert _card_matches_type(_prose_draft(), CardType.PROSE.value, topic_name="Python Programming")


def test_code_type_never_matches_non_code_draft() -> None:
    assert not _card_matches_type(
        _prose_draft(), CardType.CODE.value, topic_name="Python Programming"
    )
