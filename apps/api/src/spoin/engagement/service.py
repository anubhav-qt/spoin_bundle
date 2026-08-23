"""Engagement ingest and the seen-state machine.

Two things in here are easy to get wrong and expensive to fix later:

1. `explicit_complete` and `dwell_complete` are **separate events**. Equivalent for
   the progression gate; very different for ranking. Collapsing them into one
   boolean is not recoverable from the log, because the distinction would never
   have been written down.
2. `occurred_at` is server-assigned, always.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.enums import COMPLETION_KINDS, CardStatus, EngagementKind, SeenState
from spoin.domain.models import (
    Card,
    CardBookmark,
    CardLike,
    EngagementEvent,
    UserCardState,
    UserSessionTopicSignal,
    UserSubtopicProgress,
    UserTopicCycle,
    UserTopicDifficultyProgress,
)


@dataclass(frozen=True)
class IncomingEvent:
    id: UUID
    card_id: UUID
    kind: EngagementKind
    dwell_ms: int | None = None
    client_occurred_at: datetime | None = None
    session_id: UUID | None = None


@dataclass(frozen=True)
class IngestResult:
    accepted: int
    duplicates: int
    rejected: int


class EngagementService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def ingest(self, user_id: UUID, events: list[IncomingEvent]) -> IngestResult:
        """Insert a client batch, deduplicating on the client-generated id.

        Retries and flaky networks produce duplicates. Without dedup, impression
        counts inflate and every rate computed from them is wrong — and since
        `card_quality` is a rate, that corrupts ranking rather than merely
        miscounting.
        """

        if not events:
            return IngestResult(0, 0, 0)

        cards = await self._card_lookup([event.card_id for event in events])

        rows = []
        rejected = 0
        for event in events:
            card = cards.get(event.card_id)
            if card is None:
                rejected += 1
                continue

            dwell = self._sanitize_dwell(event.dwell_ms)
            if event.dwell_ms is not None and dwell is None:
                # Discard implausible values at ingest rather than storing them. A
                # tab left open overnight is not a nine-hour engagement, and one
                # such row skews avg_dwell for a card permanently.
                rejected += 1
                continue

            rows.append(
                {
                    "id": event.id,
                    "user_id": user_id,
                    "card_id": event.card_id,
                    "topic_id": card[0],
                    "subtopic_id": card[1],
                    "kind": event.kind,
                    "dwell_ms": dwell,
                    "client_occurred_at": event.client_occurred_at,
                    "session_id": event.session_id,
                }
            )

        if not rows:
            return IngestResult(0, 0, rejected)

        statement = (
            pg_insert(EngagementEvent)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(EngagementEvent.id)
        )
        inserted = len((await self._session.execute(statement)).scalars().all())

        # Sort rows to ensure a consistent lock acquisition order across concurrent
        # requests, preventing deadlocks on user_card_state and user_subtopic_progress.
        # Python's sort is stable, so multiple events for the SAME card retain
        # their chronological order from the client batch.
        rows.sort(key=lambda r: (r["subtopic_id"], r["card_id"]))

        now = datetime.now(UTC)
        for row in rows:
            await self._apply_state(user_id, row)
            # Driven from here rather than from `_apply_state`, which returns early
            # for impressions, skips and completions — the session profile needs
            # every kind, including the ones that state machine handles and stops.
            await self._bump_session_signal(user_id, row, now=now)

        await self._session.flush()
        return IngestResult(
            accepted=inserted,
            duplicates=len(rows) - inserted,
            rejected=rejected,
        )

    # --------------------------------------------------------- state machine --
    async def _apply_state(self, user_id: UUID, row: dict[str, object]) -> None:
        kind = row["kind"]
        assert isinstance(kind, EngagementKind)

        if kind is EngagementKind.IMPRESSION:
            # An impression means the card was actually on screen long enough to
            # be looked at (the client only emits one after ~1s of continuous
            # visibility, not on a fast flick past). That makes it "shown", which
            # is DEFERRED -- eligible again, but only after the rest of this
            # difficulty has had its turn.
            #
            # This used to write UNSEEN with the comment "scrolling past never
            # counts", which meant nothing except deliberate reading ever
            # consumed a card. A reader who scrolled without opening anything got
            # the same slate back forever, because every card stayed eligible.
            #
            # DEFERRED is deliberately NOT counted anywhere coverage is: the 80%
            # quiz gate reads `state == SEEN` exclusively (see
            # `_bump_subtopic_progress` below), so being shown a card never
            # advances progression. Only reading it does.
            await self._defer(user_id, row)
            return

        if kind is EngagementKind.SKIP:
            await self._defer(user_id, row)
            return

        if kind in COMPLETION_KINDS:
            await self._mark_seen(user_id, row, via=kind)
            return

        if kind is EngagementKind.LIKE:
            await self._session.execute(
                pg_insert(CardLike)
                .values(user_id=user_id, card_id=row["card_id"])
                .on_conflict_do_nothing()
            )
        elif kind is EngagementKind.UNLIKE:
            await self._session.execute(
                delete(CardLike).where(
                    CardLike.user_id == user_id, CardLike.card_id == row["card_id"]
                )
            )
        elif kind is EngagementKind.BOOKMARK:
            await self._session.execute(
                pg_insert(CardBookmark)
                .values(user_id=user_id, card_id=row["card_id"])
                .on_conflict_do_nothing()
            )
        elif kind is EngagementKind.UNBOOKMARK:
            await self._session.execute(
                delete(CardBookmark).where(
                    CardBookmark.user_id == user_id, CardBookmark.card_id == row["card_id"]
                )
            )

    async def _defer(self, user_id: UUID, row: dict[str, object]) -> None:
        """DEFERRED: shown, but not read. Comes back once this difficulty's
        cycle advances -- see `feed/service.py`'s `_maybe_advance_cycle`.

        Reached from an impression (the common path: the card was on screen and
        the reader moved on) and from an explicit SKIP."""

        cycle = await self._current_cycle(user_id, row)
        statement = pg_insert(UserCardState).values(
            user_id=user_id,
            card_id=row["card_id"],
            topic_id=row["topic_id"],
            subtopic_id=row["subtopic_id"],
            state=SeenState.DEFERRED,
            deferred_cycle=cycle,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "card_id"],
                set_={
                    "state": SeenState.DEFERRED,
                    "deferred_cycle": cycle,
                },
                # SEEN is terminal. A stray skip event arriving after a completion
                # must never walk a card backwards out of the progression count.
                where=UserCardState.state != SeenState.SEEN,
            )
        )

    async def _mark_seen(
        self, user_id: UUID, row: dict[str, object], *, via: EngagementKind
    ) -> None:
        now = datetime.now(UTC)
        statement = pg_insert(UserCardState).values(
            user_id=user_id,
            card_id=row["card_id"],
            topic_id=row["topic_id"],
            subtopic_id=row["subtopic_id"],
            state=SeenState.SEEN,
            completed_via=via,
            seen_at=now,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "card_id"],
                set_={"state": SeenState.SEEN, "completed_via": via, "seen_at": now},
                where=UserCardState.state != SeenState.SEEN,
            )
        )
        await self._bump_progress(user_id, row)

    async def _bump_progress(self, user_id: UUID, row: dict[str, object]) -> None:
        """Keep `user_subtopic_progress` current so the 80% gate stays a column read.

        This is a derived aggregate and fully rebuildable from the event log; it is
        maintained here incrementally only so the read path never has to count.
        """

        seen_count = await self._session.scalar(
            select(func.count())
            .select_from(UserCardState)
            .where(
                UserCardState.user_id == user_id,
                UserCardState.subtopic_id == row["subtopic_id"],
                UserCardState.state == SeenState.SEEN,
            )
        )
        total_count = await self._session.scalar(
            select(func.count())
            .select_from(Card)
            .where(
                Card.subtopic_id == row["subtopic_id"],
                Card.status == CardStatus.ACTIVE,
            )
        )

        await self._session.execute(
            pg_insert(UserSubtopicProgress)
            .values(
                user_id=user_id,
                subtopic_id=row["subtopic_id"],
                seen_count=seen_count or 0,
                total_count=total_count or 0,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "subtopic_id"],
                set_={"seen_count": seen_count or 0, "total_count": total_count or 0},
            )
        )

        await self._bump_difficulty_progress(user_id, row)

    async def _bump_difficulty_progress(self, user_id: UUID, row: dict[str, object]) -> None:
        """Keep `user_topic_difficulty_progress` current -- the dynamic
        difficulty mix ramp's input (feed/strata.py `dynamic_mix`). Same
        incremental-aggregate pattern as `_bump_progress` just above, scoped
        to the whole topic+tier instead of one subtopic."""

        difficulty = await self._session.scalar(
            select(Card.difficulty).where(Card.id == row["card_id"])
        )
        if difficulty is None:
            return

        seen_count = await self._session.scalar(
            select(func.count())
            .select_from(UserCardState)
            .join(Card, Card.id == UserCardState.card_id)
            .where(
                UserCardState.user_id == user_id,
                Card.topic_id == row["topic_id"],
                Card.difficulty == difficulty,
                UserCardState.state == SeenState.SEEN,
            )
        )
        total_count = await self._session.scalar(
            select(func.count())
            .select_from(Card)
            .where(
                Card.topic_id == row["topic_id"],
                Card.difficulty == difficulty,
                Card.status == CardStatus.ACTIVE,
            )
        )

        await self._session.execute(
            pg_insert(UserTopicDifficultyProgress)
            .values(
                user_id=user_id,
                topic_id=row["topic_id"],
                difficulty=difficulty,
                seen_count=seen_count or 0,
                total_count=total_count or 0,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "topic_id", "difficulty"],
                set_={"seen_count": seen_count or 0, "total_count": total_count or 0},
            )
        )

    # -------------------------------------------------------- session profile --
    async def _bump_session_signal(
        self, user_id: UUID, row: dict[str, object], *, now: datetime
    ) -> None:
        """Accumulate this event into the current session's weight for its topic.

        The feed reads the result as a plain column, so the aggregation happens
        here at write time and never in the read path (ADR-0011). See
        `feed/session_profile.py` for what the score is eventually turned into.
        """

        kind = row["kind"]
        assert isinstance(kind, EngagementKind)
        topic_id = row["topic_id"]
        assert isinstance(topic_id, UUID)

        contribution = self._settings.session_signal_weights().get(kind, 0.0)
        dwell_ms = row["dwell_ms"]
        if isinstance(dwell_ms, int):
            # Already bounded by `_sanitize_dwell`, so this cannot be an overnight
            # tab masquerading as sustained interest.
            contribution += dwell_ms / 1000.0 * self._settings.session_w_dwell_per_second

        if contribution == 0.0:
            return

        window = timedelta(seconds=self._settings.session_window_seconds)
        statement = pg_insert(UserSessionTopicSignal).values(
            user_id=user_id,
            topic_id=topic_id,
            score=contribution,
            last_event_at=now,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "topic_id"],
                set_={
                    # Reset-or-accumulate in one statement. Postgres holds a row
                    # lock across the conflicting update, so two concurrent
                    # ingests for the same (user, topic) serialize rather than
                    # losing one of the contributions -- the same guarantee
                    # `UserTopicCycle`'s `cycle + 1` upsert already leans on.
                    #
                    # The reset is what makes the session end: an event arriving
                    # after the window has lapsed starts a new profile instead of
                    # resuming one built hours ago.
                    "score": case(
                        (
                            UserSessionTopicSignal.last_event_at < now - window,
                            statement.excluded.score,
                        ),
                        else_=UserSessionTopicSignal.score + statement.excluded.score,
                    ),
                    "last_event_at": statement.excluded.last_event_at,
                },
            )
        )

    async def _current_cycle(self, user_id: UUID, row: dict[str, object]) -> int:
        card_difficulty = await self._session.scalar(
            select(Card.difficulty).where(Card.id == row["card_id"])
        )
        cycle = await self._session.scalar(
            select(UserTopicCycle.cycle).where(
                UserTopicCycle.user_id == user_id,
                UserTopicCycle.topic_id == row["topic_id"],
                UserTopicCycle.difficulty == card_difficulty,
            )
        )
        return cycle or 0

    # ---------------------------------------------------------------- helpers --
    def _sanitize_dwell(self, dwell_ms: int | None) -> int | None:
        if dwell_ms is None:
            return None
        if dwell_ms < 0 or dwell_ms > self._settings.dwell_max_ms:
            return None
        return dwell_ms

    async def _card_lookup(self, card_ids: list[UUID]) -> dict[UUID, tuple[UUID, UUID]]:
        rows = (
            await self._session.execute(
                select(Card.id, Card.topic_id, Card.subtopic_id).where(Card.id.in_(card_ids))
            )
        ).all()
        return {row[0]: (row[1], row[2]) for row in rows}
