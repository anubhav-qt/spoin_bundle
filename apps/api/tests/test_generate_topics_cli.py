"""The CLI resolves an AUTHORED topic; it never mints one.

Curricula are authored and projected (ADR-0007), so `python -m spoin.generate_topics
"Rust"` is an operator naming a topic they wrote. The resolution below is deliberately
deterministic -- no embedding search, no `match_topics` call -- because guessing at
which topic an operator meant is a way to generate into the wrong corpus.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import project_fake_curriculum
from spoin.core.config import Settings
from spoin.domain.models import Topic, TopicAlias
from spoin.generate_topics import (
    TopicNotAuthoredError,
    _parse_args,
    resolve_authored_topic,
)


async def _authored(session: AsyncSession, settings: Settings, name: str) -> Topic:
    topic = Topic(slug=name.lower().replace(" ", "-"), canonical_name=name)
    session.add(topic)
    await session.flush()
    await project_fake_curriculum(session, topic, settings)
    return topic


@pytest.mark.asyncio
async def test_resolves_by_slug_case_and_whitespace_insensitively(
    session: AsyncSession, settings: Settings
) -> None:
    topic = await _authored(session, settings, "Rust")
    for spelling in ("Rust", "rust", "  RUST  "):
        assert (await resolve_authored_topic(session, spelling)).id == topic.id


@pytest.mark.asyncio
async def test_resolves_through_the_alias_the_projection_writes(
    session: AsyncSession, settings: Settings
) -> None:
    topic = await _authored(session, settings, "Bhagavad Gita")
    session.add(
        TopicAlias(
            normalized_text="gita",
            raw_text="Gita",
            topic_id=topic.id,
            decided_by="projection",
        )
    )
    await session.flush()
    assert (await resolve_authored_topic(session, "Gita")).id == topic.id


@pytest.mark.asyncio
async def test_an_unknown_name_names_the_authoring_steps(
    session: AsyncSession, settings: Settings
) -> None:
    """The failure is authoring work, not a bug -- so it says which three commands
    produce the thing that is missing, rather than printing a traceback."""

    with pytest.raises(TopicNotAuthoredError) as caught:
        await resolve_authored_topic(session, "Underwater Basket Weaving")
    message = str(caught.value)
    assert "curricula/underwater-basket-weaving/curriculum.md" in message
    assert "make curriculum-check" in message
    assert "make curriculum-project" in message


@pytest.mark.asyncio
async def test_a_topic_without_a_projected_curriculum_is_refused(
    session: AsyncSession, settings: Settings
) -> None:
    """A `Topic` row is not enough. Nothing is generated for a topic whose curriculum
    nobody authored -- that is the strictest reading of "the universe is the substrate",
    and it is the one the owner chose."""

    session.add(Topic(slug=f"stub-{uuid.uuid4().hex[:6]}", canonical_name="Stub Topic"))
    await session.flush()
    with pytest.raises(TopicNotAuthoredError, match="no projected curriculum"):
        await resolve_authored_topic(session, "Stub Topic")


@pytest.mark.asyncio
async def test_a_stub_becomes_resolvable_once_it_is_projected(
    session: AsyncSession, settings: Settings
) -> None:
    topic = Topic(slug="later", canonical_name="Later")
    session.add(topic)
    await session.flush()
    with pytest.raises(TopicNotAuthoredError):
        await resolve_authored_topic(session, "Later")

    topic.curriculum_generated_at = datetime.now(UTC)
    await session.flush()
    assert (await resolve_authored_topic(session, "Later")).id == topic.id


def test_the_cli_no_longer_accepts_a_description() -> None:
    """`Name::Description` used to mint a topic with that description. A topic's
    description now comes from its curriculum file, so the separator is just part of
    the name -- and a name containing it will fail to resolve, loudly."""

    assert _parse_args(["Rust", "  Bhagavad Gita  "]) == ["Rust", "Bhagavad Gita"]
    assert _parse_args(["Rust::something"]) == ["Rust::something"]


def test_no_arguments_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        _parse_args([])
