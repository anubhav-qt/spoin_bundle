"""Worker entrypoint: `python -m spoin.worker`.

**One batch pass, then exit.** ADR-0003 §3: at free-tier quota a persistent pool
has nothing to do 99% of the time, and free hosting tiers sleep idle services
anyway. So this runs on a GitHub Actions cron (~every 15 min): claim pending jobs,
spend that slice of quota, exit. That also paces the daily quota across the day
instead of exhausting it by 9am.

The same job functions run as a persistent loop once we are paying — a different
entrypoint over identical code, which is what "no accommodation may require a
rewrite to undo" means in practice.

**A pass runs as many jobs as the key pool holds BOXES (ADR-0082).** It claims
up to `settings.max_concurrent_topics` pending jobs — `pool // topic_key_box_size`,
so 2 at the current 75-key pool and a box of 34 — in priority-then-`created_at` order, and runs
them concurrently, each on its OWN DB session and its OWN box of keys, sharing
one `ContentGenerator` so a single `BoxPool` keeps the boxes disjoint. One job's
exception marks only that job `failed`/`pending`; failure isolation is per-job.
Inside a box, the pipeline's LangGraph concurrency (ADR-0024) fans out per
subtopic group; each generation call routes through the box's `LoadBalancer`
(ADR-0084), which picks the least-spent key in the box and serialises the send
per `(key, model)` cell — so at most one caller per cell, over this topic's 34
keys, not the whole pool.

That is the hybrid: bounded inside a box, parallel across boxes. ADR-0073's
strictly-sequential loop under-used a 119-key pool; ADR-0078's width-derived
leases over-used it (a dozen topics at once burst the per-minute ceilings and
the run stopped being walk-away-safe). A fixed box makes total in-flight work a
constant — `max_concurrent_topics * box_size` keys — instead of a function of
how many topics happen to be queued.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from frog.embeddings import Embedder
from sqlalchemy import select

from spoin.core.config import get_settings
from spoin.core.db import get_engine, session_scope
from spoin.domain.models import GenerationJob
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator
from spoin.generation.base import ContentGenerator
from spoin.generation.pipeline import run_generation_pipeline
from spoin.generation.quota import (
    AllCellsThrottledError,
    AllModelsUnavailableError,
    DailyQuotaExhaustedError,
    QuotaExhaustedError,
)
from spoin.generation.repair import run_card_repair

logger = logging.getLogger("spoin.worker")

#: How a paused job describes WHY it paused (ADR-0065). Three different facts
#: about the world that all requeue the same way -- kept distinguishable in the
#: log and in `GenerationJob.last_error` so the next person reading a stalled
#: queue can tell an outage from an exhausted budget without re-deriving it.
_QUOTA_PAUSE_CAUSE: dict[type[QuotaExhaustedError], str] = {
    DailyQuotaExhaustedError: "daily quota exhausted (resumes after reset)",
    AllCellsThrottledError: "throttled on every cell (daily quota remains)",
    AllModelsUnavailableError: "every model unavailable -- provider outage, not quota",
}


async def _run_job(
    job_id: uuid.UUID,
    topic_id: uuid.UUID,
    kind: str,
    card_id: uuid.UUID | None,
    generator: ContentGenerator,
    embedder: Embedder,
) -> None:
    """One job, start to finish, on its own session throughout — including the
    status write-back, so a crash between generation and write-back can't leave
    a job silently stuck `running` forever (the next pass's claim query would
    just never see it again; an operational concern for later, not solved here).

    `kind='repair'` (ADR-0076) runs `run_card_repair` instead of the pipeline;
    it owns the `CardRepair`/`Card` writes, this function only sets the
    `GenerationJob` status, with the same quota-requeue / fail handling."""

    settings = get_settings()
    try:
        if kind == "repair":
            assert card_id is not None, "a repair job must carry a card_id"
            await run_card_repair(job_id, card_id, generator, embedder)
            async with session_scope() as session:
                job = await session.get(GenerationJob, job_id)
                assert job is not None
                job.status = "completed"
                job.completed_at = datetime.now(UTC)
                job.attempts += 1
                job.last_error = None
            logger.info("repair job %s completed (card=%s)", job_id, card_id)
            return

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
        # ADR-0028: not a bug, an expected ceiling. Requeue rather than fail --
        # run_generation_pipeline is idempotent (ADR-0026), so the next cron
        # pass just picks up wherever this one stopped, instead of the topic
        # being stuck "failed" forever next to jobs that failed for a real
        # reason.
        #
        # WHEN that next pass can usefully run differs by subclass (ADR-0065),
        # and the requeue is identical either way -- so the distinction is
        # recorded rather than acted on. It is the difference between "come back
        # after midnight" and "come back in a few minutes", and writing the
        # wrong one into `last_error` is how a run that stopped on a provider
        # outage gets read, hours later, as having exhausted the day's budget.
        cause = _QUOTA_PAUSE_CAUSE.get(type(exc), "quota unavailable")
        logger.info("job %s paused: %s (topic=%s): %s", job_id, cause, topic_id, exc)
        async with session_scope() as session:
            job = await session.get(GenerationJob, job_id)
            if job is not None:
                job.status = "pending"
                job.attempts += 1
                job.last_error = f"{cause}, requeued: {exc}"[:2000]
    except Exception as exc:
        logger.exception("job %s failed (topic=%s)", job_id, topic_id)
        async with session_scope() as session:
            job = await session.get(GenerationJob, job_id)
            if job is not None:
                job.status = "failed"
                job.attempts += 1
                job.last_error = str(exc)[:2000]


async def run_once() -> int:
    """Claim as many pending jobs as the key pool holds boxes, highest priority
    first, then run them CONCURRENTLY (ADR-0082) with per-job isolation.

    Returns the number of jobs processed (attempted, not necessarily succeeded —
    see each job's own `status`/`last_error` for outcome).
    """

    settings = get_settings()
    # The pool size is logged every pass because the box arithmetic is only as
    # good as it: a key silently dropped between `.env` and this process shows
    # up downstream as fewer topics running and reads like a quota problem
    # rather than a config one (the same confusion ADR-0058 fixed for 429s).
    logger.info(
        "worker pass starting (generator=%s, %d key(s), box=%d, up to %d topic(s) at once)",
        settings.generator,
        settings.gemini_pool_size,
        settings.topic_key_box_size,
        settings.max_concurrent_topics,
    )

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
                    # As many jobs as there are whole key boxes (ADR-0082) --
                    # never more than `generation_batch_size`, which stays the
                    # outer bound on how much of the queue one pass may touch.
                    # Claiming exactly what will run is what keeps this simple:
                    # there is no admit-then-demote step, so a row is `running`
                    # only if a box is about to be handed to it.
                    .limit(min(settings.generation_batch_size, settings.max_concurrent_topics))
                    # Two passes that overlap -- `--watch` lapping itself, a cron
                    # pass landing on a slow one, or a second replica -- must not
                    # both dispatch the same `pending` rows: that is duplicate
                    # generation billed twice against the quota ADR-0028 protects.
                    # Plain `FOR UPDATE` (not SKIP LOCKED): this claim txn is
                    # short -- lock the rows, set `status='running'`, commit; the
                    # generation itself runs in separate txns after this `with`
                    # block closes. So a second overlapping pass blocks for those
                    # few milliseconds, then its own `WHERE status='pending'`
                    # re-reads and finds these rows `running` -- nothing new to
                    # claim, no double-dispatch. SKIP LOCKED was dropped because
                    # on CockroachDB it also skips a freshly-committed, unlocked
                    # row whose write intent has not yet resolved (0016 spike),
                    # silently under-claiming; plain `FOR UPDATE` waits for that
                    # intent instead. Standard on Postgres too.
                    .with_for_update()
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
        claimed = [(job.id, job.topic_id, job.kind, job.card_id) for job in pending]
        for job in pending:
            job.status = "running"

    generator = get_content_generator()
    embedder = get_embedder()

    # Concurrent, in claim order (ADR-0082): the claimed topics generate
    # together, each on its own session and its own key box. One shared
    # `generator` is what makes the boxes disjoint -- two generators would each
    # hand out the same key indices. `_run_job` swallows its own exceptions, so
    # one failure never aborts the gather.
    await asyncio.gather(
        *(
            _run_job(job_id, topic_id, kind, card_id, generator, embedder)
            for job_id, topic_id, kind, card_id in claimed
        )
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
