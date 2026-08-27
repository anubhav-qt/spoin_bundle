"""Scan for incomplete topics in spoin_db and execute the generation pipeline.

`python -m spoin.scan_and_generate [--limit N] [--dry-run]`

Incomplete topics include:
1. Topics with no curriculum generated (`curriculum_generated_at IS NULL`).
2. Topics with curriculum where active cards in subtopics are below target.

Prioritization:
1. Real user subscribers (`subscriber_count DESC`).
2. Seeded topics (`is_seeded DESC`).
3. Lowest completion percentage first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import get_settings
from spoin.core.db import get_engine, session_scope
from spoin.domain.models import Card, Subtopic, Topic
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator
from spoin.generation.pipeline import run_generation_pipeline
from spoin.generation.quota import DailyQuotaExhaustedError, QuotaExhaustedError

logger = logging.getLogger("spoin.scan_and_generate")


async def find_incomplete_topics(session: AsyncSession, *, limit: int = 1) -> list[dict[str, Any]]:
    """Query and return incomplete topics ordered by priority and completion deficit."""

    # 1. Unstarted topics (no curriculum generated)
    unstarted_rows = (
        (
            await session.execute(
                select(Topic)
                .where(Topic.curriculum_generated_at.is_(None))
                .order_by(Topic.subscriber_count.desc(), Topic.is_seeded.desc(), Topic.created_at)
            )
        )
        .scalars()
        .all()
    )

    candidates: list[dict[str, Any]] = []

    for t in unstarted_rows:
        candidates.append(
            {
                "topic_id": t.id,
                "name": t.canonical_name,
                "status": "unstarted",
                "curriculum_generated": False,
                "active_cards": 0,
                "target_cards": 0,
                "completion_pct": 0.0,
                "subscriber_count": t.subscriber_count,
                "is_seeded": t.is_seeded,
            }
        )

    # 2. Topics with curriculum but under-target cards
    started_rows = (
        (
            await session.execute(
                select(Topic)
                .where(Topic.curriculum_generated_at.is_not(None))
                .order_by(Topic.subscriber_count.desc(), Topic.is_seeded.desc(), Topic.created_at)
            )
        )
        .scalars()
        .all()
    )

    for t in started_rows:
        subtopics = (
            (await session.execute(select(Subtopic).where(Subtopic.topic_id == t.id)))
            .scalars()
            .all()
        )

        if not subtopics:
            candidates.append(
                {
                    "topic_id": t.id,
                    "name": t.canonical_name,
                    "status": "no_subtopics",
                    "curriculum_generated": True,
                    "active_cards": 0,
                    "target_cards": 0,
                    "completion_pct": 0.0,
                    "subscriber_count": t.subscriber_count,
                    "is_seeded": t.is_seeded,
                }
            )
            continue

        target_cards = sum(s.target_cards for s in subtopics)
        active_cards = (
            await session.execute(
                select(func.count(Card.id))
                .join(Subtopic, Card.subtopic_id == Subtopic.id)
                .where(Subtopic.topic_id == t.id, Card.status == "active")
            )
        ).scalar() or 0

        if active_cards < target_cards:
            pct = (active_cards / target_cards * 100.0) if target_cards > 0 else 100.0
            candidates.append(
                {
                    "topic_id": t.id,
                    "name": t.canonical_name,
                    "status": "under_target",
                    "curriculum_generated": True,
                    "active_cards": active_cards,
                    "target_cards": target_cards,
                    "completion_pct": round(pct, 1),
                    "subscriber_count": t.subscriber_count,
                    "is_seeded": t.is_seeded,
                }
            )

    # Sort candidates by:
    # 1. unstarted first (or 0% complete)
    # 2. subscriber count DESC
    # 3. completion_pct ASC
    candidates.sort(
        key=lambda c: (
            0 if not c["curriculum_generated"] else 1,
            -c["subscriber_count"],
            -1 if c["is_seeded"] else 0,
            c["completion_pct"],
        )
    )

    return candidates[:limit]


async def process_incomplete_topics(
    *, limit: int = 1, dry_run: bool = False
) -> list[dict[str, Any]]:
    """Scan and process incomplete topics."""
    settings = get_settings()
    generator = get_content_generator()
    embedder = get_embedder()

    async with session_scope() as session:
        candidates = await find_incomplete_topics(session, limit=limit)

    if not candidates:
        logger.info("Scan complete: No incomplete topics found in database.")
        return []

    logger.info("Found %d incomplete candidate topic(s) to process:", len(candidates))
    for c in candidates:
        logger.info(
            "  - %s (ID: %s) | Status: %s | Cards: %d/%d (%.1f%%)",
            c["name"],
            c["topic_id"],
            c["status"],
            c["active_cards"],
            c["target_cards"],
            c["completion_pct"],
        )

    if dry_run:
        logger.info("Dry-run mode enabled: skipping generation.")
        return candidates

    reports = []
    for candidate in candidates:
        topic_id = candidate["topic_id"]
        logger.info("Starting generation pipeline for topic: %s (%s)", candidate["name"], topic_id)
        try:
            async with session_scope() as session:
                generation_report = await run_generation_pipeline(
                    session,
                    generator,
                    embedder,
                    settings,
                    topic_ids=[topic_id],
                )
            logger.info("Completed generation pipeline for topic: %s", candidate["name"])
            reports.append(
                {
                    "topic": candidate["name"],
                    "topic_id": str(topic_id),
                    "status": "success",
                    "report": generation_report,
                }
            )
        except QuotaExhaustedError as exc:
            # "Pausing for tomorrow" is only true of the daily subclass
            # (ADR-0065). A throttle or a provider outage clears in minutes, and
            # a scan report that says otherwise is why a 504 storm got written up
            # as the day's budget being gone.
            resumes = (
                "Pausing for tomorrow."
                if isinstance(exc, DailyQuotaExhaustedError)
                else "Transient -- retryable well before tomorrow."
            )
            logger.warning(
                "Generation stopped on topic %s: %s. %s",
                candidate["name"],
                exc,
                resumes,
            )
            reports.append(
                {
                    "topic": candidate["name"],
                    "topic_id": str(topic_id),
                    # The status a report reader (and the run summaries built
                    # from it) keys off -- so it must not claim exhaustion for
                    # a condition that never consulted the ledger.
                    "status": (
                        "quota_exhausted"
                        if isinstance(exc, DailyQuotaExhaustedError)
                        else "generation_paused"
                    ),
                    "pause_reason": type(exc).__name__,
                    "error": str(exc),
                }
            )
            break
        except Exception as exc:
            logger.exception("Error processing topic %s: %s", candidate["name"], exc)
            reports.append(
                {
                    "topic": candidate["name"],
                    "topic_id": str(topic_id),
                    "status": "error",
                    "error": str(exc),
                }
            )

    return reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan incomplete topics and execute the generation pipeline."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Number of incomplete topics to process in this pass (default: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and list incomplete topics without running generation",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    try:
        results = await process_incomplete_topics(limit=args.limit, dry_run=args.dry_run)
        print(json.dumps(results, indent=2, default=str))
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
