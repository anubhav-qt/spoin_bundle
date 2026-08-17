"""Run the generation pipeline for one or more topics from the command line.

`python -m spoin.generate_topics "Docker" "Kubernetes::Container orchestration at scale"`

Each argument is a topic. `Name::Description` sets a description; a bare `Name`
gets an empty one. This exists so the vertical slice (ADR-0024,
generation/pipeline.py) can be exercised end to end before auth, the job queue
wiring, or a real Gemini key exist — it calls `run_generation_pipeline` exactly the
way a future `GenerationJob` handler will, synchronously, once per invocation.
"""

from __future__ import annotations

import asyncio
import json
import sys

from spoin.core.config import get_settings
from spoin.core.db import get_engine, session_scope
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator
from spoin.generation.pipeline import TopicRequest, run_generation_pipeline


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
            report = await run_generation_pipeline(
                session, generator, embedder, settings, topic_requests=topic_requests
            )
    finally:
        await get_engine().dispose()

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
