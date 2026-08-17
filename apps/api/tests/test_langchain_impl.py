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

from unittest.mock import ANY, AsyncMock, patch

import pytest
from google.api_core.exceptions import ResourceExhausted
from langchain_google_genai import ChatGoogleGenerativeAI

from spoin.core.config import Settings
from spoin.domain.enums import Difficulty
from spoin.generation.base import CurriculumDraft, SubtopicGroupDraft, SubtopicTierDraft
from spoin.generation.langchain_impl import (
    GeminiContentGenerator,
    _WireCard,
    _WireCardBatch,
    _WireCorrection,
    _WireCorrectionBatch,
    _WireQuestion,
    _WireQuestionBatch,
    _WireVerification,
    _WireVerificationBatch,
)
from spoin.generation.quota import QuotaExhaustedError

_THINKING_MODEL = "gemini-thinking-test"
_GENERATOR_MODEL = "gemini-generator-test"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "gemini_api_keys": "key-a,key-b",
        "gemini_thinking_ladder": f"{_THINKING_MODEL}:20:5",
        "gemini_generator_ladder": f"{_GENERATOR_MODEL}:500:15",
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
    generator._generator.acquire = AsyncMock(  # type: ignore[method-assign]
        return_value=(0, _GENERATOR_MODEL)
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


async def test_invoke_with_retry_falls_through_to_next_cell_on_real_429() -> None:
    """ADR-0028's drift risk, confirmed live: a real 429 from the provider
    means our local ledger disagreed with reality. The retry path must mark
    that exact cell exhausted and try the next one, not just fail outright."""

    generator = _generator()
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(0, _THINKING_MODEL), (1, _THINKING_MODEL)]
    )
    generator._thinking.mark_exhausted = AsyncMock()  # type: ignore[method-assign]

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
    runnable = AsyncMock()
    runnable.ainvoke = AsyncMock(side_effect=[ResourceExhausted("quota exceeded"), draft])
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        result = await generator.generate_curriculum("Topic", "desc")

    assert result is draft
    generator._thinking.mark_exhausted.assert_awaited_once_with(0, _THINKING_MODEL, now=ANY)
    assert generator._thinking.acquire.await_count == 2


async def test_invoke_with_retry_raises_once_the_whole_grid_429s() -> None:
    generator = _generator()
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            (0, _THINKING_MODEL),
            (1, _THINKING_MODEL),
            QuotaExhaustedError("all exhausted"),
        ]
    )
    generator._thinking.mark_exhausted = AsyncMock()  # type: ignore[method-assign]

    runnable = AsyncMock()
    runnable.ainvoke = AsyncMock(side_effect=ResourceExhausted("quota exceeded"))
    with (
        patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable),
        pytest.raises(QuotaExhaustedError),
    ):
        await generator.generate_curriculum("Topic", "desc")

    assert generator._thinking.mark_exhausted.await_count == 2


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
            difficulty_examples={},
            avoid_bodies=[],
            rejection_feedback=[],
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
            difficulty_examples={},
            avoid_bodies=[],
            rejection_feedback=[],
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
            difficulty_examples={},
            avoid_bodies=[],
            rejection_feedback=[],
        )

    prompt_text = str(captured_prompt[0])
    assert "Lower-tier card body about the basics." in prompt_text


async def test_generate_cards_threads_difficulty_examples_into_prompt() -> None:
    generator = _generator()
    wire = _WireCardBatch(cards=[_WireCard(title="T", canonical_title="T", summary="s", body="b")])
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
            difficulty=Difficulty.BEGINNER,
            count=1,
            existing_titles=[],
            builds_on=[],
            difficulty_examples={Difficulty.ADVANCED: ["An example advanced-tier card body."]},
            avoid_bodies=[],
            rejection_feedback=[],
        )

    prompt_text = str(captured_prompt[0])
    assert "An example advanced-tier card body." in prompt_text


async def test_generate_cards_threads_avoid_bodies_into_prompt() -> None:
    generator = _generator()
    wire = _WireCardBatch(cards=[_WireCard(title="T", canonical_title="T", summary="s", body="b")])
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
            difficulty=Difficulty.BEGINNER,
            count=1,
            existing_titles=[],
            builds_on=[],
            difficulty_examples={},
            avoid_bodies=["A body that was rejected as a near-duplicate last run."],
            rejection_feedback=[],
        )

    prompt_text = str(captured_prompt[0])
    assert "A body that was rejected as a near-duplicate last run." in prompt_text


async def test_generate_cards_threads_rejection_feedback_into_prompt() -> None:
    generator = _generator()
    wire = _WireCardBatch(cards=[_WireCard(title="T", canonical_title="T", summary="s", body="b")])
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
            difficulty=Difficulty.BEGINNER,
            count=1,
            existing_titles=[],
            builds_on=[],
            difficulty_examples={},
            avoid_bodies=[],
            rejection_feedback=[
                ("A body the reviewer rejected.", "reads as intermediate, not beginner")
            ],
        )

    prompt_text = str(captured_prompt[0])
    assert "A body the reviewer rejected." in prompt_text
    assert "reads as intermediate, not beginner" in prompt_text


async def test_correct_cards_passes_through_edits_and_rejects_bad_item() -> None:
    generator = _generator()
    wire = _WireCorrectionBatch(
        corrections=[
            _WireCorrection(
                index=0, title="Fixed", canonical_title="Fixed Title", summary="s", body="b",
                was_edited=True, note="fixed topic drift",
            ),
        ]
    )
    with patch.object(
        ChatGoogleGenerativeAI, "with_structured_output", return_value=_mock_structured(wire)
    ):
        from spoin.generation.base import CardCorrectionQuery

        result = await generator.correct_cards(
            [
                CardCorrectionQuery(
                    index=0, topic_name="T", topic_description="d", title="Orig",
                    canonical_title="Orig Title", summary="s", body="off-topic body",
                )
            ],
            difficulty_examples={},
        )

    assert len(result.items) == 1
    assert result.items[0].was_edited is True
    assert result.items[0].body == "b"


async def test_verify_cards_parses_verdicts_and_rejects_bad_enum() -> None:
    generator = _generator()
    wire = _WireVerificationBatch(
        verdicts=[
            _WireVerification(index=0, accepted=True, confirmed_difficulty="advanced", reason=""),
            _WireVerification(
                index=1, accepted=False, confirmed_difficulty="not-a-real-tier", reason="mismatch"
            ),
        ]
    )
    with patch.object(
        ChatGoogleGenerativeAI, "with_structured_output", return_value=_mock_structured(wire)
    ):
        from spoin.generation.base import CardVerificationQuery

        result = await generator.verify_cards(
            [
                CardVerificationQuery(
                    index=0, canonical_title="A", body="body one",
                    requested_difficulty=Difficulty.ADVANCED,
                ),
                CardVerificationQuery(
                    index=1, canonical_title="B", body="body two",
                    requested_difficulty=Difficulty.BEGINNER,
                ),
            ],
            difficulty_examples={},
        )

    assert len(result.items) == 1
    assert result.items[0].accepted is True
    assert result.items[0].confirmed_difficulty == Difficulty.ADVANCED
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


async def test_generate_questions_drops_duplicate_card_index() -> None:
    generator = _generator()
    wire = _WireQuestionBatch(
        questions=[
            _WireQuestion(
                card_index=0,
                stem="First question, correctly attached.",
                options=["a", "b", "c", "d"],
                correct_index=0,
            ),
            _WireQuestion(
                card_index=0,
                stem="Second question, mislabeled with the same card_index.",
                options=["a", "b", "c", "d"],
                correct_index=1,
            ),
        ]
    )
    with patch.object(
        ChatGoogleGenerativeAI, "with_structured_output", return_value=_mock_structured(wire)
    ):
        result = await generator.generate_questions(
            [("Card A", "body a"), ("Card B", "body b")], Difficulty.BEGINNER
        )

    assert len(result.items) == 1
    assert result.items[0].stem == "First question, correctly attached."
    assert len(result.failures) == 1
    assert "duplicate card_index" in result.failures[0]


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
