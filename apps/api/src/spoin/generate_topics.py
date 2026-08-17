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
    generator = get_content_generator()
    embedder = get_embedder()

    try:
        async with session_scope() as session:
            outcomes = await match_and_create_topics(
                session, generator, embedder, settings, topic_requests=topic_requests
            )

        new_topic_ids = [
            uuid.UUID(outcome["topic_id"])
            for outcome in outcomes
            if not outcome["matched_existing"]
        ]
        async with session_scope() as session:
            generation_report = await run_generation_pipeline(
                session, generator, embedder, settings, topic_ids=new_topic_ids
            )
        generated_by_id = {t["topic_id"]: t for t in generation_report["topics"]}  # type: ignore[index]

        report = {
            "topics": [
                generated_by_id[outcome["topic_id"]]
                if not outcome["matched_existing"]
                else {
                    "topic_id": outcome["topic_id"],
                    "topic_name": outcome["topic_name"],
                    "merged_into_existing": True,
                    "accepted": 0,
                    "rejected": 0,
                    "questions_accepted": 0,
                    "questions_rejected": 0,
                }
                for outcome in outcomes
            ]
        }
        for topic_report in report["topics"]:
            topic_report.setdefault("merged_into_existing", False)
    finally:
        await get_engine().dispose()

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
