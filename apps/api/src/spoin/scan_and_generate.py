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
import uuid
from typing import Any

from frog.embeddings import Embedder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings, get_settings
from spoin.core.db import get_engine, session_scope
from spoin.domain.models import Card, Subtopic, Topic
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator
from spoin.generation.base import ContentGenerator
from spoin.generation.pipeline import (
    TopicRequest,
    match_and_create_topics,
    run_generation_pipeline,
)
from spoin.generation.quota import DailyQuotaExhaustedError, QuotaExhaustedError

logger = logging.getLogger("spoin.scan_and_generate")


async def find_incomplete_topics(
    session: AsyncSession,
    *,
    limit: int = 1,
    topic_names: list[str] | None = None,
    generator: ContentGenerator | None = None,
    embedder: Embedder | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Query and return incomplete topics ordered by priority and completion deficit."""

    if topic_names:
        candidates: list[dict[str, Any]] = []
        for name in topic_names:
            clean_name = name.strip()
            if not clean_name:
                continue
            topic = (
                await session.execute(
                    select(Topic).where(func.lower(Topic.canonical_name) == clean_name.lower())
                )
            ).scalar_one_or_none()

            has_components = generator is not None and embedder is not None and settings is not None
            if topic is None and has_components:
                logger.info(
                    "Topic '%s' not in DB; minting via match_and_create_topics",
                    clean_name,
                )
                assert generator is not None and embedder is not None and settings is not None
                outcomes = await match_and_create_topics(
                    session,
                    generator,
                    embedder,
                    settings,
                    topic_requests=[TopicRequest(name=clean_name, description=clean_name)],
                )
                await session.commit()
                if outcomes:
                    topic = await session.get(Topic, uuid.UUID(outcomes[0]["topic_id"]))

            if topic is None:
                logger.warning("Topic '%s' could not be resolved or created; skipping", clean_name)
                continue

            subtopics = (
                (await session.execute(select(Subtopic).where(Subtopic.topic_id == topic.id)))
                .scalars()
                .all()
            )

            if not topic.curriculum_generated_at or not subtopics:
                candidates.append(
                    {
                        "topic_id": topic.id,
                        "name": topic.canonical_name,
                        "status": "unstarted",
                        "curriculum_generated": False,
                        "active_cards": 0,
                        "target_cards": 0,
                        "completion_pct": 0.0,
                        "subscriber_count": topic.subscriber_count,
                        "is_seeded": topic.is_seeded,
                    }
                )
            else:
                target_cards = sum(s.target_cards for s in subtopics)
                active_cards = (
                    await session.execute(
                        select(func.count(Card.id))
                        .join(Subtopic, Card.subtopic_id == Subtopic.id)
                        .where(Subtopic.topic_id == topic.id, Card.status == "active")
                    )
                ).scalar() or 0
                pct = (active_cards / target_cards * 100.0) if target_cards > 0 else 100.0
                candidates.append(
                    {
                        "topic_id": topic.id,
                        "name": topic.canonical_name,
                        "status": "completed" if active_cards >= target_cards else "under_target",
                        "curriculum_generated": True,
                        "active_cards": active_cards,
                        "target_cards": target_cards,
                        "completion_pct": round(pct, 1),
                        "subscriber_count": topic.subscriber_count,
                        "is_seeded": topic.is_seeded,
                    }
                )
        return candidates[:limit] if limit > 0 else candidates

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

    candidates = []

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


async def _process_candidate(
    candidate: dict[str, Any],
    generator: ContentGenerator,
    embedder: Embedder,
    settings: Settings,
) -> dict[str, Any]:
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
        return {
            "topic": candidate["name"],
            "topic_id": str(topic_id),
            "status": "success",
            "report": generation_report,
        }
    except QuotaExhaustedError as exc:
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
        return {
            "topic": candidate["name"],
            "topic_id": str(topic_id),
            "status": (
                "quota_exhausted"
                if isinstance(exc, DailyQuotaExhaustedError)
                else "generation_paused"
            ),
            "pause_reason": type(exc).__name__,
            "error": str(exc),
        }
    except Exception as exc:
        logger.exception("Error processing topic %s: %s", candidate["name"], exc)
        return {
            "topic": candidate["name"],
            "topic_id": str(topic_id),
            "status": "error",
            "error": str(exc),
        }


async def process_incomplete_topics(
    *,
    limit: int = 1,
    dry_run: bool = False,
    topics: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Scan and process incomplete topics concurrently up to max_concurrent_topics."""
    settings = get_settings()
    generator = get_content_generator()
    embedder = get_embedder()

    async with session_scope() as session:
        candidates = await find_incomplete_topics(
            session,
            limit=limit,
            topic_names=topics,
            generator=generator,
            embedder=embedder,
            settings=settings,
        )

    if not candidates:
        logger.info("Scan complete: No incomplete topics found in database.")
        return []

    logger.info("Found %d candidate topic(s) to process:", len(candidates))
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

    chunk_size = max(1, settings.max_concurrent_topics)
    reports: list[dict[str, Any]] = []
    for i in range(0, len(candidates), chunk_size):
        batch = candidates[i : i + chunk_size]
        logger.info(
            "Dispatching concurrent batch of %d topic(s) (chunk_size=%d, max_concurrent=%d): %s",
            len(batch),
            chunk_size,
            settings.max_concurrent_topics,
            [c["name"] for c in batch],
        )
        batch_reports = await asyncio.gather(
            *[_process_candidate(c, generator, embedder, settings) for c in batch]
        )
        reports.extend(batch_reports)
        if any(r.get("status") == "quota_exhausted" for r in batch_reports):
            logger.warning("Daily quota reached in concurrent batch; halting remaining batches.")
            break

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
    parser.add_argument(
        "--topics",
        nargs="*",
        default=None,
        help="Specific topic names to process in parallel",
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
        results = await process_incomplete_topics(
            limit=args.limit,
            dry_run=args.dry_run,
            topics=args.topics,
        )
        print(json.dumps(results, indent=2, default=str))
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
