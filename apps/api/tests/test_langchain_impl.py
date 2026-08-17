"""Mocked unit tests for langchain_impl.py — no real Gemini key, no network.

Patches `ChatGoogleGenerativeAI.with_structured_output` so every call returns a
scripted response, and patches `QuotaGovernor.acquire_key` so nothing here opens
a real database connection (key-rotation correctness itself is already fully
covered by test_quota_governor.py — these tests are about the LangChain/pydantic
plumbing one layer up). See langchain_impl.py's module docstring for why prompt
QUALITY (does the model write good cards) is explicitly NOT covered here — there
is no real key to verify that against.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_google_genai import ChatGoogleGenerativeAI

from slocho.core.config import Settings
from slocho.domain.enums import Difficulty
from slocho.generation.langchain_impl import (
    GeminiContentGenerator,
    _WireCard,
    _WireCardBatch,
    _WireDifficultyBatch,
    _WireDifficultyVerdict,
    _WireQuestion,
    _WireQuestionBatch,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "gemini_api_keys": "key-a,key-b",
        "quota_daily_requests": 1500,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _mock_structured(return_value: object, side_effect: object = None) -> AsyncMock:
    """Stands in for the Runnable `.with_structured_output(...)` returns."""

    runnable = AsyncMock()
    if side_effect is not None:
        runnable.ainvoke = AsyncMock(side_effect=side_effect)
    else:
        runnable.ainvoke = AsyncMock(return_value=return_value)
    return runnable


def _generator(**settings_overrides: object) -> GeminiContentGenerator:
    generator = GeminiContentGenerator(_settings(**settings_overrides))
    generator._quota.acquire_key = AsyncMock(return_value=0)  # type: ignore[method-assign]
    return generator


def test_construction_requires_at_least_one_key() -> None:
    with pytest.raises(ValueError, match="SLOCHO_GEMINI_API_KEYS"):
        GeminiContentGenerator(_settings(gemini_api_keys=""))


def test_client_is_cached_per_key_index() -> None:
    generator = _generator()
    first = generator._client(0)
    second = generator._client(0)
    third = generator._client(1)
    assert first is second
    assert first is not third


async def test_generate_cards_partial_failure_does_not_sink_batch() -> None:
    generator = _generator()
    wire = _WireCardBatch(
        cards=[
            _WireCard(title="Good", canonical_title="Good Card", summary="s", body="b"),
            _WireCard(
                title="", canonical_title="", summary="", body=""
            ),  # empty -> min_length fails
        ]
    )
    with patch.object(
        ChatGoogleGenerativeAI, "with_structured_output", return_value=_mock_structured(wire)
    ):
        result = await generator.generate_cards(
            topic_name="T",
            subtopic_title="S",
            subtopic_description="d",
            difficulty=Difficulty.INTERMEDIATE,
            count=2,
            existing_titles=[],
        )

    assert len(result.items) == 1
    assert result.items[0].title == "Good"
    # difficulty is NEVER read from the model's own output — it's what was asked.
    assert result.items[0].difficulty == Difficulty.INTERMEDIATE
    assert len(result.failures) == 1


async def test_generate_cards_whole_call_failure_degrades_to_empty_batch() -> None:
    generator = _generator()
    with patch.object(
        ChatGoogleGenerativeAI,
        "with_structured_output",
        return_value=_mock_structured(None, side_effect=RuntimeError("network blip")),
    ):
        result = await generator.generate_cards(
            topic_name="T",
            subtopic_title="S",
            subtopic_description="d",
            difficulty=Difficulty.BEGINNER,
            count=5,
            existing_titles=[],
        )

    assert result.items == []
    assert len(result.failures) == 1
    assert "network blip" in result.failures[0]


async def test_judge_difficulty_parses_verdicts_and_rejects_bad_enum() -> None:
    generator = _generator()
    wire = _WireDifficultyBatch(
        verdicts=[
            _WireDifficultyVerdict(index=0, difficulty="advanced", factually_sound=True, note=""),
            _WireDifficultyVerdict(index=1, difficulty="not-a-real-tier", factually_sound=False),
        ]
    )
    with patch.object(
        ChatGoogleGenerativeAI, "with_structured_output", return_value=_mock_structured(wire)
    ):
        result = await generator.judge_difficulty(["body one", "body two"])

    assert len(result.items) == 1
    assert result.items[0].difficulty == Difficulty.ADVANCED
    assert len(result.failures) == 1


async def test_generate_questions_maps_mcq_and_free_text() -> None:
    generator = _generator()
    wire = _WireQuestionBatch(
        questions=[
            _WireQuestion(
                card_index=0,
                stem="Which is correct?",
                options=["a", "b", "c", "d"],
                correct_index=2,
                explanation="because",
            ),
            _WireQuestion(
                card_index=1,
                stem="Explain it",
                rubric="0/1/2/3",
                reference_answer="a correct account",
            ),
        ]
    )
    with patch.object(
        ChatGoogleGenerativeAI, "with_structured_output", return_value=_mock_structured(wire)
    ):
        result = await generator.generate_questions(
            [("Card A", "body a"), ("Card B", "body b")], Difficulty.BEGINNER
        )

    assert len(result.items) == 2
    assert result.items[0].correct_index == 2
    assert result.items[1].rubric == "0/1/2/3"


async def test_generate_curriculum_threads_related_hints_into_prompt() -> None:
    from slocho.generation.base import CurriculumDraft, SubtopicGroupDraft, SubtopicTierDraft

    generator = _generator()
    draft = CurriculumDraft(
        subtopics=[
            SubtopicGroupDraft(
                title="G",
                tiers=[
                    SubtopicTierDraft(
                        difficulty=Difficulty.BEGINNER, description="d", target_cards=10
                    )
                ],
            )
        ]
    )
    captured_prompt: list[object] = []

    async def _capture(prompt: object) -> CurriculumDraft:
        captured_prompt.append(prompt)
        return draft

    runnable = AsyncMock()
    runnable.ainvoke = _capture
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        result = await generator.generate_curriculum("Topic", "desc", ["Related Hint One"])

    assert result is draft
    prompt_text = str(captured_prompt[0])
    assert "Related Hint One" in prompt_text


async def test_generate_curriculum_threads_existing_subtopics_into_prompt() -> None:
    from slocho.generation.base import CurriculumDraft, SubtopicGroupDraft, SubtopicTierDraft

    generator = _generator()
    draft = CurriculumDraft(
        subtopics=[
            SubtopicGroupDraft(
                title="G",
                tiers=[
                    SubtopicTierDraft(
                        difficulty=Difficulty.BEGINNER, description="d", target_cards=10
                    )
                ],
            )
        ]
    )
    captured_prompt: list[object] = []

    async def _capture(prompt: object) -> CurriculumDraft:
        captured_prompt.append(prompt)
        return draft

    runnable = AsyncMock()
    runnable.ainvoke = _capture
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        await generator.generate_curriculum(
            "Topic", "desc", existing_subtopics=["Existing Subtopic One :: some description"]
        )

    prompt_text = str(captured_prompt[0])
    assert "Existing Subtopic One" in prompt_text


async def test_judge_topic_match_returns_verdict_directly() -> None:
    from slocho.generation.base import TopicMatchVerdict

    generator = _generator()
    verdict = TopicMatchVerdict(same_topic=True, relevant_subtopic_titles=["X"])
    with patch.object(
        ChatGoogleGenerativeAI, "with_structured_output", return_value=_mock_structured(verdict)
    ):
        result = await generator.judge_topic_match("A", "a", "A'", ["X", "Y"])

    assert result is verdict
