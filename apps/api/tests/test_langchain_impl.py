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

import asyncio
from typing import cast
from unittest.mock import ANY, AsyncMock, Mock, call, patch

import pytest
from google.genai.errors import ClientError, ServerError
from langchain_google_genai import ChatGoogleGenerativeAI

from spoin.core.config import Settings
from spoin.domain.enums import Difficulty
from spoin.generation.base import (
    CardCorrectionQuery,
    CardVerificationQuery,
    CurriculumDraft,
    SubtopicGroupDraft,
    SubtopicTierDraft,
)
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


def _real_429(message: str = "quota exceeded") -> ClientError:
    """A real 429 from the provider, in the shape `google-genai` actually
    raises it -- `ClientError(code, response_json)`, code/status pulled from
    the API's `{"error": {...}}` envelope. Mirrors what
    `GeminiContentGenerator._invoke_with_retry` matches on (`exc.code == 429`)."""

    return ClientError(
        429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": message}}
    )


def _real_504(message: str = "Deadline expired before operation could complete.") -> ServerError:
    """`gemini_request_timeout_seconds` firing on a genuinely stalled call, in
    the shape confirmed live against the real API (not a distinct exception
    class -- `google.genai.errors.ServerError` with `.code == 504`, same class
    as an ordinary 503 "high demand" overload, distinguished only by code)."""

    return ServerError(
        504, {"error": {"code": 504, "status": "DEADLINE_EXCEEDED", "message": message}}
    )


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


async def test_invoke_with_backoff_retries_503_on_the_same_cell() -> None:
    """A 503 'high demand' is retried in place with backoff -- Google's own
    docs call it usually temporary, so it's worth a couple of same-cell
    attempts before giving up."""

    generator = _generator()
    runnable = AsyncMock()
    runnable.ainvoke = AsyncMock(
        side_effect=[
            ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}}),
            "ok-result",
        ]
    )
    with patch("spoin.generation.langchain_impl.asyncio.sleep", AsyncMock()) as mock_sleep:
        result = await generator._invoke_with_backoff(
            runnable, [], key_index=0, model=_THINKING_MODEL
        )

    assert result == "ok-result"
    mock_sleep.assert_awaited_once()


async def test_invoke_with_backoff_raises_504_immediately_without_retrying() -> None:
    """Confirmed live: `gemini_request_timeout_seconds` firing surfaces as a
    504 `ServerError`, not a distinct exception class. Unlike a 503, the cell
    already burned its FULL timeout budget just getting this error -- retrying
    it again here would burn that budget a second time for nothing, so this
    must raise on the very first attempt instead of sleeping and retrying."""

    generator = _generator()
    runnable = AsyncMock()
    runnable.ainvoke = AsyncMock(side_effect=_real_504())
    with (
        patch("spoin.generation.langchain_impl.asyncio.sleep", AsyncMock()) as mock_sleep,
        pytest.raises(ServerError),
    ):
        await generator._invoke_with_backoff(runnable, [], key_index=0, model=_THINKING_MODEL)

    mock_sleep.assert_not_awaited()


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
    runnable.ainvoke = AsyncMock(side_effect=[_real_429(), draft])
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
    runnable.ainvoke = AsyncMock(side_effect=_real_429())
    with (
        patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable),
        pytest.raises(QuotaExhaustedError),
    ):
        await generator.generate_curriculum("Topic", "desc")

    assert generator._thinking.mark_exhausted.await_count == 2


async def test_invoke_with_retry_excludes_model_on_timeout_without_retrying_same_cell() -> None:
    """Confirmed live: key 0/gemini-3.7-flash hung with no response until the
    client-side timeout fired, raising a 504 `ServerError`. Unlike an
    ordinary 503, the cell already burned its full timeout budget once, so
    this must NOT retry the same cell via `_invoke_with_backoff` -- it should
    exclude the whole model and move to the next rung on the very next
    attempt, and it must not call `mark_exhausted` (a timeout isn't a quota
    condition)."""

    generator = _generator()
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(0, _THINKING_MODEL), (0, "gemini-fallback-model")]
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
    runnable.ainvoke = AsyncMock(side_effect=[_real_504(), draft])
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        result = await generator.generate_curriculum("Topic", "desc")

    assert result is draft
    generator._thinking.mark_exhausted.assert_not_awaited()
    second_call_kwargs = generator._thinking.acquire.await_args_list[1].kwargs
    assert second_call_kwargs["exclude_models"] == frozenset({_THINKING_MODEL})


async def test_invoke_with_retry_starts_a_recovery_probe_on_timeout() -> None:
    """A timeout must both exclude the model from real traffic immediately
    (`pool.exclude_model`) and kick off exactly one background probe -- not
    block the caller waiting for it."""

    generator = _generator()
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(0, _THINKING_MODEL), (0, "gemini-fallback-model")]
    )
    generator._thinking.exclude_model = Mock()  # type: ignore[method-assign]
    probe_started = asyncio.Event()

    async def _fake_probe(pool: object, model: str) -> None:
        probe_started.set()

    generator._probe_model = _fake_probe  # type: ignore[method-assign]

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
    runnable.ainvoke = AsyncMock(side_effect=[_real_504(), draft])
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        result = await generator.generate_curriculum("Topic", "desc")
        await asyncio.wait_for(probe_started.wait(), timeout=1)

    assert result is draft
    generator._thinking.exclude_model.assert_called_once_with(_THINKING_MODEL)
    assert len(generator._active_probes) == 1


async def test_probe_model_stops_at_first_key_that_responds() -> None:
    """The probe must try a DIFFERENT key each attempt (not the one that
    originally stalled), and stop as soon as any key responds -- it must NOT
    burn through the rest of the budget once the model is confirmed back, and
    must NOT touch mark_exhausted (nothing here is out of quota)."""

    generator = _generator(gemini_api_keys="key-a,key-b,key-c")
    pool = generator._thinking
    pool.record_probe_attempt = AsyncMock()  # type: ignore[method-assign]
    pool.include_model = Mock()  # type: ignore[method-assign]
    pool.mark_exhausted = AsyncMock()  # type: ignore[method-assign]

    fail_client = AsyncMock()
    fail_client.ainvoke = AsyncMock(side_effect=_real_504())
    ok_client = AsyncMock()
    ok_client.ainvoke = AsyncMock(return_value=None)
    generator._client = Mock(side_effect=[fail_client, ok_client])  # type: ignore[method-assign]

    with (
        patch("spoin.generation.langchain_impl.asyncio.sleep", AsyncMock()),
        patch("spoin.generation.langchain_impl.time.monotonic", return_value=0.0),
    ):
        await generator._probe_model(pool, _THINKING_MODEL)

    assert generator._client.call_args_list == [call(0, _THINKING_MODEL), call(1, _THINKING_MODEL)]
    assert pool.record_probe_attempt.await_count == 2
    pool.include_model.assert_called_once_with(_THINKING_MODEL)
    pool.mark_exhausted.assert_not_awaited()


async def test_probe_model_marks_every_tried_key_exhausted_once_budget_expires() -> None:
    """If nothing responds within the probe budget, every key actually tried
    gets marked exhausted (same posture as a real 429) rather than the model
    just quietly staying excluded with no ledger record of why."""

    generator = _generator(gemini_api_keys="key-a,key-b")
    pool = generator._thinking
    pool.record_probe_attempt = AsyncMock()  # type: ignore[method-assign]
    pool.include_model = Mock()  # type: ignore[method-assign]
    pool.mark_exhausted = AsyncMock()  # type: ignore[method-assign]

    fail_client = AsyncMock()
    fail_client.ainvoke = AsyncMock(side_effect=_real_504())
    generator._client = Mock(return_value=fail_client)  # type: ignore[method-assign]

    # deadline call, then 3 while-checks: two attempts inside budget (key 0,
    # then key 1), the third past it -- so exactly 2 attempts run.
    with (
        patch("spoin.generation.langchain_impl.asyncio.sleep", AsyncMock()),
        patch(
            "spoin.generation.langchain_impl.time.monotonic",
            side_effect=[0.0, 0.0, 0.0, 2000.0],
        ),
    ):
        await generator._probe_model(pool, _THINKING_MODEL)

    assert pool.record_probe_attempt.await_count == 2
    tried = {c.args for c in pool.mark_exhausted.await_args_list}
    assert tried == {(0, _THINKING_MODEL), (1, _THINKING_MODEL)}
    pool.include_model.assert_called_once_with(_THINKING_MODEL)


async def test_invoke_with_retry_reraises_non_429_client_errors_immediately() -> None:
    """The new SDK folds every 4xx into one `ClientError` class -- a non-quota
    one (bad request, auth failure, ...) must still propagate on the first
    attempt rather than being mistaken for a retryable 429 and burning the
    whole grid on an error key rotation can never fix."""

    generator = _generator()
    generator._thinking.mark_exhausted = AsyncMock()  # type: ignore[method-assign]

    runnable = AsyncMock()
    runnable.ainvoke = AsyncMock(
        side_effect=ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})
    )
    with (
        patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable),
        pytest.raises(ClientError),
    ):
        await generator.generate_curriculum("Topic", "desc")

    generator._thinking.mark_exhausted.assert_not_awaited()
    assert cast(AsyncMock, generator._thinking.acquire).await_count == 1


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
        cards=[
            _WireCard(title="Advanced take", canonical_title="Advanced Take", summary="s", body="b")
        ]
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
                index=0,
                title="Fixed",
                canonical_title="Fixed Title",
                summary="s",
                body="b",
                was_edited=True,
                note="fixed topic drift",
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
                    index=0,
                    topic_name="T",
                    topic_description="d",
                    title="Orig",
                    canonical_title="Orig Title",
                    summary="s",
                    body="off-topic body",
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
                    index=0,
                    canonical_title="A",
                    body="body one",
                    requested_difficulty=Difficulty.ADVANCED,
                ),
                CardVerificationQuery(
                    index=1,
                    canonical_title="B",
                    body="body two",
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
            [("Card A", "body a"), ("Card B", "body b")],
            Difficulty.BEGINNER,
            existing_stems=[],
            is_backfill=False,
        )

    assert len(result.items) == 2
    assert result.items[0].correct_index == 2
    assert result.items[1].rubric == "0/1/2/3"


def test_wire_question_tolerates_null_explanation() -> None:
    """Regression test for a real failure seen against live Gemini: a null
    `explanation` on one item in a batch failed Pydantic validation for the
    ENTIRE `_WireQuestionBatch`, silently discarding every other question in
    that call. `_LenientWireModel` coerces the null to the field's default
    before validation instead of letting it propagate."""

    wire_question = _WireQuestion.model_validate(
        {
            "card_index": 0,
            "stem": "What is X?",
            "options": ["a", "b", "c", "d"],
            "correct_index": 0,
            "explanation": None,
        }
    )
    assert wire_question.explanation == ""


async def test_generate_questions_survives_null_explanation_in_batch() -> None:
    generator = _generator()
    wire = _WireQuestionBatch.model_validate(
        {
            "questions": [
                {
                    "card_index": 0,
                    "stem": "Which is correct?",
                    "options": ["a", "b", "c", "d"],
                    "correct_index": 2,
                    "explanation": None,
                },
                {
                    "card_index": 1,
                    "stem": "Explain it",
                    "rubric": "0/1/2/3",
                    "reference_answer": "a correct account",
                },
            ]
        }
    )
    with patch.object(
        ChatGoogleGenerativeAI, "with_structured_output", return_value=_mock_structured(wire)
    ):
        result = await generator.generate_questions(
            [("Card A", "body a"), ("Card B", "body b")],
            Difficulty.BEGINNER,
            existing_stems=[],
            is_backfill=False,
        )

    assert len(result.items) == 2
    assert result.items[0].explanation == ""


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
            [("Card A", "body a"), ("Card B", "body b")],
            Difficulty.BEGINNER,
            existing_stems=[],
            is_backfill=False,
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
            _WireTopicMatchResult(
                request_index=0, matched_topic_id="11111111-1111-1111-1111-111111111111"
            ),
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
            TopicMatchQuery(
                request_index=1, name="Sourdough Baking", description="", candidates=[]
            ),
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


@pytest.mark.parametrize(
    ("card_type", "expected_phrase"),
    [
        ("ascii", "STICKMAN ASCII COMIC SCENE"),
        ("comparison", "MYTH VS FACT / COMPARISON"),
        ("code", "CODE / SYNTAX / CONFIGURATION"),
        ("diagram", "DOMAIN-SPECIALIZED DIAGRAM"),
        ("prose", "CONCEPTUAL PROSE & MENTAL MODELS"),
    ],
)
async def test_generate_cards_prompt_selection_by_card_type(
    card_type: str, expected_phrase: str
) -> None:
    generator = _generator()
    wire = _WireCardBatch(
        cards=[
            _WireCard(
                title="T",
                canonical_title="CT",
                summary="S",
                body="B",
                ascii_label="stickman" if card_type == "ascii" else "",
                ascii_art="  o\n /|\\\n / \\" if card_type == "ascii" else "",
                ascii_alt="Stickman" if card_type == "ascii" else "",
            )
        ]
    )
    captured_prompt: list[object] = []

    async def _capture(prompt: object) -> _WireCardBatch:
        captured_prompt.append(prompt)
        return wire

    runnable = AsyncMock()
    runnable.ainvoke = _capture
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        result = await generator.generate_cards(
            topic_name="Databases",
            subtopic_title="Indexing",
            subtopic_description="B-trees vs Hash indexes",
            difficulty=Difficulty.INTERMEDIATE,
            count=1,
            existing_titles=[],
            builds_on=[],
            difficulty_examples={},
            avoid_bodies=[],
            rejection_feedback=[],
            card_type=card_type,
        )

    assert len(result.items) == 1
    system_prompt = str(captured_prompt[0])
    assert expected_phrase in system_prompt


async def test_quota_exhausted_error_is_reraised_across_methods() -> None:
    """When QuotaExhaustedError is raised, it must NOT be swallowed into BatchResult.failures;
    it must propagate so worker can pause and requeue cleanly."""
    generator = _generator()
    generator._generator.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=QuotaExhaustedError("All exhausted")
    )
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=QuotaExhaustedError("All exhausted")
    )

    with pytest.raises(QuotaExhaustedError):
        await generator.generate_cards(
            topic_name="T",
            subtopic_title="S",
            subtopic_description="D",
            difficulty=Difficulty.BEGINNER,
            count=1,
            existing_titles=[],
            builds_on=[],
            difficulty_examples={},
            avoid_bodies=[],
            rejection_feedback=[],
        )

    with pytest.raises(QuotaExhaustedError):
        await generator.correct_cards(
            [
                CardCorrectionQuery(
                    index=0,
                    topic_name="T",
                    topic_description="D",
                    title="title",
                    canonical_title="ctitle",
                    summary="summary",
                    body="body",
                )
            ],
            difficulty_examples={},
        )

    with pytest.raises(QuotaExhaustedError):
        await generator.verify_cards(
            [
                CardVerificationQuery(
                    index=0,
                    canonical_title="ctitle",
                    body="body",
                    requested_difficulty=Difficulty.BEGINNER,
                )
            ],
            difficulty_examples={},
        )

    with pytest.raises(QuotaExhaustedError):
        await generator.generate_questions(
            [("title", "body")],
            difficulty=Difficulty.BEGINNER,
            existing_stems=[],
            is_backfill=False,
        )
