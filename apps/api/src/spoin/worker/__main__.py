"""Worker entrypoint: `python -m spoin.worker`.

**One batch pass, then exit.** ADR-0003 §3: at free-tier quota a persistent pool
has nothing to do 99% of the time, and free hosting tiers sleep idle services
anyway. So this runs on a GitHub Actions cron (~every 15 min): claim pending jobs,
spend that slice of quota, exit. That also paces the daily quota across the day
instead of exhausting it by 9am.

The same job functions run as a persistent loop once we are paying — a different
entrypoint over identical code, which is what "no accommodation may require a
rewrite to undo" means in practice.

**Per-job isolation (ADR-0026).** Each claimed job runs the one-shot pipeline
(`run_generation_pipeline`, ADR-0026) in its OWN `asyncio` task with its OWN DB
session, gathered together. One job's exception marks only that job `failed` —
it never touches any other job in the same pass. Cross-job concurrency and
failure isolation live here, in the worker; the pipeline's own LangGraph
concurrency (ADR-0024) is scoped to a single topic's run.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select

from spoin.core.config import get_settings
from spoin.core.db import get_engine, session_scope
from spoin.domain.models import GenerationJob
from spoin.embeddings import Embedder, get_embedder
from spoin.generation import get_content_generator
from spoin.generation.base import ContentGenerator
from spoin.generation.pipeline import run_generation_pipeline
from spoin.generation.quota import QuotaExhaustedError

logger = logging.getLogger("spoin.worker")


async def _run_job(
    job_id: uuid.UUID,
    topic_id: uuid.UUID,
    generator: ContentGenerator,
    embedder: Embedder,
) -> None:
    """One job, start to finish, on its own session throughout — including the
    status write-back, so a crash between generation and write-back can't leave
    a job silently stuck `running` forever (the next pass's claim query would
    just never see it again; an operational concern for later, not solved here)."""

    settings = get_settings()
    try:
        async with session_scope() as session:
            report = await run_generation_pipeline(
                session, generator, embedder, settings, topic_ids=[topic_id]
            )
            job = await session.get(GenerationJob, job_id)
            assert job is not None
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            job.attempts += 1
            job.last_error = None
        topics = cast(list[dict[str, Any]], report.get("topics", []))
        accepted = topics[0].get("accepted", 0) if topics else 0
        logger.info("job %s completed (topic=%s, cards_accepted=%s)", job_id, topic_id, accepted)
    except QuotaExhaustedError as exc:
        # ADR-0028: not a bug, an expected daily ceiling. Requeue rather than
        # fail -- run_generation_pipeline is idempotent (ADR-0026), so the next
        # cron pass (after tomorrow's quota resets) just picks up wherever this
        # one stopped, instead of the topic being stuck "failed" forever next
        # to jobs that failed for a real reason.
        logger.info("job %s paused: quota exhausted (topic=%s): %s", job_id, topic_id, exc)
        async with session_scope() as session:
            job = await session.get(GenerationJob, job_id)
            if job is not None:
                job.status = "pending"
                job.attempts += 1
                job.last_error = f"quota exhausted, requeued: {exc}"[:2000]
    except Exception as exc:
        logger.exception("job %s failed (topic=%s)", job_id, topic_id)
        async with session_scope() as session:
            job = await session.get(GenerationJob, job_id)
            if job is not None:
                job.status = "failed"
                job.attempts += 1
                job.last_error = str(exc)[:2000]


async def run_once() -> int:
    """Claim whatever is pending, highest priority first, and run every claimed
    job concurrently with per-job isolation.

    Returns the number of jobs processed (attempted, not necessarily succeeded —
    see each job's own `status`/`last_error` for outcome).
    """

    settings = get_settings()
    logger.info("worker pass starting (generator=%s)", settings.generator)

    async with session_scope() as session:
        pending = (
            (
                await session.execute(
                    select(GenerationJob)
                    .where(GenerationJob.status == "pending")
                    # Prioritised, not FIFO (ADR-0003 §6): a demand-triggered fill
                    # (a real user is waiting) outranks speculative background
                    # work. When quota runs out, low-priority work waits for
                    # tomorrow rather than everyone starving equally.
                    .order_by(GenerationJob.priority.desc(), GenerationJob.created_at)
                    .limit(settings.generation_batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not pending:
            logger.info("nothing to do")
            return 0

        # Claim now, in this same transaction, so a crash before dispatch
        # doesn't leave these silently re-claimable as `pending` next pass.
        claimed = [(job.id, job.topic_id) for job in pending]
        for job in pending:
            job.status = "running"

    generator = get_content_generator()
    embedder = get_embedder()

    await asyncio.gather(
        *(_run_job(job_id, topic_id, generator, embedder) for job_id, topic_id in claimed)
    )

    logger.info("worker pass finished (%d job(s) processed)", len(claimed))
    return len(claimed)


async def _watch() -> None:
    """Local-dev-only persistent loop: `run_once()` repeatedly, on
    `settings.worker_poll_seconds`, instead of the single pass production's
    cron entrypoint takes. Same function, same per-job isolation, same
    quota/failure handling — the only difference is what calls it and how
    often. This is what makes a topic typed into the app during local dev
    actually get generated without a developer re-running the worker by hand
    (docker-compose.yml's `worker` service runs this mode)."""

    settings = get_settings()
    logger.info(
        "worker watching for jobs every %.1fs (generator=%s)",
        settings.worker_poll_seconds,
        settings.generator,
    )
    while True:
        try:
            await run_once()
        except Exception:
            # A pass-level failure (e.g. a transient DB hiccup) must not kill
            # the loop -- individual job failures are already isolated inside
            # run_once/_run_job; this is the outer safety net for everything
            # else.
            logger.exception("worker pass raised; continuing to watch")
        await asyncio.sleep(settings.worker_poll_seconds)


async def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    watch = "--watch" in sys.argv
    try:
        if watch:
            await _watch()
        else:
            await run_once()
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
