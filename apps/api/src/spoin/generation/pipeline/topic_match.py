"""ADR-0025's batched topic matching — the cheap, no-generation entrypoint.

Separate from the graph entirely: `match_and_create_topics` is not a node and
never runs inside one. Callers invoke it first, commit, and only then call
`run_generation_pipeline`, so a topic's identity (and any `GenerationJob` row
referencing its id) survives even if generation later fails and retries.
"""

from __future__ import annotations

import uuid

from frog.embeddings import Embedder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.models import Topic
from spoin.embeddings import normalize_topic_text
from spoin.generation.base import (
    ContentGenerator,
    TopicMatchCandidate,
    TopicMatchQuery,
    TopicMatchResult,
)
from spoin.generation.pipeline.persistence import _ensure_alias, _find_top_topic_candidates
from spoin.generation.pipeline.state import TopicMatchOutcome, TopicRequest, _slugify, logger


async def match_and_create_topics(
    session: AsyncSession,
    generator: ContentGenerator,
    embedder: Embedder,
    settings: Settings,
    *,
    topic_requests: list[TopicRequest],
) -> list[TopicMatchOutcome]:
    """ADR-0025. Embeds every incoming topic, finds each one's top-N nearest
    existing topics locally (pgvector, free), then makes ONE batched LLM call
    covering every incoming topic at once for the actual yes/no decision. No
    thresholds -- similarity scores are context for the call, never a gate
    applied by this function.

    Matched topics get aliased and nothing else happens. Unmatched topics get a
    brand-new `Topic` row -- **no curriculum, no cards yet**. Callers should
    commit this before calling `run_generation_pipeline` in a separate
    transaction, so a topic's identity outlives a failed/retried generation
    attempt (see module docstring).
    """

    if not topic_requests:
        return []

    normalized_names = [normalize_topic_text(request["name"]) for request in topic_requests]
    embeddings = await embedder.aembed(normalized_names)

    candidate_lists: list[list[tuple[Topic, float]]] = []
    queries: list[TopicMatchQuery] = []
    for index, (request, embedding) in enumerate(zip(topic_requests, embeddings, strict=True)):
        candidates = await _find_top_topic_candidates(
            session, embedding, limit=settings.topic_match_candidates
        )
        candidate_lists.append(candidates)
        queries.append(
            TopicMatchQuery(
                request_index=index,
                name=request["name"],
                description=request["description"],
                candidates=[
                    TopicMatchCandidate(
                        topic_id=str(topic.id), name=topic.canonical_name, similarity=round(sim, 4)
                    )
                    for topic, sim in candidates
                ],
            )
        )

    # Only ask the LLM about topics that have at least one candidate -- nothing
    # to possibly match against otherwise is not a judgment call, it's a fact.
    askable = [query for query in queries if query.candidates]
    verdicts_by_index: dict[int, TopicMatchResult] = {}
    if askable:
        verdict_result = await generator.match_topics(askable)
        verdicts_by_index = {verdict.request_index: verdict for verdict in verdict_result.items}

    outcomes: list[TopicMatchOutcome] = []
    for index, (request, embedding) in enumerate(zip(topic_requests, embeddings, strict=True)):
        verdict = verdicts_by_index.get(index)
        matched_topic_id = (
            uuid.UUID(verdict.matched_topic_id)
            if verdict is not None and verdict.matched_topic_id
            else None
        )
        if matched_topic_id is not None:
            topic = await session.get(Topic, matched_topic_id)
            assert topic is not None, f"match_topics returned unknown topic_id {matched_topic_id}"
            similarity = next(
                (
                    sim
                    for candidate, sim in candidate_lists[index]
                    if candidate.id == matched_topic_id
                ),
                None,
            )
            await _ensure_alias(
                session, topic, request["name"], decided_by="llm_batch_match", similarity=similarity
            )
            logger.info(
                "topic '%s': matched existing topic '%s' (id=%s, similarity=%s)",
                request["name"],
                topic.canonical_name,
                topic.id,
                similarity,
            )
            outcomes.append(
                TopicMatchOutcome(
                    topic_id=str(topic.id), topic_name=topic.canonical_name, matched_existing=True
                )
            )
        else:
            slug = _slugify(request["name"])
            existing_by_slug = await session.scalar(select(Topic).where(Topic.slug == slug))
            if existing_by_slug is not None:
                # Known gap, not fixed here: unlike the LLM-match branch above, this merge
                # has no LLM judgment behind it and doesn't call _ensure_alias, so it isn't
                # cached the way ADR-0025 commits every match decision should be. See
                # docs/tasks/0022-slug-collision-skips-alias.md.
                topic = existing_by_slug
                if topic.embedding is None:
                    topic.embedding = embedding
                logger.info(
                    "topic '%s': matched existing topic by slug '%s' (id=%s)",
                    request["name"],
                    topic.canonical_name,
                    topic.id,
                )
                outcomes.append(
                    TopicMatchOutcome(
                        topic_id=str(topic.id),
                        topic_name=topic.canonical_name,
                        matched_existing=True,
                    )
                )
            else:
                topic = Topic(
                    slug=slug,
                    canonical_name=request["name"],
                    description=request["description"],
                )
                session.add(topic)
                await session.flush()
                topic.embedding = embedding
                logger.info(
                    "topic '%s': no match, minted new topic (id=%s)", request["name"], topic.id
                )
                outcomes.append(
                    TopicMatchOutcome(
                        topic_id=str(topic.id),
                        topic_name=topic.canonical_name,
                        matched_existing=False,
                    )
                )

    await session.flush()
    return outcomes
