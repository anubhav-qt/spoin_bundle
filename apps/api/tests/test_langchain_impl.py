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
    CardPlan,
    CardVerificationQuery,
    CurriculumDraft,
    FetchedAsciiScene,
    SubtopicGroupDraft,
    SubtopicTierDraft,
)
from spoin.generation.langchain_impl import (
    _ASCII_MAX_WIDTH,
    _PROBE_BUDGET_SECONDS,
    GeminiContentGenerator,
    _classify_rate_limit,
    _WireAsciiRedrawBatch,
    _WireAsciiScene,
    _WireCard,
    _WireCardBatch,
    _WireCorrection,
    _WireCorrectionBatch,
    _WireQuestion,
    _WireQuestionBatch,
    _WireVerification,
    _WireVerificationBatch,
)
from spoin.generation.quota import (
    AllCellsThrottledError,
    DailyQuotaExhaustedError,
    QuotaExhaustedError,
)

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


def _rpm_429(retry_delay: str = "13s") -> ClientError:
    """A PER-MINUTE 429, in the exact shape the real API returns it (captured
    live from a run that mistook a burst of these for a day-long exhaustion --
    see ADR-0058). The `quotaId` is the discriminator that matters."""

    return ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota exceeded for metric: generate_content_free_tier_requests",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": ("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"),
                                "quotaMetric": (
                                    "generativelanguage.googleapis.com/"
                                    "generate_content_free_tier_requests"
                                ),
                            }
                        ],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": retry_delay,
                    },
                ],
            }
        },
    )


def _rpd_429() -> ClientError:
    """A genuine per-DAY exhaustion -- same status code, opposite meaning."""

    return ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota exceeded",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                        ],
                    }
                ],
            }
        },
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
    # Stubbed for the same reason `acquire` is: since ADR-0058 the per-minute
    # window lives in the database, and these tests are about the LangChain
    # plumbing, not quota bookkeeping (which test_quota_governor.py owns
    # against a real session).
    generator._thinking.note_request_sent = AsyncMock()  # type: ignore[method-assign]
    generator._generator.note_request_sent = AsyncMock()  # type: ignore[method-assign]
    # Same again for model availability, which ADR-0065 moved into the database
    # for the same cross-process reason. Unstubbed these open a session against
    # the APP's database (they don't go through the `session` fixture), which is
    # both outside what this file tests and a write this suite must never make.
    generator._thinking.exclude_model = AsyncMock()  # type: ignore[method-assign]
    generator._generator.exclude_model = AsyncMock()  # type: ignore[method-assign]
    generator._thinking.include_model = AsyncMock()  # type: ignore[method-assign]
    generator._generator.include_model = AsyncMock()  # type: ignore[method-assign]
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
    pool = generator._thinking
    pool.note_request_sent = AsyncMock()  # type: ignore[method-assign]
    with patch("spoin.generation.langchain_impl.asyncio.sleep", AsyncMock()) as mock_sleep:
        result = await generator._invoke_with_backoff(
            runnable, [], pool=pool, key_index=0, model=_THINKING_MODEL
        )

    assert result == "ok-result"
    mock_sleep.assert_awaited_once()
    # Two real requests left the process, so both are stamped into the
    # per-minute window -- the retry is not covered by the original
    # reservation (ADR-0058).
    assert pool.note_request_sent.await_count == 2


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
        pool = generator._thinking
        pool.note_request_sent = AsyncMock()  # type: ignore[method-assign]
        await generator._invoke_with_backoff(
            runnable, [], pool=pool, key_index=0, model=_THINKING_MODEL
        )

    mock_sleep.assert_not_awaited()


async def test_invoke_with_retry_falls_through_to_next_cell_on_real_429() -> None:
    """ADR-0028's drift risk, confirmed live: a real per-DAY 429 from the
    provider means our local ledger disagreed with reality. The retry path must
    mark that exact cell exhausted and try the next one, not just fail outright.

    Deliberately a `_rpd_429`, not a bare `_real_429`: since ADR-0060 only a
    positively-identified daily 429 spends a cell, so a scope-less envelope
    would exercise the cooldown path instead of this one."""

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
    runnable.ainvoke = AsyncMock(side_effect=[_rpd_429(), draft])
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
    runnable.ainvoke = AsyncMock(side_effect=_rpd_429())
    with (
        patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable),
        pytest.raises(QuotaExhaustedError),
    ):
        await generator.generate_curriculum("Topic", "desc")

    assert generator._thinking.mark_exhausted.await_count == 2


def test_classify_rate_limit_reads_the_quota_id() -> None:
    """The one distinction the whole ADR-0058 fix rests on."""

    per_minute = _classify_rate_limit(_rpm_429())
    assert per_minute.is_daily is False
    assert per_minute.retry_after_s == 13.0

    assert _classify_rate_limit(_rpd_429()).is_daily is True


def test_classify_rate_limit_falls_back_to_per_minute_when_scope_is_unknown() -> None:
    """A 429 carrying no `quotaId` and no `RetryInfo` tells us nothing, so it
    takes the RECOVERABLE branch (ADR-0060, reversing ADR-0058).

    Guessing daily here is what cost a whole day of generation on 2026-08-26:
    the pipeline's fan-out throttles every cell at once, so one wrong guess is
    not one cell, it is the entire grid slammed to its cap. Guessing per-minute
    instead is self-correcting -- the cell keeps walking toward its own RPD
    ceiling on every acquire() and retires itself."""

    assert _classify_rate_limit(_real_429()).is_daily is False


def test_classify_rate_limit_trusts_a_short_retry_delay_over_an_unknown_quota_id() -> None:
    """The exact hole that slammed the grid: `RetryInfo` used to be consulted
    only when NO `quotaId` was present, so an unrecognized id riding along with
    a 13-second delay fell through to daily. Nothing daily resolves in 13s --
    the delay is evidence in its own right, whatever id accompanies it."""

    unknown_id = ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": "SomeUnrecognizedQuotaId-FreeTier"}],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "13s"},
                ],
            }
        },
    )

    limit = _classify_rate_limit(unknown_id)
    assert limit.is_daily is False
    assert limit.retry_after_s == 13.0


def test_classify_rate_limit_reads_a_long_retry_delay_as_daily() -> None:
    """The other half of trusting `RetryInfo`: a delay well past one RPM window
    cannot be describing a per-minute limit, so it is positive evidence FOR
    daily rather than something to discard."""

    assert _classify_rate_limit(_rpm_429(retry_delay="3600s")).is_daily is False, (
        "an explicit PerMinute quotaId still wins over the delay heuristic"
    )

    long_delay = ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3600s"}
                ],
            }
        },
    )
    assert _classify_rate_limit(long_delay).is_daily is True


def test_classify_rate_limit_trusts_a_short_retry_delay_when_no_quota_id_is_sent() -> None:
    """No per-DAY exhaustion resolves itself inside a minute, so a lone
    `RetryInfo` under one RPM window is evidence enough on its own."""

    no_quota_id = ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "8s"}
                ],
            }
        },
    )

    limit = _classify_rate_limit(no_quota_id)
    assert limit.is_daily is False
    assert limit.retry_after_s == 8.0


async def test_per_minute_429_cools_the_cell_without_spending_it() -> None:
    """The live failure this fixes: a burst of per-minute 429s used to mark
    cells exhausted one after another until the whole grid read as spent for
    the day, on keys with their full daily quota still available."""

    generator = _generator()
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(0, _THINKING_MODEL), (1, _THINKING_MODEL)]
    )
    generator._thinking.mark_exhausted = AsyncMock()  # type: ignore[method-assign]
    generator._thinking.mark_rate_limited = AsyncMock()  # type: ignore[method-assign]

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
    runnable.ainvoke = AsyncMock(side_effect=[_rpm_429(), draft])
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        result = await generator.generate_curriculum("Topic", "desc")

    assert result is draft
    generator._thinking.mark_exhausted.assert_not_awaited()
    generator._thinking.mark_rate_limited.assert_awaited_once_with(
        0, _THINKING_MODEL, now=ANY, retry_after_s=13.0
    )


async def test_per_minute_429s_do_not_burn_the_grids_attempt_budget() -> None:
    """`max_attempts` counts cells BURNED, not calls made. A 2x2 grid gets 4
    cell-attempts; throttling must not consume them, or a brief rate limit
    surfaces as a hard failure while every key still has daily quota.

    The throttles here all land on cells still ABOVE their rpm floor, which is
    the ordinary case: AIMD's answer to them is to slow down and carry on, and
    this test is the guard that it does carry on. See
    `test_sustained_throttling_at_the_rpm_floor_stops_the_retry_loop` for the
    other half -- what happens once slowing down has run out of room."""

    generator = _generator()
    # More throttled calls than the 2 keys x 1 model grid has cells, but each
    # cell still has pace left to give up (rpm 5 -> 2 -> 1), so none of these
    # counts as evidence the provider is refusing us outright.
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(i % 2, _THINKING_MODEL) for i in range(12)]
    )
    generator._thinking.mark_exhausted = AsyncMock()  # type: ignore[method-assign]
    generator._thinking.mark_rate_limited = AsyncMock()  # type: ignore[method-assign]
    # Stubbing mark_rate_limited above means the real AIMD shrink never runs,
    # so every cell stays at its configured rpm -- exactly the "still has pace
    # to give up" condition this test is about.

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
    runnable.ainvoke = AsyncMock(side_effect=[*([_rpm_429()] * 9), draft])
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable):
        result = await generator.generate_curriculum("Topic", "desc")

    assert result is draft
    assert generator._thinking.mark_rate_limited.await_count == 9
    generator._thinking.mark_exhausted.assert_not_awaited()


async def test_sustained_throttling_at_the_rpm_floor_stops_the_retry_loop() -> None:
    """ADR-0065's replacement terminator. Refunding throttled grants removed the
    quota erosion that used to end this loop, so it now ends on evidence: every
    cell in the grid 429ing while already paced down to one request per minute.

    The error must be `AllCellsThrottledError`, NOT `DailyQuotaExhaustedError` --
    daily budget is intact, and a caller that stands down until midnight over
    this is discarding quota it still has."""

    generator = _generator()
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(i % 2, _THINKING_MODEL) for i in range(40)]
    )
    generator._thinking.mark_exhausted = AsyncMock()  # type: ignore[method-assign]
    # Both cells start already floored, so every throttle below is provider
    # evidence rather than a pacing correction.
    for key_index in (0, 1):
        generator._thinking._effective_rpm[(key_index, _THINKING_MODEL)] = 1.0

    runnable = AsyncMock()
    runnable.ainvoke = AsyncMock(side_effect=_rpm_429())
    with (
        patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable),
        patch.object(generator._thinking, "mark_rate_limited", AsyncMock()),
        pytest.raises(AllCellsThrottledError) as excinfo,
    ):
        await generator.generate_curriculum("Topic", "desc")

    assert not isinstance(excinfo.value, DailyQuotaExhaustedError)
    assert "not exhaustion" in str(excinfo.value)
    # Throttling still never spends a cell for the day, floored or not.
    generator._thinking.mark_exhausted.assert_not_awaited()


async def test_a_success_resets_the_floored_throttle_streak() -> None:
    """The streak is about a run of failures with nothing getting through. One
    call succeeding means the grid is serving us, however slowly -- so a later
    throttle starts counting from scratch rather than inheriting a tally from
    before the thing that disproved it."""

    generator = _generator()
    generator._thinking.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(i % 2, _THINKING_MODEL) for i in range(40)]
    )
    for key_index in (0, 1):
        generator._thinking._effective_rpm[(key_index, _THINKING_MODEL)] = 1.0

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
    # One short of the 2-cell grid's bound, then a success, then one more --
    # which would trip the bound only if the streak had survived the success.
    runnable.ainvoke = AsyncMock(side_effect=[_rpm_429(), draft, _rpm_429(), draft])
    with (
        patch.object(ChatGoogleGenerativeAI, "with_structured_output", return_value=runnable),
        patch.object(generator._thinking, "mark_rate_limited", AsyncMock()),
    ):
        assert await generator.generate_curriculum("Topic", "desc") is draft
        assert await generator.generate_curriculum("Topic", "desc") is draft


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
    generator._thinking.exclude_model.assert_awaited_once()
    excluded = generator._thinking.exclude_model.await_args
    assert excluded.args[0] == _THINKING_MODEL
    # The exclusion is given exactly the probe's own budget to be cleared in
    # (ADR-0065) -- not an independently chosen lifetime.
    assert excluded.kwargs["expires_in_s"] == _PROBE_BUDGET_SECONDS
    assert "504" in excluded.kwargs["reason"]
    assert len(generator._active_probes) == 1


async def test_probe_model_stops_at_first_key_that_responds() -> None:
    """The probe must try a DIFFERENT key each attempt (not the one that
    originally stalled), and stop as soon as any key responds -- it must NOT
    burn through the rest of the budget once the model is confirmed back, and
    must NOT touch mark_exhausted (nothing here is out of quota)."""

    generator = _generator(gemini_api_keys="key-a,key-b,key-c")
    pool = generator._thinking
    pool.record_probe_attempt = AsyncMock()  # type: ignore[method-assign]
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
    pool.include_model.assert_awaited_once_with(_THINKING_MODEL)
    pool.mark_exhausted.assert_not_awaited()


async def test_probe_model_marks_every_tried_key_exhausted_once_budget_expires() -> None:
    """If nothing responds within the probe budget, every key actually tried
    gets marked exhausted (same posture as a real 429) rather than the model
    just quietly staying excluded with no ledger record of why."""

    generator = _generator(gemini_api_keys="key-a,key-b")
    pool = generator._thinking
    pool.record_probe_attempt = AsyncMock()  # type: ignore[method-assign]
    pool.mark_exhausted = AsyncMock()  # type: ignore[method-assign]
    # Also keeps the real implementation from consuming one of the scripted
    # `time.monotonic` values below: patching that name via this module patches
    # the shared `time` module, which quota.py reads from as well.
    pool.note_request_sent = AsyncMock()  # type: ignore[method-assign]

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
    # Each ping is a real outbound request, so it stamps the per-minute window
    # at send time exactly like ordinary traffic (ADR-0058).
    assert pool.note_request_sent.await_count == 2
    tried = {c.args for c in pool.mark_exhausted.await_args_list}
    assert tried == {(0, _THINKING_MODEL), (1, _THINKING_MODEL)}
    pool.include_model.assert_awaited_once_with(_THINKING_MODEL)


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
        ("ascii", "CARD TYPE REQUIREMENT — ASCII SCENE"),
        ("comparison", "MYTH VS FACT / COMPARISON"),
        ("code", "CODE / SYNTAX / CONFIGURATION"),
        ("diagram", "DIAGRAM, WRITTEN IN MERMAID"),
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


async def test_generate_cards_ascii_plan_uses_fetched_scene_not_writer_art() -> None:
    """ADR-0080: retrieval moved to the fetcher. The writer prompt no longer
    carries library candidates; an ascii brief is marked "art: PROVIDED" when
    the fetcher matched it, and the card's `visual_slots` come from the fetched
    scene (with its `src_id`), NOT from anything the writer drew."""

    generator = _generator()
    wire = _WireCardBatch(
        cards=[
            # The writer "disobeys" and draws its own scene anyway -- it must be
            # ignored in favour of the fetched one.
            _WireCard(
                title="T1",
                canonical_title="CT1",
                summary="S1",
                body="B1",
                ascii_label="writer-drew-this",
                ascii_art="  x\n /|\\",
                ascii_alt="writer alt",
            ),
            _WireCard(
                title="T2",
                canonical_title="CT2",
                summary="S2",
                body="B2",
                ascii_label="free-draw",
                ascii_art="  o\n /|\\\n / \\",
                ascii_alt="free alt",
            ),
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
            topic_name="Gym",
            subtopic_title="Progressive Overload",
            subtopic_description="Adding load over time",
            difficulty=Difficulty.BEGINNER,
            count=2,
            existing_titles=[],
            builds_on=[],
            difficulty_examples={},
            avoid_bodies=[],
            rejection_feedback=[],
            card_type="ascii",
            plans=[
                CardPlan(
                    canonical_title="Progressive Overload",
                    card_type="ascii",
                    asset_direction="a boxer in a fighting stance getting stronger",
                    content_direction="the gag angle",
                    fetched_scene=FetchedAsciiScene(
                        src_id="art_52_5",
                        label="boxer-overload",
                        art="  o/  vs  \\o\n /|    |\\",
                        alt="two boxers, one bulking up",
                    ),
                ),
                CardPlan(
                    canonical_title="Rest Days Matter",
                    card_type="ascii",
                    asset_direction="a couch that refuses to give the lifter back",
                    content_direction="the gag angle",
                    fetched_scene=None,  # no library scene fit -> writer free-draws
                ),
            ],
        )

    assert len(result.items) == 2
    user_prompt = str(captured_prompt[0])
    assert "Curated reference pieces" not in user_prompt
    assert "art: PROVIDED" in user_prompt
    assert "art: draw one" in user_prompt

    provided, free_draw = result.items
    assert provided.visual_slots == {
        "art": "  o/  vs  \\o\n /|    |\\",
        "alt": "two boxers, one bulking up",
        "src_id": "art_52_5",
    }
    assert provided.visual_id == "boxer-overload"
    # The no-match card keeps whatever the writer drew, with no src_id.
    assert free_draw.visual_slots is not None
    assert free_draw.visual_slots.get("src_id") is None
    assert "o" in free_draw.visual_slots["art"]


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


# --- ADR-0066: over-budget ASCII art is redrawn, then rejected with its card ---

_VALID_ART = "  o\n /|\\\n / \\"
_OVERSIZED_ART = "  \\o/  " + "x" * _ASCII_MAX_WIDTH + "\n / \\"


def _schema_dispatch(mapping: dict[object, object]) -> Mock:
    """A `with_structured_output` stand-in that hands back a different scripted
    runnable per requested schema, so one `generate_cards` call can script both
    the card batch and the ASCII redraw batch. `.call_args_list` records which
    schema each `_invoke_with_retry` asked for."""

    def _make(schema: object) -> AsyncMock:
        return _mock_structured(mapping[schema])

    return Mock(side_effect=_make)


async def _generate_one_ascii_card(
    generator: GeminiContentGenerator,
    card_wire: _WireCardBatch,
    redraw_wire: _WireAsciiRedrawBatch,
) -> tuple[object, Mock]:
    dispatch = _schema_dispatch({_WireCardBatch: card_wire, _WireAsciiRedrawBatch: redraw_wire})
    with patch.object(ChatGoogleGenerativeAI, "with_structured_output", dispatch):
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
            card_type="ascii",
        )
    return result, dispatch


def _redraw_call_count(dispatch: Mock) -> int:
    return sum(1 for c in dispatch.call_args_list if c.args[0] is _WireAsciiRedrawBatch)


def _wire_card_with_art(label: str, art: str) -> _WireCardBatch:
    return _WireCardBatch(
        cards=[
            _WireCard(
                title="T",
                canonical_title="CT",
                summary="S",
                body="B",
                ascii_label=label,
                ascii_art=art,
                ascii_alt="alt",
            )
        ]
    )


async def test_generate_cards_ascii_within_budget_is_not_sent_for_redraw() -> None:
    generator = _generator()
    result, dispatch = await _generate_one_ascii_card(
        generator, _wire_card_with_art("scene", _VALID_ART), _WireAsciiRedrawBatch()
    )

    assert len(result.items) == 1
    assert result.items[0].visual_slots == {"art": _VALID_ART, "alt": "alt"}
    assert _redraw_call_count(dispatch) == 0


async def test_generate_cards_oversized_ascii_is_redrawn_not_dropped() -> None:
    generator = _generator()
    redraw_wire = _WireAsciiRedrawBatch(
        scenes=[
            _WireAsciiScene(
                index=0, ascii_label="scene", ascii_art=_VALID_ART, ascii_alt="fixed alt"
            )
        ]
    )
    result, dispatch = await _generate_one_ascii_card(
        generator, _wire_card_with_art("scene", _OVERSIZED_ART), redraw_wire
    )

    assert len(result.items) == 1
    assert result.items[0].visual_id == "scene"
    assert result.items[0].visual_slots == {"art": _VALID_ART, "alt": "fixed alt"}
    assert result.failures == []
    assert _redraw_call_count(dispatch) == 1


async def test_generate_cards_ascii_still_oversized_after_redraws_rejects_whole_card() -> None:
    generator = _generator()  # ascii_redraw_attempts defaults to 2
    redraw_wire = _WireAsciiRedrawBatch(
        scenes=[
            _WireAsciiScene(index=0, ascii_label="wide", ascii_art=_OVERSIZED_ART, ascii_alt="alt")
        ]
    )
    result, dispatch = await _generate_one_ascii_card(
        generator, _wire_card_with_art("wide", _OVERSIZED_ART), redraw_wire
    )

    assert result.items == []
    assert len(result.failures) == 1
    assert "card rejected" in result.failures[0]
    assert "wide" in result.failures[0]
    # Two redraw attempts (the config default) before giving up.
    assert _redraw_call_count(dispatch) == 2


async def test_generate_cards_ascii_redraw_disabled_rejects_without_a_redraw_call() -> None:
    generator = _generator(ascii_redraw_attempts=0)
    result, dispatch = await _generate_one_ascii_card(
        generator, _wire_card_with_art("wide", _OVERSIZED_ART), _WireAsciiRedrawBatch()
    )

    assert result.items == []
    assert "card rejected" in result.failures[0]
    assert _redraw_call_count(dispatch) == 0


async def test_generate_cards_ascii_redraw_quota_exhaustion_propagates() -> None:
    generator = _generator()
    generator._generator.acquire = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(0, _GENERATOR_MODEL), QuotaExhaustedError("exhausted mid-redraw")]
    )
    dispatch = _schema_dispatch(
        {
            _WireCardBatch: _wire_card_with_art("wide", _OVERSIZED_ART),
            _WireAsciiRedrawBatch: _WireAsciiRedrawBatch(),
        }
    )
    with (
        patch.object(ChatGoogleGenerativeAI, "with_structured_output", dispatch),
        pytest.raises(QuotaExhaustedError),
    ):
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
            card_type="ascii",
        )
