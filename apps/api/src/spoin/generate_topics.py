"""Run the generation pipeline for one or more topics from the command line.

`python -m spoin.generate_topics "Docker" "Kubernetes::Container orchestration at scale"`

Each argument is a topic. `Name::Description` sets a description; a bare `Name`
gets an empty one. This exists so the vertical slice (ADR-0024,
generation/pipeline.py) can be exercised end to end before auth, the job queue
wiring, or a real Gemini key exist — it calls the same two entrypoints a future
`GenerationJob` handler will (ADR-0025's matching, then ADR-0026's one-shot
run), in two separate transactions so a topic's identity survives even if
generation itself fails.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid

from spoin.core.config import get_settings
from spoin.core.db import get_engine, session_scope
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator
from spoin.generation.pipeline import (
    TopicRequest,
    match_and_create_topics,
    run_generation_pipeline,
)


def _parse_args(argv: list[str]) -> list[TopicRequest]:
    if not argv:
        raise SystemExit(
            'Usage: python -m spoin.generate_topics "Topic" ["Topic::Description" ...]'
        )
    requests: list[TopicRequest] = []
    for arg in argv:
        name, _, description = arg.partition("::")
        requests.append(TopicRequest(name=name.strip(), description=description.strip()))
    return requests


async def main(argv: list[str]) -> None:
    topic_requests = _parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    generator = get_content_generator()
    embedder = get_embedder()

    try:
        async with session_scope() as session:
            outcomes = await match_and_create_topics(
                session, generator, embedder, settings, topic_requests=topic_requests
            )

        # Every outcome's topic_id goes through run_generation_pipeline,
        # regardless of matched_existing -- it's designed to be a safe no-op
        # for a topic that's already fully generated (curriculum_generated_at
        # set, every subtopic at target) and to correctly resume one that
        # isn't. Gating this on matched_existing instead silently skipped
        # generation entirely for any matched topic still missing its
        # curriculum or cards -- a topic interrupted mid-run on an earlier
        # call would look "merged_into_existing" with zero cards generated,
        # not resumed, on every subsequent call.
        all_topic_ids = [uuid.UUID(outcome["topic_id"]) for outcome in outcomes]
        async with session_scope() as session:
            generation_report = await run_generation_pipeline(
                session, generator, embedder, settings, topic_ids=all_topic_ids
            )
        generated_by_id = {t["topic_id"]: t for t in generation_report["topics"]}  # type: ignore[index]

        report = {
            "topics": [generated_by_id[outcome["topic_id"]] for outcome in outcomes]
        }
        for topic_report, outcome in zip(report["topics"], outcomes, strict=True):
            topic_report["merged_into_existing"] = outcome["matched_existing"]
    finally:
        await get_engine().dispose()

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
