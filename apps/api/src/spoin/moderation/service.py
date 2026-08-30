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
    RepairEnqueuedOut,
    RepairQueueItemOut,
    RepairReportOut,
)
from spoin.domain.enums import CardReportReason, CardStatus, RepairMode, RepairStatus
from spoin.domain.models import Card, CardRepair, CardReport, GenerationJob

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
        """Cards with at least one unresolved report, newest report first, each
        with its full text (so the operator judges without a second fetch), all
        its unresolved reports, and its latest `card_repair` attempt if any."""

        card_ids = (
            await self._session.execute(
                select(CardReport.card_id, func.max(CardReport.created_at).label("latest"))
                .where(CardReport.resolved_at.is_(None))
                .group_by(CardReport.card_id)
                .order_by(func.max(CardReport.created_at).desc())
            )
        ).all()
        if not card_ids:
            return []

        ids = [row.card_id for row in card_ids]
        cards = {
            c.id: c
            for c in (await self._session.execute(select(Card).where(Card.id.in_(ids)))).scalars()
        }
        reports_by_card: dict[UUID, list[CardReport]] = {}
        for report in (
            await self._session.execute(
                select(CardReport)
                .where(CardReport.card_id.in_(ids), CardReport.resolved_at.is_(None))
                .order_by(CardReport.created_at)
            )
        ).scalars():
            reports_by_card.setdefault(report.card_id, []).append(report)

        latest_repair: dict[UUID, CardRepair] = {}
        for repair in (
            await self._session.execute(
                select(CardRepair)
                .where(CardRepair.card_id.in_(ids))
                .order_by(CardRepair.created_at.desc())
            )
        ).scalars():
            latest_repair.setdefault(repair.card_id, repair)

        out: list[RepairQueueItemOut] = []
        for row in card_ids:
            card = cards.get(row.card_id)
            if card is None:
                continue
            reports = reports_by_card.get(row.card_id, [])
            latest = latest_repair.get(row.card_id)
            out.append(
                RepairQueueItemOut(
                    card_id=card.id,
                    topic_id=card.topic_id,
                    family_id=card.family_id,
                    version=card.version,
                    difficulty=card.difficulty,
                    title=card.title,
                    canonical_title=card.canonical_title,
                    summary=card.summary,
                    body=card.body,
                    archetype=card.archetype,
                    visual_id=card.visual_id,
                    visual_slots=card.visual_slots,
                    report_count=len(reports),
                    reports=[
                        RepairReportOut(reason=r.reason, note=r.note, created_at=r.created_at)
                        for r in reports
                    ],
                    latest_repair=(
                        RepairAttemptOut(
                            mode=latest.mode,
                            status=latest.status,
                            error=latest.error,
                            created_at=latest.created_at,
                        )
                        if latest is not None
                        else None
                    ),
                )
            )
        return out

    async def delete_card(self, card_id: UUID) -> RepairEnqueuedOut:
        """Pull the card from every feed (status -> RETIRED) and resolve its
        reports. No LLM, no job."""

        card = await self._require_active_card(card_id)
        card.status = CardStatus.RETIRED
        await mark_card_reports_resolved(self._session, card_id)
        await self._session.commit()
        return RepairEnqueuedOut(card_id=card_id, action="deleted")

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
