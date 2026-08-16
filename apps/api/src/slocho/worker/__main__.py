"""Worker entrypoint: `python -m slocho.worker`.

**One batch pass, then exit.** ADR-0003 §3: at free-tier quota a persistent pool
has nothing to do 99% of the time, and free hosting tiers sleep idle services
anyway. So this runs on a GitHub Actions cron (~every 15 min): claim pending jobs,
spend that slice of quota, exit. That also paces the daily quota across the day
instead of exhausting it by 9am.

The same job functions run as a persistent loop once we are paying — a different
entrypoint over identical code, which is what "no accommodation may require a
rewrite to undo" means in practice.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from slocho.core.config import get_settings
from slocho.core.db import get_engine, session_scope
from slocho.domain.models import GenerationJob

logger = logging.getLogger("slocho.worker")


async def run_once() -> int:
    """Claim and run whatever is pending, highest priority first.

    Returns the number of jobs processed.
    """

    settings = get_settings()
    logger.info("worker pass starting (generator=%s)", settings.generator)

    async with session_scope() as session:
        pending = (
            (
                await session.execute(
                    select(GenerationJob)
                    .where(GenerationJob.status == "pending")
                    # Prioritised, not FIFO (ADR-0003 §6): refilling a starved popular
                    # topic outranks one user's niche custom topic, and a
                    # demand-triggered fill outranks speculative background work. When
                    # quota runs out, low-priority work waits for tomorrow rather than
                    # everyone starving equally.
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

    # NOT YET IMPLEMENTED. The jobs themselves — curriculum pass, card generation,
    # the batch judge, question banks — are the next milestone. Deliberately not
    # stubbed with something that half-works: a worker that silently marks jobs
    # complete without generating anything is worse than one that does nothing,
    # because the queue would look healthy while the corpus stayed empty.
    logger.warning(
        "%d job(s) queued but no job handlers are implemented yet; leaving them pending",
        len(pending),
    )
    return 0


async def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        processed = await run_once()
        logger.info("worker pass finished (%d jobs)", processed)
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
