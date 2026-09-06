"""Generate cards and questions for one or more **authored** topics.

    python -m spoin.generate_topics "Rust"
    python -m spoin.generate_topics "Rust" "Bhagavad Gita"

Each argument names a topic whose curriculum has already been authored and projected:

    docs/the_spoin_universe/curricula/<topic>/curriculum.md
        -> make curriculum-check      validate it (pure; no network, model or database)
        -> make curriculum-ingest     parse it into the_spoin_universe
        -> make curriculum-project    upsert Topic / Subtopic rows in spoin_db_2
        -> python -m spoin.generate_topics "<topic>"

**This command no longer mints a topic and no longer takes a description.** Both
belonged to the era when a topic could arrive from nowhere and have a curriculum
generated for it; curricula are authored, never generated (ADR-0007,
docs/architecture/authored-curriculum.md), so a topic exists because somebody wrote
its curriculum, and its description comes from that file. A name that resolves to
nothing is an error with the authoring steps in it, not an invitation to create
something.

ADR-0094: generation is local and manual -- one process, one log stream, one JSONL
file if the backend is `hybrid` (ADR-0090), and easy to stop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from typing import Any, cast

from frog.embeddings import normalize_topic_text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import get_settings
from spoin.core.db import get_engine, session_scope
from spoin.domain.models import Topic, TopicAlias
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator
from spoin.generation.pipeline import run_generation_pipeline

#: Mirrors `spoin.curriculum.projection._slugify`, which is what the projection names
#: a topic's row by. Kept as a resolution path so `"Rust"`, `"rust"` and `"  Rust  "`
#: all reach the same authored topic without needing an alias row for each.
_SLUG_KEEP = "abcdefghijklmnopqrstuvwxyz0123456789-"


def _slugify(name: str) -> str:
    lowered = "-".join(name.strip().lower().split())
    return "".join(char for char in lowered if char in _SLUG_KEEP) or "topic"


class TopicNotAuthoredError(RuntimeError):
    """A named topic has no projected curriculum.

    Its own type so the CLI can say what to do about it rather than printing a
    traceback: the fix is always the same three commands, and it is authoring work,
    not a bug.
    """


async def resolve_authored_topic(session: AsyncSession, name: str) -> Topic:
    """The projected topic this name refers to, or a failure that says how to make one.

    Three resolution paths, cheapest first, all deterministic -- **no model call and no
    embedding search**. ADR-0025's matching exists to decide whether a *user's* free
    text is an existing topic; this is an operator naming a topic they authored, and
    guessing at that would be a way to generate into the wrong corpus.

    1. `slug`, which is what the projection derives from `topic` in the curriculum file.
    2. `canonical_name`, exactly.
    3. `topic_alias.normalized_text` -- the projection writes one for every topic it
       creates, and ADR-0004's aliases accumulate others over time.
    """

    slug = _slugify(name)
    topic: Topic | None = await session.scalar(select(Topic).where(Topic.slug == slug))
    if topic is None:
        topic = await session.scalar(select(Topic).where(Topic.canonical_name == name.strip()))
    if topic is None:
        alias = await session.scalar(
            select(TopicAlias).where(TopicAlias.normalized_text == normalize_topic_text(name))
        )
        if alias is not None:
            topic = await session.get(Topic, alias.topic_id)

    if topic is None:
        raise TopicNotAuthoredError(
            f"no topic matches {name!r} (looked for slug {slug!r}, an exact canonical "
            f"name, and an alias).\n"
            f"  Author its curriculum at docs/the_spoin_universe/curricula/{slug}/"
            f"curriculum.md, then run:\n"
            f"    make curriculum-check && make curriculum-ingest && make curriculum-project"
        )
    if topic.curriculum_generated_at is None:
        raise TopicNotAuthoredError(
            f"topic {topic.canonical_name!r} exists but has no projected curriculum.\n"
            f"  Author docs/the_spoin_universe/curricula/{topic.slug}/curriculum.md, then run:\n"
            f"    make curriculum-check && make curriculum-ingest && make curriculum-project"
        )
    return topic


def _parse_args(argv: list[str]) -> list[str]:
    if not argv:
        raise SystemExit('Usage: python -m spoin.generate_topics "Topic" ["Another Topic" ...]')
    names = [arg.strip() for arg in argv if arg.strip()]
    if not names:
        raise SystemExit("Every argument was blank; name at least one authored topic.")
    return names


async def main(argv: list[str]) -> None:
    names = _parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    generator = get_content_generator()
    embedder = get_embedder()

    try:
        #: Resolution and generation in two transactions, as before: a topic's
        #: identity should survive a generation run that fails.
        async with session_scope() as session:
            resolved: list[tuple[str, uuid.UUID]] = []
            problems: list[str] = []
            for name in names:
                try:
                    topic = await resolve_authored_topic(session, name)
                except TopicNotAuthoredError as exc:
                    problems.append(str(exc))
                    continue
                resolved.append((topic.canonical_name, topic.id))

        #: Every name is reported at once rather than dying on the first, same
        #: discipline as `make curriculum-check`: a typo in the third argument should
        #: not be discovered one run at a time.
        if problems:
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            raise SystemExit(2)

        for canonical_name, _ in resolved:
            logging.getLogger(__name__).info("generating for authored topic '%s'", canonical_name)

        async with session_scope() as session:
            generation_report = await run_generation_pipeline(
                session,
                generator,
                embedder,
                settings,
                topic_ids=[topic_id for _, topic_id in resolved],
            )
        report = {"topics": cast(list[dict[str, Any]], generation_report["topics"])}
    finally:
        await get_engine().dispose()

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
