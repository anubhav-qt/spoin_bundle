"""Mocked unit tests for langchain_impl.py — no real Gemini key, no network.

Patches `ChatGoogleGenerativeAI.with_structured_output` so every call returns a
scripted response, and patches both quota pools' `acquire` so nothing here
opens a real database connection (key/model-rotation correctness itself is
already fully covered by test_quota_governor.py — these tests are about the
LangChain/pydantic plumbing one layer up). See langchain_impl.py's module
docstring for why prompt QUALITY (does the model write good cards) is
explicitly NOT covered here — there is no real key to verify that against.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_google_genai import ChatGoogleGenerativeAI

from spoin.core.config import Settings
from spoin.domain.enums import Difficulty
from spoin.generation.langchain_impl import (
    GeminiContentGenerator,
    _WireCard,
    _WireCardBatch,
    _WireDifficultyBatch,
    _WireDifficultyVerdict,
    _WireQuestion,
    _WireQuestionBatch,
)

_THINKING_MODEL = "gemini-thinking-test"
_CARDS_MODEL = "gemini-cards-test"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "gemini_api_keys": "key-a,key-b",
        "gemini_thinking_ladder": f"{_THINKING_MODEL}:20:5",
        "gemini_cards_ladder": f"{_CARDS_MODEL}:500:15",
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
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        return_value=(0, _THINKING_MODEL)
    )
    generator._cards.acquire = AsyncMock(  # type: ignore[method-assign]
        return_value=(0, _CARDS_MODEL)
    )
    return generator


def test_construction_requires_at_least_one_key() -> None:
    with pytest.raises(ValueError, match="SPOIN_GEMINI_API_KEYS"):
        GeminiContentGenerator(_settings(gemini_api_keys=""))


def test_client_is_cached_per_key_and_model() -> None:
    generator = _generator()
    first = generator._client(0, "model-a")
    second = generator._client(0, "model-a")
    third_key = generator._client(1, "model-a")
    third_model = generator._client(0, "model-b")
    assert first is second
    assert first is not third_key
    assert first is not third_model


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
            builds_on=[],
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
            builds_on=[],
        )

    assert result.items == []
    assert len(result.failures) == 1
    assert "network blip" in result.failures[0]


async def test_generate_cards_threads_builds_on_into_prompt() -> None:
    generator = _generator()
    wire = _WireCardBatch(
        cards=[_WireCard(title="Advanced take", canonical_title="Advanced Take", summary="s", body="b")]
    )
    captured_prompt: list[object] = []

    async def _capture(prompt: object) -> _WireCardBatch:
        captured_prompt.append(prompt)
        return wire

    runnable = AsyncMock()
    runnable.ainvoke = _capture
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        await generator.generate_cards(
            topic_name="T",
            subtopic_title="S",
            subtopic_description="d",
            difficulty=Difficulty.ADVANCED,
            count=1,
            existing_titles=[],
            builds_on=["Lower-tier card body about the basics."],
        )

    prompt_text = str(captured_prompt[0])
    assert "Lower-tier card body about the basics." in prompt_text


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


async def test_generate_curriculum_threads_existing_subtopics_into_prompt() -> None:
    from spoin.generation.base import CurriculumDraft, SubtopicGroupDraft, SubtopicTierDraft

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


async def test_match_topics_batches_every_query_in_one_call() -> None:
    from spoin.generation.langchain_impl import _WireTopicMatchBatch, _WireTopicMatchResult

    generator = _generator()
    wire = _WireTopicMatchBatch(
        results=[
            _WireTopicMatchResult(request_index=0, matched_topic_id="11111111-1111-1111-1111-111111111111"),
            _WireTopicMatchResult(request_index=1, matched_topic_id=None),
        ]
    )
    captured_prompt: list[object] = []

    async def _capture(prompt: object) -> _WireTopicMatchBatch:
        captured_prompt.append(prompt)
        return wire

    runnable = AsyncMock()
    runnable.ainvoke = _capture
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        from spoin.generation.base import TopicMatchCandidate, TopicMatchQuery

        queries = [
            TopicMatchQuery(
                request_index=0,
                name="k8s",
                description="",
                candidates=[
                    TopicMatchCandidate(
                        topic_id="11111111-1111-1111-1111-111111111111",
                        name="Kubernetes",
                        similarity=0.95,
                    )
                ],
            ),
            TopicMatchQuery(request_index=1, name="Sourdough Baking", description="", candidates=[]),
        ]
        result = await generator.match_topics(queries)

    assert len(result.items) == 2
    assert result.items[0].matched_topic_id == "11111111-1111-1111-1111-111111111111"
    assert result.items[1].matched_topic_id is None
    prompt_text = str(captured_prompt[0])
    assert "k8s" in prompt_text
    assert "Sourdough Baking" in prompt_text
    # One call for the whole batch, not one per query (ADR-0025).
    assert len(captured_prompt) == 1
