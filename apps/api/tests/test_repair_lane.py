"""ADR-0076: report a card, operator triage, and the repair executor.

`run_card_repair` opens its own `session_scope()` (like the worker), so these
point it at the test database and read results back through the fixture session.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from spoin.domain.enums import (
    CardReportReason,
    CardStatus,
    Difficulty,
    RepairMode,
    RepairStatus,
)
from spoin.domain.models import (
    Card,
    CardRepair,
    CardReport,
    GenerationJob,
    Subtopic,
    Topic,
    User,
)
from spoin.embeddings import HashEmbedder
from spoin.generation import repair as repair_module
from spoin.generation.base import BatchResult, CardRepairQuery, CardRepairResult
from spoin.generation.fake import FakeContentGenerator
from spoin.moderation.service import ModerationService

_TEST_DATABASE_URL = os.environ.get(
    "SPOIN_TEST_DATABASE_URL", os.environ.get("SPOIN_DATABASE_URL", "")
)


@pytest_asyncio.fixture(autouse=True)
async def _repair_env(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> AsyncIterator[None]:
    engine = create_async_engine(_TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def _scope() -> AsyncIterator[AsyncSession]:
        async with maker() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    monkeypatch.setattr(repair_module, "session_scope", _scope)
    yield
    await engine.dispose()


class _AddsCodeFence(FakeContentGenerator):
    async def repair_card_structure(
        self, queries: list[CardRepairQuery]
    ) -> BatchResult[CardRepairResult]:
        q = queries[0]
        return BatchResult(
            items=[
                CardRepairResult(
                    index=q.index,
                    title=q.title,
                    canonical_title=q.canonical_title,
                    summary=q.summary,
                    body=q.body + "\n\n```python\nprint('injected')\n```\n",
                    visual_slots=q.visual_slots,
                    note="added an example",
                )
            ]
        )


async def _card(
    session: AsyncSession, *, body: str = "A plain prose card body."
) -> tuple[User, Card]:
    user = User(email=f"{uuid.uuid4()}@t.local", display_name="R")
    topic = Topic(slug=f"t-{uuid.uuid4().hex[:8]}", canonical_name="Rivers", description="water")
    session.add_all([user, topic])
    await session.flush()
    sub = Subtopic(
        topic_id=topic.id,
        difficulty=Difficulty.BEGINNER,
        title="Meanders",
        description="How rivers bend.",
        target_cards=10,
        min_cards=5,
    )
    session.add(sub)
    await session.flush()
    card = Card(
        family_id=uuid.uuid4(),
        topic_id=topic.id,
        subtopic_id=sub.id,
        difficulty=Difficulty.BEGINNER,
        status=CardStatus.ACTIVE,
        title="Meanders migrate downstream",
        canonical_title="Meanders migrate downstream",
        summary="hook",
        body=body,
    )
    session.add(card)
    await session.flush()
    await session.commit()
    return user, card


# -- reporting + triage ---------------------------------------------------


async def test_report_is_idempotent_per_user_and_card(session: AsyncSession) -> None:
    user, card = await _card(session)
    svc = ModerationService(session)

    await svc.report_card(user.id, card.id, CardReportReason.ART, "art is broken")
    await svc.report_card(user.id, card.id, CardReportReason.FORMATTING, "actually formatting")

    rows = (
        (await session.execute(select(CardReport).where(CardReport.card_id == card.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].reason == CardReportReason.FORMATTING


async def test_queue_lists_then_delete_retires_and_resolves(session: AsyncSession) -> None:
    user, card = await _card(session)
    svc = ModerationService(session)
    await svc.report_card(user.id, card.id, CardReportReason.DIAGRAM, "mangled")

    queue = await svc.list_queue()
    assert [q.card_id for q in queue] == [card.id]
    assert queue[0].report_count == 1

    await svc.delete_card(card.id)

    await session.refresh(card)
    assert card.status == CardStatus.RETIRED
    assert await svc.list_queue() == []


async def test_second_repair_while_one_is_pending_409s(session: AsyncSession) -> None:
    _user, card = await _card(session)
    svc = ModerationService(session)

    await svc.enqueue_fix(card.id, image=b"\x89PNG\r\n\x1a\n0", guidance=None)
    with pytest.raises(HTTPException):
        await svc.enqueue_fix(card.id, image=b"\x89PNG\r\n\x1a\n0", guidance=None)

    jobs = (
        (await session.execute(select(GenerationJob).where(GenerationJob.card_id == card.id)))
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].kind == "repair"


# -- the executor ------------------------------------------------------


async def _enqueue_and_run(
    session: AsyncSession,
    card: Card,
    mode: RepairMode,
    generator: FakeContentGenerator,
    *,
    guidance: str | None,
) -> None:
    svc = ModerationService(session)
    if mode == RepairMode.FIX:
        await svc.enqueue_fix(card.id, image=b"\x89PNG\r\n\x1a\n0", guidance=guidance)
    else:
        assert guidance is not None
        await svc.enqueue_remake(card.id, instructions=guidance, image=None)
    job = await session.scalar(select(GenerationJob).where(GenerationJob.card_id == card.id))
    assert job is not None
    await repair_module.run_card_repair(job.id, card.id, generator, HashEmbedder(384))
    # run_card_repair committed on its own session; refresh this one's cached
    # copy of the original card so assertions read its post-repair state.
    await session.refresh(card)


async def test_fix_mints_a_new_family_version_and_supersedes(session: AsyncSession) -> None:
    _user, card = await _card(session)
    await _enqueue_and_run(session, card, RepairMode.FIX, FakeContentGenerator(), guidance=None)

    versions = (
        (
            await session.execute(
                select(Card).where(Card.family_id == card.family_id).order_by(Card.version)
            )
        )
        .scalars()
        .all()
    )
    assert [c.version for c in versions] == [1, 2]
    assert versions[0].status == CardStatus.SUPERSEDED
    assert versions[1].status == CardStatus.ACTIVE

    repair = await session.scalar(select(CardRepair).where(CardRepair.card_id == card.id))
    assert repair is not None
    assert repair.status == RepairStatus.DONE
    assert repair.result_card_id == versions[1].id


async def test_resolved_fix_shows_before_and_after_until_dismissed(session: AsyncSession) -> None:
    _user, card = await _card(session)
    await _enqueue_and_run(session, card, RepairMode.FIX, FakeContentGenerator(), guidance=None)
    session.expire_all()
    svc = ModerationService(session)

    queue = await svc.list_queue()
    assert len(queue) == 1
    item = queue[0]
    assert item.state == "resolved"
    assert item.before.version == 1
    assert item.after is not None and item.after.version == 2
    assert item.latest_repair is not None and item.latest_repair.status == RepairStatus.DONE

    await svc.dismiss(card.id)
    assert await svc.list_queue() == []


async def test_fix_rejects_an_added_code_fence(session: AsyncSession) -> None:
    _user, card = await _card(session)
    await _enqueue_and_run(session, card, RepairMode.FIX, _AddsCodeFence(), guidance=None)

    await session.refresh(card)
    assert card.status == CardStatus.ACTIVE  # untouched
    repair = await session.scalar(select(CardRepair).where(CardRepair.card_id == card.id))
    assert repair is not None
    assert repair.status == RepairStatus.FAILED
    assert "code fence" in (repair.error or "")


async def test_remake_goes_through_the_gate_and_versions(session: AsyncSession) -> None:
    _user, card = await _card(session)
    await _enqueue_and_run(
        session, card, RepairMode.REMAKE, FakeContentGenerator(), guidance="Rewrite it simpler."
    )

    active = await session.scalar(
        select(Card).where(Card.family_id == card.family_id, Card.status == CardStatus.ACTIVE)
    )
    assert active is not None and active.version == 2
    repair = await session.scalar(select(CardRepair).where(CardRepair.card_id == card.id))
    assert repair is not None and repair.status == RepairStatus.DONE
