"""ADR-0076: report a card, and the operator triage that follows.

`report_card` is reachable by any signed-in reader (guests included -- a report
costs nothing and needs no durable account). The `list_queue` / `delete` / `fix`
/ `remake` methods are the operator surface, mounted `env != "production"` (task
0035); this service does not re-check a role because there is no role yet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.api.schemas import (
    RepairAttemptOut,
    RepairCardOut,
    RepairEnqueuedOut,
    RepairQueueItemOut,
    RepairReportOut,
)
from spoin.domain.enums import CardReportReason, CardStatus, RepairMode, RepairStatus
from spoin.domain.models import Card, CardRepair, CardReport, GenerationJob

_TERMINAL_REPAIR = (RepairStatus.DONE, RepairStatus.FAILED)


def _repair_card_out(card: Card) -> RepairCardOut:
    return RepairCardOut(
        card_id=card.id,
        version=card.version,
        title=card.title,
        canonical_title=card.canonical_title,
        summary=card.summary,
        body=card.body,
        archetype=card.archetype,
        visual_id=card.visual_id,
        visual_slots=card.visual_slots,
    )


def _attempt_out(repair: CardRepair | None) -> RepairAttemptOut | None:
    if repair is None:
        return None
    return RepairAttemptOut(
        mode=repair.mode,
        status=repair.status,
        error=repair.error,
        created_at=repair.created_at,
    )


#: Repair work yields to a real user waiting on a new topic (ADR-0076). Below
#: the default generate-job priority of 0.
_REPAIR_JOB_PRIORITY = -10


async def mark_card_reports_resolved(session: AsyncSession, card_id: UUID) -> None:
    """Set `resolved_at` on every open report for a card. Called by the operator
    delete path here and by the worker once a fix/remake lands -- the two
    writers of `CardReport.resolved_at`, kept in one place."""

    now = datetime.now(UTC)
    for report in (
        await session.execute(
            select(CardReport).where(
                CardReport.card_id == card_id, CardReport.resolved_at.is_(None)
            )
        )
    ).scalars():
        report.resolved_at = now


class ModerationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- reader ------------------------------------------------------------

    async def report_card(
        self, user_id: UUID, card_id: UUID, reason: CardReportReason, note: str | None
    ) -> None:
        """Idempotent: a second report from the same user on the same card
        updates their row rather than 409-ing. Only an ACTIVE card can be
        reported -- a retired or superseded one is already handled."""

        card = await self._session.get(Card, card_id)
        if card is None or card.status != CardStatus.ACTIVE:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such card")

        existing = await self._session.scalar(
            select(CardReport).where(CardReport.card_id == card_id, CardReport.user_id == user_id)
        )
        if existing is not None:
            existing.reason = reason
            existing.note = note
            existing.resolved_at = None
        else:
            self._session.add(
                CardReport(card_id=card_id, user_id=user_id, reason=reason, note=note)
            )
        await self._session.commit()

    # -- operator --------------------------------------------------------

    async def list_queue(self) -> list[RepairQueueItemOut]:
        """Two kinds of entry, newest activity first:

        - `state="open"` -- a card with unresolved reports awaiting triage.
        - `state="resolved"` -- a fix/remake has landed (or failed) and the
          entry stays, showing before/after, until the operator dismisses it.
        """

        open_ids = [
            r.card_id
            for r in (
                await self._session.execute(
                    select(CardReport.card_id, func.max(CardReport.created_at).label("t"))
                    .where(CardReport.resolved_at.is_(None))
                    .group_by(CardReport.card_id)
                    .order_by(func.max(CardReport.created_at).desc())
                )
            ).all()
        ]
        resolved_stmt = (
            select(CardRepair)
            .where(
                CardRepair.status.in_(_TERMINAL_REPAIR),
                CardRepair.dismissed_at.is_(None),
            )
            .order_by(CardRepair.created_at.desc())
        )
        if open_ids:
            resolved_stmt = resolved_stmt.where(CardRepair.card_id.not_in(open_ids))
        resolved_repairs = list((await self._session.execute(resolved_stmt)).scalars().all())

        want = (
            set(open_ids)
            | {rp.card_id for rp in resolved_repairs}
            | {rp.result_card_id for rp in resolved_repairs if rp.result_card_id}
        )
        cards = {
            c.id: c
            for c in (await self._session.execute(select(Card).where(Card.id.in_(want)))).scalars()
        }

        reports_by_card: dict[UUID, list[CardReport]] = {}
        if open_ids:
            for rep in (
                await self._session.execute(
                    select(CardReport)
                    .where(CardReport.card_id.in_(open_ids), CardReport.resolved_at.is_(None))
                    .order_by(CardReport.created_at)
                )
            ).scalars():
                reports_by_card.setdefault(rep.card_id, []).append(rep)

        latest_repair: dict[UUID, CardRepair] = {}
        for rp in (
            await self._session.execute(
                select(CardRepair)
                .where(CardRepair.card_id.in_(want))
                .order_by(CardRepair.created_at.desc())
            )
        ).scalars():
            latest_repair.setdefault(rp.card_id, rp)

        out: list[RepairQueueItemOut] = []
        seen: set[UUID] = set()

        for card_id in open_ids:
            card = cards.get(card_id)
            if card is None:
                continue
            seen.add(card_id)
            latest = latest_repair.get(card_id)
            reports = reports_by_card.get(card_id, [])
            out.append(
                RepairQueueItemOut(
                    card_id=card.id,
                    topic_id=card.topic_id,
                    family_id=card.family_id,
                    difficulty=card.difficulty,
                    before=_repair_card_out(card),
                    after=None,
                    report_count=len(reports),
                    reports=[
                        RepairReportOut(reason=r.reason, note=r.note, created_at=r.created_at)
                        for r in reports
                    ],
                    latest_repair=_attempt_out(latest),
                    state="open",
                )
            )

        for rp in resolved_repairs:
            if rp.card_id in seen:
                continue
            before = cards.get(rp.card_id)
            if before is None:
                continue
            seen.add(rp.card_id)
            after = cards.get(rp.result_card_id) if rp.result_card_id else None
            out.append(
                RepairQueueItemOut(
                    card_id=rp.card_id,
                    topic_id=before.topic_id,
                    family_id=before.family_id,
                    difficulty=before.difficulty,
                    before=_repair_card_out(before),
                    after=_repair_card_out(after) if after is not None else None,
                    report_count=0,
                    reports=[],
                    latest_repair=_attempt_out(rp),
                    state="resolved",
                )
            )
        return out

    async def delete_card(self, card_id: UUID) -> RepairEnqueuedOut:
        """Pull the card from every feed (status -> RETIRED), resolve its
        reports, and clear any resolved repair from the queue. No LLM, no job."""

        card = await self._require_active_card(card_id)
        card.status = CardStatus.RETIRED
        await mark_card_reports_resolved(self._session, card_id)
        await self._dismiss_repairs(card_id)
        await self._session.commit()
        return RepairEnqueuedOut(card_id=card_id, action="deleted")

    async def dismiss(self, card_id: UUID) -> RepairEnqueuedOut:
        """Accept the repair: clear its before/after entry from the queue and
        keep the new version live. Reports are already resolved."""

        await self._dismiss_repairs(card_id)
        await self._session.commit()
        return RepairEnqueuedOut(card_id=card_id, action="dismissed")

    async def revert(self, card_id: UUID) -> RepairEnqueuedOut:
        """Undo a landed repair: put the original version back ACTIVE and
        supersede the repaired one. `card_id` is the ORIGINAL (`before`) card --
        the same id every other repair action takes. The repaired row stays in
        the DB (SUPERSEDED) so this is itself reversible."""

        repair = await self._session.scalar(
            select(CardRepair)
            .where(
                CardRepair.card_id == card_id,
                CardRepair.status == RepairStatus.DONE,
                CardRepair.result_card_id.is_not(None),
            )
            .order_by(CardRepair.created_at.desc())
        )
        if repair is None or repair.result_card_id is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="No landed repair to revert for this card"
            )
        before = await self._session.get(Card, card_id)
        after = await self._session.get(Card, repair.result_card_id)
        if before is None or after is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Repair cards missing")

        # Flip the repaired row off first so the one-active-per-family partial
        # unique index is never briefly violated.
        after.status = CardStatus.SUPERSEDED
        await self._session.flush()
        before.status = CardStatus.ACTIVE
        repair.error = "reverted by operator"
        repair.dismissed_at = datetime.now(UTC)
        await self._session.commit()
        return RepairEnqueuedOut(card_id=card_id, action="reverted")

    async def enqueue_fix(
        self, card_id: UUID, *, image: bytes, guidance: str | None
    ) -> RepairEnqueuedOut:
        job = await self._enqueue_repair(card_id, RepairMode.FIX, guidance, image)
        return RepairEnqueuedOut(card_id=card_id, action="fix_enqueued", job_id=job.id)

    async def enqueue_remake(
        self, card_id: UUID, *, instructions: str, image: bytes | None
    ) -> RepairEnqueuedOut:
        job = await self._enqueue_repair(card_id, RepairMode.REMAKE, instructions, image)
        return RepairEnqueuedOut(card_id=card_id, action="remake_enqueued", job_id=job.id)

    # -- internals ------------------------------------------------------

    async def _dismiss_repairs(self, card_id: UUID) -> None:
        now = datetime.now(UTC)
        for rp in (
            await self._session.execute(
                select(CardRepair).where(
                    CardRepair.card_id == card_id,
                    CardRepair.status.in_(_TERMINAL_REPAIR),
                    CardRepair.dismissed_at.is_(None),
                )
            )
        ).scalars():
            rp.dismissed_at = now

    async def _require_active_card(self, card_id: UUID) -> Card:
        card = await self._session.get(Card, card_id)
        if card is None or card.status != CardStatus.ACTIVE:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="No such card, or it is not active"
            )
        return card

    async def _enqueue_repair(
        self, card_id: UUID, mode: RepairMode, guidance: str | None, image: bytes | None
    ) -> GenerationJob:
        card = await self._require_active_card(card_id)

        outstanding = await self._session.scalar(
            select(GenerationJob).where(
                GenerationJob.kind == "repair",
                GenerationJob.card_id == card_id,
                GenerationJob.status.in_(("pending", "running")),
            )
        )
        if outstanding is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="A repair is already queued for this card"
            )

        job = GenerationJob(
            kind="repair",
            topic_id=card.topic_id,
            card_id=card_id,
            status="pending",
            priority=_REPAIR_JOB_PRIORITY,
        )
        self._session.add(job)
        await self._session.flush()
        self._session.add(
            CardRepair(
                card_id=card_id,
                job_id=job.id,
                mode=mode,
                guidance=guidance,
                source_image=image,
                status=RepairStatus.PENDING,
            )
        )
        await self._session.commit()
        return job
