"""Unit tests for the key x model quota governor (generation/quota.py, ADR-0028).

Pure DB bookkeeping — no real Gemini key needed, no network. Uses the real
`session` fixture (Postgres, skipped if unavailable) since `QuotaLedger` rows and
`day`-scoped uniqueness are the whole point of what's under test. RPM is
in-memory only, so those tests don't touch the database at all — they rely on
calls happening well within one 60s window, never on real sleeping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.domain.models.quiz import QuotaLedger, QuotaRequest
from spoin.generation.quota import LadderRung, QuotaExhaustedError, QuotaGovernor, parse_ladder


def _ladder(*rungs: tuple[str, int, int]) -> list[LadderRung]:
    return [LadderRung(model=model, rpd=rpd, rpm=rpm) for model, rpd, rpm in rungs]


async def _window_rows(session: AsyncSession, backend: str) -> list[QuotaRequest]:
    """Every request row recorded for one cell, oldest first."""

    result = await session.scalars(
        select(QuotaRequest).where(QuotaRequest.backend == backend).order_by(QuotaRequest.sent_at)
    )
    return list(result)


async def _spent(session: AsyncSession, backend: str, on: datetime) -> int:
    """Today's billed RPD for one cell -- the number the phantom refund moves."""

    day = on.replace(hour=0, minute=0, second=0, microsecond=0)
    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.day == day, QuotaLedger.backend == backend)
    )
    assert ledger is not None, f"no ledger row for {backend} on {day.date()}"
    return ledger.requests_spent


async def test_stays_on_first_key_and_model_while_under_target(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=3, ladder=_ladder(("model-a", 5, 100)))
    now = datetime.now(UTC)

    results = [await governor.acquire_with_session(session, now=now) for _ in range(4)]

    assert results == [(0, "model-a")] * 4
    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:0:model-a")
    )
    assert ledger is not None
    assert ledger.requests_spent == 4
    assert ledger.exhausted_at is None


async def test_drains_every_key_before_falling_to_the_next_model(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 2, 100), ("model-b", 2, 100)))
    now = datetime.now(UTC)

    results = [await governor.acquire_with_session(session, now=now) for _ in range(5)]

    # Both keys exhaust model-a (2 each) before model-b is ever touched.
    assert results == [
        (0, "model-a"),
        (0, "model-a"),
        (1, "model-a"),
        (1, "model-a"),
        (0, "model-b"),
    ]
    exhausted = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:1:model-a")
    )
    assert exhausted is not None
    assert exhausted.exhausted_at is not None


async def test_rpm_ceiling_skips_to_the_next_key_without_waiting(session: AsyncSession) -> None:
    # Huge RPD, tiny RPM -- the second call within the same instant should
    # skip key 0 (already at its 1-per-minute ceiling) rather than wait.
    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 100, 1)))
    now = datetime.now(UTC)

    first = await governor.acquire_with_session(session, now=now)
    second = await governor.acquire_with_session(session, now=now)

    assert first == (0, "model-a")
    assert second == (1, "model-a")


async def test_mark_exhausted_forces_a_cell_off_the_ladder(session: AsyncSession) -> None:
    """A real 429 from the provider disagreeing with our local ledger (the
    ADR-0028 drift risk) -- mark_exhausted must make the NEXT acquire() skip
    that cell, even though the ledger only recorded 0 requests against it."""

    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 20, 100)))
    now = datetime.now(UTC)

    await governor.mark_exhausted_with_session(session, 0, "model-a", now=now)
    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:0:model-a")
    )
    assert ledger is not None
    assert ledger.requests_spent >= 20
    assert ledger.exhausted_at is not None

    result = await governor.acquire_with_session(session, now=now)
    assert result == (1, "model-a")


async def test_excluded_model_is_skipped_until_included_again(session: AsyncSession) -> None:
    """`exclude_model` (called the moment a call times out -- see
    langchain_impl.py's DeadlineExceeded handler) must keep EVERY key off that
    model, not just one -- and `include_model` must restore it exactly as it
    was, with no ledger side effects either way."""

    governor = QuotaGovernor(
        key_count=2, ladder=_ladder(("model-a", 20, 100), ("model-b", 20, 100))
    )
    now = datetime.now(UTC)

    governor.exclude_model("model-a")
    first = await governor.acquire_with_session(session, now=now)
    second = await governor.acquire_with_session(session, now=now)
    assert first == (0, "model-b")
    assert second == (0, "model-b")

    governor.include_model("model-a")
    third = await governor.acquire_with_session(session, now=now)
    assert third == (0, "model-a")


async def test_record_probe_attempt_spends_ledger_like_a_real_acquire(
    session: AsyncSession,
) -> None:
    """A background recovery probe's own calls count against today's ledger
    exactly like a real acquired call -- it is one real request against the
    provider, not free reconnaissance (see langchain_impl.py's _probe_model)."""

    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 20, 100)))
    now = datetime.now(UTC)

    await governor.record_probe_attempt_with_session(session, 0, "model-a", now=now)
    await governor.record_probe_attempt_with_session(session, 0, "model-a", now=now)

    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:0:model-a")
    )
    assert ledger is not None
    assert ledger.requests_spent == 2

    # A subsequent real acquire() picks up from the ledger the probe already
    # spent against, not from zero -- "already filled data for today's quota
    # from before" is kept, never reset.
    result = await governor.acquire_with_session(session, now=now)
    assert result == (0, "model-a")
    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:0:model-a")
    )
    assert ledger is not None
    assert ledger.requests_spent == 3


async def test_record_probe_attempt_rejects_unknown_model(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 20, 100)))
    with pytest.raises(ValueError, match="not in this pool's ladder"):
        await governor.record_probe_attempt_with_session(
            session, 0, "model-b", now=datetime.now(UTC)
        )


async def test_raises_once_every_key_and_model_exhausted(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 1, 100)))
    now = datetime.now(UTC)

    await governor.acquire_with_session(session, now=now)
    await governor.acquire_with_session(session, now=now)

    with pytest.raises(QuotaExhaustedError):
        await governor.acquire_with_session(session, now=now)


async def test_separate_days_get_separate_ledger_rows(session: AsyncSession) -> None:
    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 2, 100)))
    day_one = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    day_two = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)

    await governor.acquire_with_session(session, now=day_one)
    await governor.acquire_with_session(session, now=day_one)
    # Day one's key is exhausted, but day two is a fresh ledger row — same
    # key/model, different day, should NOT raise.
    result = await governor.acquire_with_session(session, now=day_two)

    assert result == (0, "model-a")
    rows = (await session.execute(select(QuotaLedger))).scalars().all()
    assert len(rows) == 2


def test_parse_ladder_reads_model_rpd_rpm_triples() -> None:
    rungs = parse_ladder("gemini-3.7-flash:20:5, gemini-2.5-flash:20:5")
    assert rungs == [
        LadderRung(model="gemini-3.7-flash", rpd=20, rpm=5),
        LadderRung(model="gemini-2.5-flash", rpd=20, rpm=5),
    ]


def test_parse_ladder_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="at least one rung"):
        parse_ladder("")


def test_governor_rejects_empty_ladder() -> None:
    with pytest.raises(ValueError, match="at least one ladder rung"):
        QuotaGovernor(key_count=1, ladder=[])


async def test_rate_limited_cell_cools_down_without_spending_the_ledger(
    session: AsyncSession,
) -> None:
    """The ADR-0058 fix: a per-minute 429 parks a cell but must NOT touch its
    daily ledger. Folding the two together is what made a burst of throttling
    read back as "every key exhausted for today" on keys with quota to spare."""

    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 20, 100)))
    now = datetime.now(UTC)

    spent_before = await governor.acquire_with_session(session, now=now)
    assert spent_before == (0, "model-a")

    await governor.mark_rate_limited_with_session(
        session, 0, "model-a", now=now, retry_after_s=13.0
    )

    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:0:model-a")
    )
    assert ledger is not None
    # The one real acquire above, and nothing else -- not reset to 0, not
    # inflated to the RPD ceiling.
    assert ledger.requests_spent == 1
    assert ledger.exhausted_at is None
    assert ledger.cooldown_until == now + timedelta(seconds=13)

    # Cooling, so the next acquire routes around it rather than raising.
    assert await governor.acquire_with_session(session, now=now) == (1, "model-a")

    # ...and it comes back on its own once the cooldown lapses.
    later = now + timedelta(seconds=14)
    assert await governor.acquire_with_session(session, now=later) == (0, "model-a")


async def test_repeated_rate_limiting_never_exhausts_a_cell(session: AsyncSession) -> None:
    """No number of per-minute 429s may add up to a day-long exhaustion. This is
    the regression guard for `_FLASH_LITE_MAX_RESETS`, the 10-strike cap this
    replaced: strike 11 used to write `requests_spent = rpd` and take a healthy
    key out of rotation for the rest of the day."""

    # RPD comfortably above the loop count: the point is that THROTTLING never
    # exhausts a cell, so the real daily ceiling must stay out of the way. (The
    # 50 genuine acquires below still count against it -- that monotonic spend
    # is exactly what bounds the retry loop in `_invoke_with_retry`.)
    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 200, 100)))
    start = datetime.now(UTC)

    for tick in range(50):
        # Each iteration is a fresh minute, so the cooldown from the previous
        # one has lapsed and the RPM window is clear -- isolating the daily
        # ledger as the only thing under test here.
        now = start + timedelta(minutes=tick)
        await governor.mark_rate_limited_with_session(
            session, 0, "model-a", now=now, retry_after_s=5.0
        )
        assert await governor.acquire_with_session(session, now=now + timedelta(seconds=6)) == (
            0,
            "model-a",
        )

    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:0:model-a")
    )
    assert ledger is not None
    # Purely the 50 real acquires. Under the old cap this cell would have been
    # written up to its RPD ceiling and marked exhausted long before here.
    assert ledger.requests_spent == 50
    assert ledger.exhausted_at is None


async def test_acquire_reserves_rpm_before_the_call_is_sent(session: AsyncSession) -> None:
    """The reservation has to count immediately. If the window only recorded
    real sends, every concurrent caller would see an empty window and pile onto
    the same cell while the first call was still queued on its cell lock."""

    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 100, 1)))
    now = datetime.now(UTC)

    assert await governor.acquire_with_session(session, now=now) == (0, "model-a")

    rows = await _window_rows(session, "gemini:0:model-a")
    assert len(rows) == 1
    assert rows[0].confirmed is False

    # Key 0 is at its 1/min ceiling on the strength of a reservation alone.
    assert await governor.acquire_with_session(session, now=now) == (1, "model-a")


async def test_note_request_sent_restamps_the_reservation(session: AsyncSession) -> None:
    """ADR-0058: the window must be anchored to when the request actually left,
    not when the cell was granted. Confirming a reservation updates it rather
    than adding to it, so the ceiling is unchanged and only the expiry moves."""

    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 100, 15)))
    granted_at = datetime.now(UTC)

    await governor.acquire_with_session(session, now=granted_at)
    # 30s queued behind another call on this cell before actually going out.
    sent_at = granted_at + timedelta(seconds=30)
    await governor.note_request_sent_with_session(session, 0, "model-a", now=sent_at)

    rows = await _window_rows(session, "gemini:0:model-a")
    assert len(rows) == 1, "confirming a reservation must not add a second row"
    assert rows[0].confirmed is True
    # Anchored to the send, so it leaves the window 60s after THAT, not after
    # the grant -- which is the whole alignment fix.
    assert rows[0].sent_at == sent_at


async def test_note_request_sent_without_a_reservation_records_an_extra_call(
    session: AsyncSession,
) -> None:
    """A 503 retried on the same cell is a second real request against the same
    grant. The reservation covered the first one, so the retry has to add a row
    of its own rather than silently reusing it."""

    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 100, 15)))
    now = datetime.now(UTC)

    await governor.acquire_with_session(session, now=now)
    await governor.note_request_sent_with_session(session, 0, "model-a", now=now)
    await governor.note_request_sent_with_session(session, 0, "model-a", now=now)

    rows = await _window_rows(session, "gemini:0:model-a")
    assert len(rows) == 2
    assert all(row.confirmed for row in rows)


async def test_two_processes_share_one_ceiling(session: AsyncSession) -> None:
    """The reason this state moved into the database at all (ADR-0058).

    Two `QuotaGovernor` instances stand in for the API process and the worker.
    With the window in process memory they each permitted the full ceiling on
    the same key, so the provider saw double what either believed it had sent.
    """

    # RPD == RPM on purpose: this is the only cell in the pool, so once RPM
    # blocks the 4th call the daily ledger is ALSO already at 3 -- the call
    # fails outright rather than entering the self-pacing wait, which is not
    # what this test is about (that path has its own coverage).
    api = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 3, 3)))
    worker = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 3, 3)))
    now = datetime.now(UTC)

    await api.acquire_with_session(session, now=now)
    await worker.acquire_with_session(session, now=now)
    await api.acquire_with_session(session, now=now)

    # Three used between them; the fourth must be refused whichever instance
    # asks, because the ceiling belongs to the KEY, not to the process.
    with pytest.raises(QuotaExhaustedError):
        await worker.acquire_with_session(session, now=now)

    assert len(await _window_rows(session, "gemini:0:model-a")) == 3


async def test_probe_attempt_counts_against_rpm_not_just_the_ledger(
    session: AsyncSession,
) -> None:
    """A probe is a real request. It used to spend RPD while staying invisible
    to the per-minute window, so real traffic could be granted a cell the probe
    had just used."""

    governor = QuotaGovernor(key_count=2, ladder=_ladder(("model-a", 100, 1)))
    now = datetime.now(UTC)

    await governor.record_probe_attempt_with_session(session, 0, "model-a", now=now)

    assert len(await _window_rows(session, "gemini:0:model-a")) == 1
    # Key 0 is spoken for by the probe, so real traffic routes to key 1.
    assert await governor.acquire_with_session(session, now=now) == (1, "model-a")


async def test_prune_drops_only_rows_past_every_cell_s_window(session: AsyncSession) -> None:
    """Rows are worthless once they age out, but pruning at exactly the window
    edge would race readers still counting them -- so the retention is a
    multiple of the window, and anything younger stays put."""

    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 100, 15)))
    now = datetime.now(UTC)

    await governor.acquire_with_session(session, now=now - timedelta(hours=1))
    await governor.acquire_with_session(session, now=now)

    deleted = await governor.prune_request_window(session, now=now)

    assert deleted == 1
    rows = await _window_rows(session, "gemini:0:model-a")
    assert [row.sent_at for row in rows] == [now]


async def test_prune_refunds_a_grant_that_never_became_a_request(
    session: AsyncSession,
) -> None:
    """ADR-0061: `acquire()` bills RPD at grant time, but the call fires later.
    A task that dies in that gap leaves the cell billed for a request the
    provider never saw, and nothing else ever reconciles it -- measured live as
    a ~19% over-count (ledger 107 vs the provider's own 87)."""

    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 100, 15)))
    now = datetime.now(UTC)
    stale = now - timedelta(hours=1)

    # Two grants an hour ago; only one of them ever reached the provider.
    await governor.acquire_with_session(session, now=stale)
    await governor.acquire_with_session(session, now=stale)
    await governor.note_request_sent_with_session(session, 0, "model-a", now=stale)
    assert await _spent(session, "gemini:0:model-a", stale) == 2

    await governor.prune_request_window(session, now=now)

    assert await _spent(session, "gemini:0:model-a", stale) == 1, (
        "the never-sent grant must be refunded, the real send must not"
    )


async def test_prune_never_refunds_a_confirmed_send(session: AsyncSession) -> None:
    """The over-count from a 429'd request is deliberate, not a leak to plug.

    `_invoke_with_retry` retries a per-minute 429 WITHOUT burning a cell, so the
    climbing ledger is the only thing that ends that loop -- and ADR-0060 routed
    unidentifiable 429s down it too. Refunding a confirmed send would turn the
    retry path into retry/refund/retry forever, so this stays pinned."""

    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 100, 15)))
    now = datetime.now(UTC)
    stale = now - timedelta(hours=1)

    for _ in range(3):
        await governor.acquire_with_session(session, now=stale)
        await governor.note_request_sent_with_session(session, 0, "model-a", now=stale)

    await governor.prune_request_window(session, now=now)

    assert await _spent(session, "gemini:0:model-a", stale) == 3


async def test_prune_leaves_an_exhausted_cell_retired(session: AsyncSession) -> None:
    """Bookkeeping must never resurrect a cell `mark_exhausted` deliberately
    retired for the day -- otherwise a phantom refund could drop a genuinely
    dead cell back under its cap and put it straight back into rotation."""

    governor = QuotaGovernor(key_count=1, ladder=_ladder(("model-a", 100, 15)))
    now = datetime.now(UTC)
    stale = now - timedelta(hours=1)

    await governor.acquire_with_session(session, now=stale)  # never sent
    await governor.mark_exhausted_with_session(session, 0, "model-a", now=stale)

    await governor.prune_request_window(session, now=now)

    assert await _spent(session, "gemini:0:model-a", stale) == 100


async def test_mark_exhausted_is_day_long_for_every_model(session: AsyncSession) -> None:
    """`mark_exhausted` used to special-case any model with "flash-lite" in its
    name into a spend-reset instead of an exhaustion -- which silently inverted
    the recovery probe's intent, since the probe calls it precisely to keep a
    dead model out of rotation for the rest of the day."""

    governor = QuotaGovernor(key_count=1, ladder=_ladder(("gemini-3.5-flash-lite", 20, 100)))
    now = datetime.now(UTC)

    await governor.mark_exhausted_with_session(session, 0, "gemini-3.5-flash-lite", now=now)

    ledger = await session.scalar(
        select(QuotaLedger).where(QuotaLedger.backend == "gemini:0:gemini-3.5-flash-lite")
    )
    assert ledger is not None
    assert ledger.requests_spent >= 20
    assert ledger.exhausted_at is not None

    with pytest.raises(QuotaExhaustedError):
        await governor.acquire_with_session(session, now=now)
