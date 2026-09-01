"""Worker entrypoint: `python -m spoin.worker`.

**One batch pass, then exit.** ADR-0003 §3: at free-tier quota a persistent pool
has nothing to do 99% of the time, and free hosting tiers sleep idle services
anyway. So this runs on a GitHub Actions cron (~every 15 min): claim pending jobs,
spend that slice of quota, exit. That also paces the daily quota across the day
instead of exhausting it by 9am.

The same job functions run as a persistent loop once we are paying — a different
entrypoint over identical code, which is what "no accommodation may require a
rewrite to undo" means in practice.

**Jobs run CONCURRENTLY, packed by key budget (ADR-0078, supersedes ADR-0073).**
A pass claims a batch of pending jobs (`generation_batch_size`) in
priority-then-`created_at` order and marks them `running`, then (ADR-0081)
**generates a curriculum for every claimed fresh topic** -- bounded by
`curriculum_concurrency` -- so admission sees a real `N` instead of a guess.
Only THEN does it admit them in claim order while their key demand fits the
pool: each topic wants `N` keys, where `N` is the most subtopics in any one of
its difficulty tiers (a topic still without a curriculum -- its phase hit quota
-- falls back to the provisional `settings.default_topic_key_budget`).
Admission stops adding a job once `sum(N) > pool_size`, skipping past one that
would overflow to try smaller ones behind it; jobs left unadmitted are demoted
back to `pending` for the next pass. The
admitted set runs together via `asyncio.gather`, each job on its OWN DB session,
one shared `ContentGenerator` so a single `KeyClaimRegistry` governs every
lease plus the shared reserve. One job's exception marks only that job
`failed`/`pending`; failure isolation is per-job. Within a run the pipeline's
LangGraph concurrency (ADR-0024) fans out per subtopic group, each claiming a
key from its topic's lease (ADR-0074 + ADR-0078).

ADR-0073's strictly-sequential loop was chosen so progress panels finished in
request order; the owner has since asked for topic-level parallelism against a
100+ key pool, which this restores (the pre-ADR-0073 `gather` shape, now with
key-budget admission in front of it).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings, get_settings
from spoin.core.db import get_engine, session_scope
from spoin.domain.models import GenerationJob, Topic
from spoin.embeddings import Embedder, get_embedder
from spoin.generation import get_content_generator
from spoin.generation.base import ContentGenerator
from spoin.generation.pipeline import run_generation_pipeline
from spoin.generation.pipeline.persistence import ensure_curriculum, topic_tier_width
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
    key_budget: int = 1,
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
                session,
                generator,
                embedder,
                settings,
                topic_ids=[topic_id],
                key_budgets={topic_id: key_budget},
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


async def _admit_by_key_budget(
    session: AsyncSession,
    pending: list[GenerationJob],
    *,
    pool_size: int,
    default_budget: int,
) -> list[tuple[GenerationJob, int]]:
    """ADR-0078's queue packer: walk `pending` in claim order and admit each job
    while the running sum of key demand fits `pool_size`, skipping past one that
    would overflow so smaller jobs behind it still get a turn.

    `pool_size < 1` (no real key pool -- the `fake` backend, most tests) means
    "no packing": admit everything with a nominal budget of 1.

    Repair jobs (ADR-0076) take no key lease, so they always admit and cost 0.
    """

    admitted: list[tuple[GenerationJob, int]] = []
    if pool_size < 1:
        return [(job, 1) for job in pending]

    running = 0
    for job in pending:
        if job.kind == "repair":
            admitted.append((job, 0))
            continue
        width = await topic_tier_width(session, job.topic_id)
        want = max(1, min(pool_size, width if width is not None else default_budget))
        if running + want > pool_size:
            logger.info(
                "worker: job %s (topic=%s) wants %d key(s), %d/%d already committed -- "
                "deferring to the next pass",
                job.id,
                job.topic_id,
                want,
                running,
                pool_size,
            )
            continue
        running += want
        admitted.append((job, want))
    return admitted


async def _ensure_curricula(
    generator: ContentGenerator, settings: Settings, topic_ids: list[uuid.UUID]
) -> None:
    """ADR-0081 curriculum phase: give every fresh topic a curriculum BEFORE
    key-budget admission, so `topic_tier_width` returns a real number when the
    topic is leased rather than the provisional `default_topic_key_budget` --
    which over-admits (many topics fit at budget 8) and then starves leases when
    the real widths land. One thinking-pool call per topic, bounded by
    `curriculum_concurrency`. A per-topic failure (quota, malformed response) is
    logged and left: that topic then admits at the provisional budget, exactly
    the pre-ADR-0081 path, and `resolve_and_plan_topic` still generates its
    curriculum inline as the fallback."""

    if not topic_ids:
        return
    sem = asyncio.Semaphore(max(1, settings.curriculum_concurrency))

    async def _one(topic_id: uuid.UUID) -> None:
        async with sem, session_scope() as session:
            topic = await session.get(Topic, topic_id)
            if topic is None or topic.curriculum_generated_at is not None:
                return
            try:
                draft = await ensure_curriculum(session, generator, settings, topic)
            except QuotaExhaustedError as exc:
                logger.info(
                    "curriculum phase: topic %s deferred to inline generation -- %s", topic_id, exc
                )
                return
            except Exception:
                logger.exception(
                    "curriculum phase: topic %s failed -- falls back to inline", topic_id
                )
                return
            if draft is not None:
                logger.info(
                    "curriculum phase: topic %s -- %d subtopic group(s)",
                    topic_id,
                    len(draft.subtopics),
                )

    await asyncio.gather(*(_one(topic_id) for topic_id in topic_ids))


async def run_once() -> int:
    """Claim pending jobs (highest priority first), generate any missing
    curricula (ADR-0081), admit as many as the key pool holds (ADR-0078), then
    run the admitted set concurrently with per-job isolation.

    Returns the number of jobs dispatched (attempted, not necessarily succeeded —
    see each job's own `status`/`last_error` for outcome).
    """

    settings = get_settings()
    logger.info("worker pass starting (generator=%s)", settings.generator)

    # --- Phase 1: claim, mark running, commit -------------------------------
    # Marked `running` (not just `FOR UPDATE`-locked) so an overlapping pass --
    # `--watch` lapping itself, a cron pass landing on a slow one, a second
    # replica -- cannot re-dispatch these while the curriculum phase runs. Plain
    # `FOR UPDATE`, not SKIP LOCKED: on CockroachDB SKIP LOCKED also skips a
    # freshly-committed row whose write intent hasn't resolved (0016 spike),
    # silently under-claiming. A crash between here and phase 3 leaves these
    # `running` (an operational concern for later, same as `_run_job`'s note);
    # the window is now the curriculum phase's duration, not milliseconds.
    async with session_scope() as session:
        pending = (
            (
                await session.execute(
                    select(GenerationJob)
                    .where(GenerationJob.status == "pending")
                    .order_by(GenerationJob.priority.desc(), GenerationJob.created_at)
                    .limit(settings.generation_batch_size)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if not pending:
            logger.info("nothing to do")
            return 0
        claimed_rows = [(job.id, job.topic_id, job.kind, job.card_id) for job in pending]
        for job in pending:
            job.status = "running"

    generator = get_content_generator()

    # --- Phase 2: curriculum for every fresh non-repair topic (ADR-0081) ----
    await _ensure_curricula(
        generator,
        settings,
        [topic_id for _job_id, topic_id, kind, _card_id in claimed_rows if kind != "repair"],
    )

    # --- Phase 3: admit by key budget, now that real tier widths are known --
    # Whatever doesn't fit is demoted back to `pending` for the next pass (it
    # was only `running` to hold it through phase 2). Re-fetched in the same
    # claim order so `_admit_by_key_budget`'s walk is unchanged (ADR-0078).
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(GenerationJob)
                    .where(GenerationJob.id.in_([job_id for job_id, *_ in claimed_rows]))
                    .order_by(GenerationJob.priority.desc(), GenerationJob.created_at)
                )
            )
            .scalars()
            .all()
        )
        admitted = await _admit_by_key_budget(
            session,
            list(rows),
            pool_size=settings.gemini_pool_size,
            default_budget=settings.default_topic_key_budget,
        )
        admitted_ids = {job.id for job, _budget in admitted}
        for job in rows:
            if job.id not in admitted_ids:
                job.status = "pending"
        claimed = [
            (job.id, job.topic_id, job.kind, job.card_id, budget) for job, budget in admitted
        ]

    if not claimed:
        logger.info("worker: nothing fits the key pool this pass -- all deferred")
        return 0

    embedder = get_embedder()

    # Concurrent, in claim order (ADR-0078): the admitted topics all generate
    # together, each on its own session and its own key lease. `_run_job`
    # swallows its own exceptions, so one failure never aborts the gather.
    await asyncio.gather(
        *(
            _run_job(job_id, topic_id, kind, card_id, generator, embedder, budget)
            for job_id, topic_id, kind, card_id, budget in claimed
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
