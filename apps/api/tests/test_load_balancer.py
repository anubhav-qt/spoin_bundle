"""Unit tests for the per-box load balancer (ADR-0084).

No database: `LoadBalancer` takes its RPD seed as a plain dict and its
write-through as an injected callable, so every rule here is exercised in
memory. Time is passed in as `now`; `_warm` puts construction far enough in the
past that the 60s warm-up has already elapsed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spoin.generation.load_balancer import (
    LoadBalancer,
    Reservation,
    _Slot,
    make_ledger_writer,
    pack_by_tokens,
)
from spoin.generation.quota import (
    AllModelsUnavailableError,
    BoxPool,
    DailyQuotaExhaustedError,
    LadderRung,
)

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_GEN = "gen-model"
_THINK = "think-model"


def _warm(now: datetime = _NOW) -> datetime:
    """A construction `now` old enough that the warm-up window has passed."""

    return now - timedelta(seconds=120)


def _lb(
    *,
    keys: tuple[int, ...] = (0, 1, 2),
    gen: list[LadderRung] | None = None,
    think: list[LadderRung] | None = None,
    seed: dict[tuple[int, str], int] | None = None,
    unavailable: dict[str, float] | None = None,
    writer: object = None,
    send_gap_s: float = 0.0,
    dispatch_stagger_s: float = 0.0,
) -> LoadBalancer:
    return LoadBalancer(
        name="test",
        key_indices=keys,
        generator_ladder=gen or [LadderRung(_GEN, 500, 15)],
        thinking_ladder=think or [LadderRung(_THINK, 20, 5)],
        model_unavailable=unavailable if unavailable is not None else {},
        rpd_seed=seed or {},
        now=_warm(),
        ledger_writer=writer,  # type: ignore[arg-type]
        send_gap_s=send_gap_s,
        dispatch_stagger_s=dispatch_stagger_s,
    )


# --- BoxPool ---------------------------------------------------------------


def test_boxpool_leases_disjoint_slices() -> None:
    pool = BoxPool(10, remainder_size=2)
    _, a = pool.lease(3)
    _, b = pool.lease(3)
    assert len(a) == 3 and len(b) == 3
    assert not set(a) & set(b)
    # The remainder (top 2 indices) is never handed out.
    assert set(a) | set(b) <= {0, 1, 2, 3, 4, 5, 6, 7}
    assert pool.remainder == (8, 9)


def test_boxpool_prefer_order_then_index_order() -> None:
    pool = BoxPool(10, remainder_size=2)
    _, keys = pool.lease(3, prefer=[5, 3])
    assert keys[:2] == (5, 3)


def test_boxpool_short_lease_when_boxable_range_is_tight() -> None:
    pool = BoxPool(6, remainder_size=2)  # boxable = 0..3
    _, a = pool.lease(3)
    _, b = pool.lease(3)
    assert len(a) == 3
    assert len(b) == 1  # only one boxable key left


def test_boxpool_release_returns_keys() -> None:
    pool = BoxPool(6, remainder_size=1)
    _, a = pool.lease(3)
    pool.release(a)
    _, b = pool.lease(5)
    assert set(a) <= set(b)


# --- assignment ----------------------------------------------------------


async def test_warmup_blocks_then_clears() -> None:
    lb = LoadBalancer(
        name="fresh",
        key_indices=(0,),
        generator_ladder=[LadderRung(_GEN, 500, 15)],
        thinking_ladder=[LadderRung(_THINK, 20, 5)],
        model_unavailable={},
        rpd_seed={},
        now=_NOW,
        ledger_writer=None,
    )
    # Right after construction: every cell is treated as cooling.
    assert isinstance(await lb.try_assign("generator", now=_NOW), float)
    # A minute later: assigns.
    got = await lb.try_assign("generator", now=_NOW + timedelta(seconds=61))
    assert isinstance(got, Reservation)


async def test_least_spent_key_first() -> None:
    lb = _lb(seed={(0, _GEN): 40, (1, _GEN): 5, (2, _GEN): 90})
    res = await lb.try_assign("generator", now=_NOW)
    assert isinstance(res, Reservation)
    assert res.key_index == 1


async def test_model_major_falls_to_next_rung_only_when_strong_one_is_spent() -> None:
    lb = _lb(
        keys=(0,),
        gen=[LadderRung("strong", 2, 15), LadderRung("weak", 500, 15)],
    )
    first = await lb.try_assign("generator", now=_NOW)
    assert isinstance(first, Reservation) and first.model == "strong"
    await lb.on_success(first, now=_NOW)
    second = await lb.try_assign("generator", now=_NOW)
    assert isinstance(second, Reservation) and second.model == "strong"
    await lb.on_success(second, now=_NOW)
    # strong is now 2/2 spent -> next call drops to the weak rung.
    third = await lb.try_assign("generator", now=_NOW)
    assert isinstance(third, Reservation) and third.model == "weak"


async def test_rpm_window_fills_then_frees_after_60s() -> None:
    lb = _lb(keys=(0,), think=[LadderRung(_THINK, 20, 3)])
    for _ in range(3):
        r = await lb.try_assign("thinking", now=_NOW)
        assert isinstance(r, Reservation)
    # 4th within the same minute: no room, returns a wait.
    assert isinstance(await lb.try_assign("thinking", now=_NOW), float)
    # After the window rolls, room again.
    later = _NOW + timedelta(seconds=61)
    assert isinstance(await lb.try_assign("thinking", now=later), Reservation)


async def test_per_minute_429_parks_cell_and_learns_ceiling() -> None:
    lb = _lb(keys=(0,), think=[LadderRung(_THINK, 20, 5)])
    # Three sends in the window, then the provider refuses.
    for _ in range(3):
        assert isinstance(await lb.try_assign("thinking", now=_NOW), Reservation)
    refused = await lb.try_assign("thinking", now=_NOW)
    assert isinstance(refused, Reservation)
    lb.on_rate_limited(refused, now=_NOW, per_minute=True)
    cell = lb._cells[(0, _THINK)]
    # Learned ceiling drops to the measured send count (4), not halved blindly.
    assert cell.learned_rpm == 4.0
    # Cell is cooling now.
    assert isinstance(await lb.try_assign("thinking", now=_NOW + timedelta(seconds=1)), float)


async def test_per_day_429_spends_the_cell() -> None:
    lb = _lb(keys=(0,), gen=[LadderRung(_GEN, 500, 15)])
    r = await lb.try_assign("generator", now=_NOW)
    assert isinstance(r, Reservation)
    lb.on_rate_limited(r, now=_NOW, per_minute=False)
    assert lb._cells[(0, _GEN)].rpd_spent == 500
    with pytest.raises(DailyQuotaExhaustedError):
        await lb.try_assign("generator", now=_NOW)


async def test_all_models_unavailable_raises_not_a_quota_error() -> None:
    unavailable = {_GEN: (_NOW + timedelta(minutes=5)).timestamp()}
    lb = _lb(keys=(0,), unavailable=unavailable)
    with pytest.raises(AllModelsUnavailableError):
        await lb.try_assign("generator", now=_NOW)


async def test_exclude_then_include_model() -> None:
    shared: dict[str, float] = {}
    lb = _lb(keys=(0,), unavailable=shared)
    lb.exclude_model(_GEN, now=_NOW, expires_in_s=300)
    with pytest.raises(AllModelsUnavailableError):
        await lb.try_assign("generator", now=_NOW)
    lb.include_model(_GEN)
    assert isinstance(await lb.try_assign("generator", now=_NOW), Reservation)


async def test_model_unavailable_dict_is_shared_across_balancers() -> None:
    shared: dict[str, float] = {}
    box = _lb(keys=(0,), unavailable=shared)
    remainder = _lb(keys=(1,), unavailable=shared)
    box.exclude_model(_GEN, now=_NOW, expires_in_s=300)
    # The other balancer sees it too -- a 503 is the model's problem, not one box's.
    with pytest.raises(AllModelsUnavailableError):
        await remainder.try_assign("generator", now=_NOW)


async def test_on_send_aborted_drops_the_window_slot() -> None:
    lb = _lb(keys=(0,), think=[LadderRung(_THINK, 20, 1)])
    r = await lb.try_assign("thinking", now=_NOW)
    assert isinstance(r, Reservation)
    # rpm 1 -> the cell is now full for the minute.
    assert isinstance(await lb.try_assign("thinking", now=_NOW), float)
    lb.on_send_aborted(r)
    # Slot refunded -> room again immediately.
    assert isinstance(await lb.try_assign("thinking", now=_NOW), Reservation)


async def test_note_send_moves_the_slot_forward() -> None:
    lb = _lb(keys=(0,))
    r = await lb.try_assign("generator", now=_NOW)
    assert isinstance(r, Reservation)
    lb.note_send(r, now=_NOW + timedelta(seconds=30))
    assert r._slot.sent_at == (_NOW + timedelta(seconds=30)).timestamp()


async def test_on_success_probes_the_learned_ceiling_back_up() -> None:
    lb = _lb(keys=(0,), think=[LadderRung(_THINK, 20, 5)])
    cell = lb._cells[(0, _THINK)]
    cell.learned_rpm = 2.0
    r = await lb.try_assign("thinking", now=_NOW)
    assert isinstance(r, Reservation)
    await lb.on_success(r, now=_NOW)
    # First clean call this minute: +1 toward the configured ceiling.
    assert cell.learned_rpm == 3.0
    # A second clean call in the same minute does not stack.
    r2 = await lb.try_assign("thinking", now=_NOW)
    assert isinstance(r2, Reservation)
    await lb.on_success(r2, now=_NOW)
    assert cell.learned_rpm == 3.0
    # A minute later it can climb again.
    r3 = await lb.try_assign("thinking", now=_NOW + timedelta(seconds=61))
    assert isinstance(r3, Reservation)
    await lb.on_success(r3, now=_NOW + timedelta(seconds=61))
    assert cell.learned_rpm == 4.0


async def test_day_rollover_resets_counts_and_ceiling() -> None:
    lb = _lb(keys=(0,), gen=[LadderRung(_GEN, 2, 15)], seed={(0, _GEN): 2})
    with pytest.raises(DailyQuotaExhaustedError):
        await lb.try_assign("generator", now=_NOW)
    tomorrow = _NOW + timedelta(days=1)
    got = await lb.try_assign("generator", now=tomorrow)
    assert isinstance(got, Reservation)
    # Yesterday's seed of 2 is wiped; the reserve doesn't bill until on_success.
    assert lb._cells[(0, _GEN)].rpd_spent == 0
    await lb.on_success(got, now=tomorrow)
    assert lb._cells[(0, _GEN)].rpd_spent == 1


async def test_ledger_write_through_fires_at_the_flush_threshold() -> None:
    writes: list[tuple[int, str, int]] = []

    async def _record(k: int, m: str, spent: int) -> None:
        writes.append((k, m, spent))

    lb = _lb(keys=(0,), gen=[LadderRung(_GEN, 500, 100)], writer=_record)
    for _ in range(9):
        r = await lb.try_assign("generator", now=_NOW)
        assert isinstance(r, Reservation)
        await lb.on_success(r, now=_NOW)
    assert writes == []  # below the every-10 threshold
    r = await lb.try_assign("generator", now=_NOW)
    assert isinstance(r, Reservation)
    await lb.on_success(r, now=_NOW)
    assert writes == [(0, _GEN, 10)]


async def test_flush_writes_every_dirty_cell() -> None:
    writes: list[tuple[int, str, int]] = []

    async def _record(k: int, m: str, spent: int) -> None:
        writes.append((k, m, spent))

    lb = _lb(keys=(0, 1), gen=[LadderRung(_GEN, 500, 100)], writer=_record)
    for _ in range(3):
        r = await lb.try_assign("generator", now=_NOW)
        assert isinstance(r, Reservation)
        await lb.on_success(r, now=_NOW)
    await lb.flush()
    assert sorted(writes) == [(0, _GEN, 2), (1, _GEN, 1)]


async def test_send_gap_paces_one_key_and_spreads_across_the_rest() -> None:
    """The burst brake (ADR-0084): with a 4s gap, one key can't be hit twice
    inside 4s -- a fan-out of many calls spreads across the other keys instead
    of hammering one."""

    lb = _lb(keys=(0, 1, 2), gen=[LadderRung(_GEN, 500, 15)], send_gap_s=4.0)
    r0 = await lb.try_assign("generator", now=_NOW)
    assert isinstance(r0, Reservation)
    first_key = r0.key_index

    # Next two assigns in the same instant go to the OTHER keys, not back to first.
    seen = {first_key}
    for _ in range(2):
        r = await lb.try_assign("generator", now=_NOW)
        assert isinstance(r, Reservation)
        assert r.key_index not in seen
        seen.add(r.key_index)
    assert seen == {0, 1, 2}

    # All three keys are now inside their 4s gap -> a 4th call in the same
    # instant gets a wait, not a cell.
    assert isinstance(await lb.try_assign("generator", now=_NOW), float)

    # 4s later the first key is free again.
    got = await lb.try_assign("generator", now=_NOW + timedelta(seconds=4.1))
    assert isinstance(got, Reservation)


async def test_send_gap_zero_is_no_pacing() -> None:
    lb = _lb(keys=(0,), gen=[LadderRung(_GEN, 500, 15)], send_gap_s=0.0)
    for _ in range(3):
        r = await lb.try_assign("generator", now=_NOW)
        assert isinstance(r, Reservation)
        assert r.key_index == 0  # same key, back to back, no gap


async def test_paced_mode_shelves_the_window_and_learned_rpm() -> None:
    """With a send gap on, the trailing-60s window and the learned ceiling are
    dormant: a 429 parks the cell for its cooldown but does NOT ratchet
    learned_rpm, and the window length never blocks an assign."""

    lb = _lb(keys=(0,), think=[LadderRung(_THINK, 20, 5)], send_gap_s=4.0)
    cell = lb._cells[(0, _THINK)]
    r = await lb.try_assign("thinking", now=_NOW)
    assert isinstance(r, Reservation)
    lb.on_rate_limited(r, now=_NOW, per_minute=True)
    assert cell.learned_rpm == 5.0  # unchanged -- learning is shelved
    assert cell.cooldown_until > _NOW.timestamp()  # but the cell is parked


async def test_dispatch_round_robins_evenly_across_cells() -> None:
    """The primary sort key is per-run dispatch count, so 12 assigns across 3
    keys land 4 apiece -- not piled onto whichever had the coldest ledger seed."""

    lb = _lb(
        keys=(0, 1, 2),
        gen=[LadderRung(_GEN, 500, 15)],
        seed={(0, _GEN): 400, (1, _GEN): 10, (2, _GEN): 0},
        send_gap_s=0.0,
    )
    counts = {0: 0, 1: 0, 2: 0}
    for i in range(12):
        r = await lb.try_assign("generator", now=_NOW + timedelta(seconds=i * 0.01))
        assert isinstance(r, Reservation)
        counts[r.key_index] += 1
    assert counts == {0: 4, 1: 4, 2: 4}


def test_make_ledger_writer_returns_a_coroutine_callable() -> None:
    writer = make_ledger_writer()
    assert callable(writer)


def test_reservation_carries_a_private_slot() -> None:
    slot = _Slot(sent_at=_NOW.timestamp())
    res = Reservation(key_index=3, model=_GEN, _slot=slot)
    assert res.key_index == 3
    assert res._slot is slot


async def test_send_gap_never_outruns_a_slow_rungs_own_rpm() -> None:
    """One configured gap, two ladders with different `rpm`: the gap is a floor,
    widened per rung by `_gap_for`.

    The thinking rungs are rpm 5 (12s between sends) and the generator rungs
    rpm 15 (4s). A single `gemini_send_gap_seconds = 4.0` used to pace both,
    driving every thinking cell 3x over its documented limit.
    """

    lb = _lb(keys=(0,), send_gap_s=4.0)

    think = await lb.try_assign("thinking", now=_NOW)
    assert isinstance(think, Reservation)
    # 4s is the configured gap but not this rung's -- 60/5 = 12s is.
    assert isinstance(await lb.try_assign("thinking", now=_NOW + timedelta(seconds=4.1)), float)
    assert isinstance(
        await lb.try_assign("thinking", now=_NOW + timedelta(seconds=12.1)), Reservation
    )

    # The generator rung's own rpm (15 -> 4s) is not slower than the floor, so
    # the configured gap still governs it.
    gen = await lb.try_assign("generator", now=_NOW)
    assert isinstance(gen, Reservation)
    assert isinstance(
        await lb.try_assign("generator", now=_NOW + timedelta(seconds=4.1)), Reservation
    )


async def test_unattributed_429_cooldown_credits_the_window_already_served() -> None:
    """A 429 with no `RetryInfo` waits one window from the cell's OLDEST live
    send, not a flat minute from now -- the latter re-serves time the trailing
    window has already served."""

    lb = _lb(keys=(0,), gen=[LadderRung(_GEN, 500, 15)])
    res = await lb.try_assign("generator", now=_NOW)
    assert isinstance(res, Reservation)
    lb.note_send(res, now=_NOW)

    # The 429 lands 50s after the send that is still in the window: only the
    # window's remaining 10s is owed, not another full 60.
    late = _NOW + timedelta(seconds=50)
    lb.on_rate_limited(res, now=late, per_minute=True)
    assert isinstance(await lb.try_assign("generator", now=late), float)
    assert isinstance(
        await lb.try_assign("generator", now=_NOW + timedelta(seconds=60.1)), Reservation
    )


# --- TPM window (ADR-0085) -------------------------------------------------


async def test_token_window_blocks_a_cell_over_its_tpm_and_spreads_to_the_next() -> None:
    """The trailing-minute TOKEN ceiling gates independently of the request
    ceiling: a cell inside its rpm can still be out of tokens."""

    lb = _lb(keys=(0, 1), gen=[LadderRung(_GEN, 500, 15, 10_000)])
    first = await lb.try_assign("generator", now=_NOW, est_tokens=6_000)
    assert isinstance(first, Reservation)
    lb.note_send(first, now=_NOW, tokens=6_000)

    # Key 0 has 4k of its 10k minute left, so a 6k call must land elsewhere.
    second = await lb.try_assign("generator", now=_NOW, est_tokens=6_000)
    assert isinstance(second, Reservation)
    assert second.key_index != first.key_index
    lb.note_send(second, now=_NOW, tokens=6_000)

    # Both cells are now over; the balancer reports a wait, not a reservation.
    assert isinstance(await lb.try_assign("generator", now=_NOW, est_tokens=6_000), float)
    # A SMALL call still fits in what is left of the same minute.
    assert isinstance(await lb.try_assign("generator", now=_NOW, est_tokens=1_000), Reservation)


async def test_tokens_age_out_of_the_trailing_minute() -> None:
    lb = _lb(keys=(0,), gen=[LadderRung(_GEN, 500, 15, 10_000)])
    res = await lb.try_assign("generator", now=_NOW, est_tokens=9_000)
    assert isinstance(res, Reservation)
    lb.note_send(res, now=_NOW, tokens=9_000)

    assert isinstance(await lb.try_assign("generator", now=_NOW, est_tokens=9_000), float)
    later = _NOW + timedelta(seconds=61)
    assert isinstance(await lb.try_assign("generator", now=later, est_tokens=9_000), Reservation)


async def test_aborted_send_refunds_its_tokens() -> None:
    """A call that never left spent no tokens -- same refund the request window
    already gets (ADR-0061)."""

    lb = _lb(keys=(0,), gen=[LadderRung(_GEN, 500, 15, 10_000)])
    res = await lb.try_assign("generator", now=_NOW, est_tokens=9_000)
    assert isinstance(res, Reservation)
    lb.note_send(res, now=_NOW, tokens=9_000)
    lb.on_send_aborted(res)

    assert isinstance(await lb.try_assign("generator", now=_NOW, est_tokens=9_000), Reservation)


def test_parse_ladder_takes_an_optional_tpm() -> None:
    from spoin.generation.quota import parse_ladder

    three = parse_ladder("m:500:15")
    assert (three[0].rpd, three[0].rpm, three[0].tpm) == (500, 15, 250_000)

    four = parse_ladder("m:500:15:80000")
    assert four[0].tpm == 80_000

    with pytest.raises(ValueError, match="model:rpd:rpm"):
        parse_ladder("m:500")


# --- pack_by_tokens (ADR-0085) ---------------------------------------------


def test_pack_by_tokens_cuts_a_chunk_short_when_the_items_are_fat() -> None:
    """The batch-size setting is the ceiling on COUNT; the budget is the ceiling
    on WEIGHT, and whichever binds first ends the chunk."""

    items = [("a", 400), ("b", 400), ("c", 400), ("d", 400)]
    chunks = pack_by_tokens(items, cost=lambda i: i[1], budget=1000, max_items=10)
    # 400+400 fits, a third would be 1200 -- so it spills.
    assert [[i[0] for i in c] for c in chunks] == [["a", "b"], ["c", "d"]]


def test_pack_by_tokens_still_honours_the_count_ceiling() -> None:
    items = [("a", 1), ("b", 1), ("c", 1), ("d", 1), ("e", 1)]
    chunks = pack_by_tokens(items, cost=lambda i: i[1], budget=10_000, max_items=2)
    assert [len(c) for c in chunks] == [2, 2, 1]


def test_pack_by_tokens_gives_an_oversized_item_its_own_chunk() -> None:
    """Splitting one card's body is not this function's business, and dropping
    it would be a silent loss of content to satisfy an estimate."""

    items = [("small", 10), ("huge", 99_999), ("small2", 10)]
    chunks = pack_by_tokens(items, cost=lambda i: i[1], budget=1000, max_items=10)
    assert [[i[0] for i in c] for c in chunks] == [["small"], ["huge"], ["small2"]]


def test_pack_by_tokens_handles_an_empty_list() -> None:
    assert pack_by_tokens([], cost=lambda _i: 1, budget=100, max_items=5) == []


# --- dispatch staggering (ADR-0086) ----------------------------------------


async def test_dispatch_stagger_spaces_consecutive_reservations_across_different_cells() -> None:
    """While `send_gap_s` spaces sends to the SAME cell, `dispatch_stagger_s`
    spaces reservations across DIFFERENT cells (ADR-0086). Even when key 1 is
    completely fresh and cold, it must wait out the stagger interval."""

    lb = _lb(keys=(0, 1), dispatch_stagger_s=0.5)

    # First reservation takes key 0 immediately at _NOW.
    res1 = await lb.try_assign("generator", now=_NOW)
    assert isinstance(res1, Reservation)
    assert res1.key_index == 0

    # Second reservation at the exact same instant is declined with the remaining stagger wait.
    wait = await lb.try_assign("generator", now=_NOW)
    assert isinstance(wait, float)
    assert pytest.approx(wait, 0.01) == 0.5

    # At _NOW + 0.2s, 0.3s of the stagger remains.
    wait2 = await lb.try_assign("generator", now=_NOW + timedelta(seconds=0.2))
    assert isinstance(wait2, float)
    assert pytest.approx(wait2, 0.01) == 0.3

    # At _NOW + 0.5s, the stagger window has passed -- key 1 is reserved.
    res2 = await lb.try_assign("generator", now=_NOW + timedelta(seconds=0.5))
    assert isinstance(res2, Reservation)
    assert res2.key_index == 1


async def test_dispatch_stagger_zero_allows_simultaneous_dispatches_across_cells() -> None:
    """With dispatch_stagger_s=0.0 (tests, fake backend), different cells can be
    reserved at the exact same instant without waiting."""

    lb = _lb(keys=(0, 1), dispatch_stagger_s=0.0)
    res1 = await lb.try_assign("generator", now=_NOW)
    res2 = await lb.try_assign("generator", now=_NOW)
    assert isinstance(res1, Reservation) and res1.key_index == 0
    assert isinstance(res2, Reservation) and res2.key_index == 1


async def test_dispatch_stagger_updated_by_note_send() -> None:
    """A send delayed behind cell_lock anchors the pool dispatch stamp to its
    actual departure time, protecting the next reservation by the full stagger."""

    lb = _lb(keys=(0, 1), dispatch_stagger_s=0.5)
    res = await lb.try_assign("generator", now=_NOW)
    assert isinstance(res, Reservation)

    # Simulated cell_lock delay: send leaves at _NOW + 1.0s.
    delayed_send = _NOW + timedelta(seconds=1.0)
    lb.note_send(res, now=delayed_send)

    # At _NOW + 1.2s, only 0.2s has passed since the true send -- must wait 0.3s.
    wait = await lb.try_assign("generator", now=_NOW + timedelta(seconds=1.2))
    assert isinstance(wait, float)
    assert pytest.approx(wait, 0.01) == 0.3

