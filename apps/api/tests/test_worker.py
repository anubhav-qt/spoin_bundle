"""Tests for the worker's job-claiming and per-job isolation (ADR-0026, task 0008).

`run_once()` opens its own sessions internally (`session_scope()`, one per job,
by design — see worker/__main__.py's docstring) rather than taking a session as
a parameter, so these tests point that at the SAME test database the `session`
fixture uses, and read results back through the fixture's own session.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from spoin.core.config import Settings
from spoin.domain.models import Card, GenerationJob, Topic
from spoin.embeddings import HashEmbedder
from spoin.generation.fake import FakeContentGenerator
from spoin.generation.quota import QuotaExhaustedError
from spoin.worker import __main__ as worker_module

_TEST_DATABASE_URL = os.environ.get(
    "SPOIN_TEST_DATABASE_URL", os.environ.get("SPOIN_DATABASE_URL", "")
)


class _FlakyGenerator(FakeContentGenerator):
    """Raises for one specific topic name, real (fake) generation for every
    other — simulates a single job's generation failing without touching the
    others in the same worker pass."""

    def __init__(self, fail_topic_name: str) -> None:
        super().__init__()
        self._fail_topic_name = fail_topic_name

    async def generate_curriculum(self, topic_name, description, existing_subtopics=None):  # type: ignore[no-untyped-def]
        if topic_name == self._fail_topic_name:
            raise RuntimeError("simulated generation failure")
        return await super().generate_curriculum(topic_name, description, existing_subtopics)


class _QuotaExhaustedGenerator(FakeContentGenerator):
    """Simulates the whole key x model grid (ADR-0028) being spent for the
    day — the case the worker is supposed to requeue rather than fail."""

    def __init__(self, exhausted_topic_name: str) -> None:
        super().__init__()
        self._exhausted_topic_name = exhausted_topic_name

    async def generate_curriculum(self, topic_name, description, existing_subtopics=None):  # type: ignore[no-untyped-def]
        if topic_name == self._exhausted_topic_name:
            raise QuotaExhaustedError("all keys exhausted for today (simulated)")
        return await super().generate_curriculum(topic_name, description, existing_subtopics)


@pytest_asyncio.fixture(autouse=True)
async def _worker_env(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession, settings: Settings
) -> AsyncIterator[None]:
    """Depending on `session` means this fixture (and every test using it)
    skips automatically when no test database is configured, same as every
    other integration test here."""

    engine = create_async_engine(_TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def _test_session_scope():
        async with maker() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    monkeypatch.setattr(worker_module, "session_scope", _test_session_scope)
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_module, "get_content_generator", lambda: FakeContentGenerator())
    monkeypatch.setattr(worker_module, "get_embedder", lambda: HashEmbedder(settings.embedding_dim))

    yield

    await engine.dispose()


async def test_run_once_completes_a_pending_job_and_persists_cards(session: AsyncSession) -> None:
    topic = Topic(slug="worker-topic", canonical_name="Worker Topic")
    session.add(topic)
    await session.flush()
    job = GenerationJob(topic_id=topic.id, status="pending")
    session.add(job)
    await session.commit()

    processed = await worker_module.run_once()
    assert processed == 1

    await session.refresh(job)
    assert job.status == "completed"
    assert job.attempts == 1
    assert job.completed_at is not None
    assert job.last_error is None

    from sqlalchemy import select

    cards = (await session.execute(select(Card).where(Card.topic_id == topic.id))).scalars().all()
    assert len(cards) > 0


async def test_run_once_isolates_one_jobs_failure_from_others(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    good_topic = Topic(slug="good-topic", canonical_name="Good Topic")
    bad_topic = Topic(slug="bad-topic", canonical_name="Bad Topic")
    session.add_all([good_topic, bad_topic])
    await session.flush()
    good_job = GenerationJob(topic_id=good_topic.id, status="pending")
    bad_job = GenerationJob(topic_id=bad_topic.id, status="pending")
    session.add_all([good_job, bad_job])
    await session.commit()

    monkeypatch.setattr(worker_module, "get_content_generator", lambda: _FlakyGenerator("Bad Topic"))

    processed = await worker_module.run_once()
    assert processed == 2

    await session.refresh(good_job)
    await session.refresh(bad_job)
    assert good_job.status == "completed"
    assert bad_job.status == "failed"
    assert bad_job.attempts == 1
    assert bad_job.last_error is not None
    assert "simulated generation failure" in bad_job.last_error

    from sqlalchemy import select

    good_cards = (
        await session.execute(select(Card).where(Card.topic_id == good_topic.id))
    ).scalars().all()
    bad_cards = (
        await session.execute(select(Card).where(Card.topic_id == bad_topic.id))
    ).scalars().all()
    assert len(good_cards) > 0
    assert len(bad_cards) == 0


async def test_quota_exhausted_requeues_the_job_instead_of_failing_it(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic = Topic(slug="quota-topic", canonical_name="Quota Topic")
    session.add(topic)
    await session.flush()
    job = GenerationJob(topic_id=topic.id, status="pending")
    session.add(job)
    await session.commit()

    monkeypatch.setattr(
        worker_module, "get_content_generator", lambda: _QuotaExhaustedGenerator("Quota Topic")
    )

    processed = await worker_module.run_once()
    assert processed == 1

    await session.refresh(job)
    # ADR-0028: quota exhaustion is an expected daily ceiling, not a bug --
    # the job goes back to "pending" (idempotent per ADR-0026) so tomorrow's
    # cron pass just continues, rather than being stuck "failed" forever next
    # to jobs that failed for a real reason.
    assert job.status == "pending"
    assert job.attempts == 1
    assert job.last_error is not None
    assert "quota exhausted" in job.last_error


async def test_run_once_returns_zero_when_nothing_pending(session: AsyncSession) -> None:
    assert await worker_module.run_once() == 0


async def test_coalescing_lock_prevents_duplicate_pending_jobs_for_same_topic(
    session: AsyncSession,
) -> None:
    topic = Topic(slug="dup-topic", canonical_name="Dup Topic")
    session.add(topic)
    await session.flush()
    session.add(GenerationJob(topic_id=topic.id, status="pending"))
    await session.flush()
    session.add(GenerationJob(topic_id=topic.id, status="pending"))
    with pytest.raises(IntegrityError):
        await session.flush()
