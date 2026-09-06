"""The deterministic projection: `the_spoin_universe` curriculum tables -> `spoin_db_2`.

No model call at any step (docs/architecture/authored-curriculum.md §8). Reads the
`curriculum` / `curriculum_subtopic` rows `make curriculum-ingest` wrote, and creates or
reconciles `Topic` and `Subtopic` rows to match them:

  for each curriculum:
      upsert Topic          matched on slug(topic_name)
      for each subtopic x tier:
          upsert Subtopic   matched on (topic, title, difficulty)
                            carrying that tier's declared grounding scope
      subtopics no longer in the file are removed        (§4: plain upsert, not a merge)
  stamp topic.curriculum_corpus_version = corpus_version()

There are no users and no production content, so a dropped subtopic is dropped from the
database -- `card.subtopic_id` and `rejected_card.subtopic_id` are both
`ondelete=CASCADE`, so the child rows go with it. This is deliberate: the file is the
truth and the database follows it, which is what makes a curriculum editable by editing
the file and re-running this.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from frog.curriculum.models import Curriculum, CurriculumSubtopic
from frog.embeddings import Embedder, normalize_topic_text
from frog.retrieval import corpus_version
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import get_settings
from spoin.core.db import session_scope, universe_session_scope
from spoin.domain.enums import Difficulty
from spoin.domain.models import Subtopic, Topic, TopicAlias
from spoin.embeddings import get_embedder

logger = logging.getLogger(__name__)

#: `_SLUG_KEEP` / `_slugify` / `_min_cards` mirror
#: `spoin.generation.pipeline.state` by value -- three trivial pure functions, inlined
#: rather than imported so the projection does not depend on the generation pipeline's
#: module graph. If the canonical ones change, change these.
_SLUG_KEEP = "abcdefghijklmnopqrstuvwxyz0123456789-"


def _slugify(name: str) -> str:
    lowered = "-".join(name.strip().lower().split())
    return "".join(char for char in lowered if char in _SLUG_KEEP) or "topic"


def _min_cards(target_cards: int, fraction: float) -> int:
    return max(1, round(target_cards * fraction))


@dataclass
class ProjectionReport:
    """What one projection run did, in counts checkable against the files."""

    curricula: int = 0
    topics_created: int = 0
    topics_updated: int = 0
    subtopics_upserted: int = 0
    subtopics_removed: int = 0

    def summary(self) -> str:
        return (
            f"curricula={self.curricula} topics_created={self.topics_created} "
            f"topics_updated={self.topics_updated} "
            f"subtopics_upserted={self.subtopics_upserted} "
            f"subtopics_removed={self.subtopics_removed}"
        )


async def project_curricula(embedder: Embedder | None = None) -> ProjectionReport:
    """Project every curriculum in `the_spoin_universe` into `spoin_db_2`.

    One universe read session (read-only) and one product write session, committed
    once at the end -- the projection of a handful of curricula is small, and an
    all-or-nothing commit means a crash mid-run leaves the database on the previous
    curriculum rather than half on the new one.

    `embedder` is injectable for tests; production passes `None` and gets the
    configured one.
    """

    settings = get_settings()
    embedder = embedder or get_embedder()
    report = ProjectionReport()

    async with universe_session_scope() as universe, session_scope() as db:
        version = await corpus_version(universe)
        curricula = (
            (await universe.execute(select(Curriculum).order_by(Curriculum.topic_name)))
            .scalars()
            .all()
        )
        for curriculum in curricula:
            subtopics = (
                (
                    await universe.execute(
                        select(CurriculumSubtopic)
                        .where(CurriculumSubtopic.curriculum_id == curriculum.id)
                        .order_by(CurriculumSubtopic.ordinal)
                    )
                )
                .scalars()
                .all()
            )
            await _project_one(
                db,
                curriculum,
                list(subtopics),
                corpus_version_token=version,
                min_cards_fraction=settings.min_cards_fraction,
                embedder=embedder,
                report=report,
            )
        report.curricula = len(curricula)

    logger.info("projection: %s", report.summary())
    return report


async def _project_one(
    db: AsyncSession,
    curriculum: Curriculum,
    subtopics: list[CurriculumSubtopic],
    *,
    corpus_version_token: str,
    min_cards_fraction: float,
    embedder: Embedder,
    report: ProjectionReport,
) -> None:
    slug = _slugify(curriculum.topic_name)
    topic = await db.scalar(select(Topic).where(Topic.slug == slug))
    if topic is None:
        topic = Topic(slug=slug, canonical_name=curriculum.topic_name)
        db.add(topic)
        await db.flush()
        report.topics_created += 1
        logger.info("projection: created topic '%s'", curriculum.topic_name)
    else:
        report.topics_updated += 1

    topic.canonical_name = curriculum.topic_name
    topic.description = curriculum.description
    topic.is_survey = curriculum.is_survey
    topic.curriculum_generated_at = datetime.now(UTC)
    topic.curriculum_corpus_version = corpus_version_token

    #: The topic needs an embedding and a canonical alias to be RESOLVABLE -- ADR-0025's
    #: matching (`match_and_create_topics`, the worker, `generate_topics`) finds a topic
    #: by embedding-similarity or by an exact alias, and a projected topic that has
    #: neither cannot be routed to for generation. The embedder is local and unmetered
    #: (ADR-0097), so this stays within "the projection calls no model" in the sense
    #: that matters: no LLM, no quota, deterministic. Re-embedded every run so a renamed
    #: topic stays findable.
    (embedding,) = await embedder.aembed_passage([normalize_topic_text(curriculum.topic_name)])
    topic.embedding = embedding
    topic.embedding_model = embedder.model_name
    normalized = normalize_topic_text(curriculum.topic_name)
    if await db.scalar(select(TopicAlias).where(TopicAlias.normalized_text == normalized)) is None:
        db.add(
            TopicAlias(
                normalized_text=normalized,
                raw_text=curriculum.topic_name,
                topic_id=topic.id,
                decided_by="projection",  # `topic_alias.decided_by` is String(20)
                similarity=None,
            )
        )

    kept: set[uuid.UUID] = set()
    for position, cs in enumerate(subtopics):
        tier_plans: dict[str, Any] = cs.tiers
        #: Mirrors `resolve_and_plan_topic`: the tiers of one authored concept share a
        #: `subtopic_group_id`. Adopt an existing tier's id if one is already in the
        #: database so an edit does not fork a second group for the same concept;
        #: otherwise mint one.
        existing_by_tier: dict[str, Subtopic | None] = {}
        for tier_name in tier_plans:
            existing_by_tier[tier_name] = await db.scalar(
                select(Subtopic).where(
                    Subtopic.topic_id == topic.id,
                    Subtopic.title == cs.title,
                    Subtopic.difficulty == Difficulty(tier_name),
                )
            )

        group_id = next(
            (row.subtopic_group_id for row in existing_by_tier.values() if row is not None),
            uuid.uuid4(),
        )

        for tier_name, existing in existing_by_tier.items():
            difficulty = Difficulty(tier_name)
            plan = tier_plans[tier_name]
            target_cards = int(plan["target_cards"])
            card_types = {str(k): int(v) for k, v in dict(plan["card_types"]).items()}
            #: The tier's declared corpus scope, carried across verbatim. The
            #: projection does NOT resolve these to chunk ids: a re-ingest rebuilds a
            #: document's chunks, so ids stored here would rot silently. Retrieval
            #: resolves them late, against whatever the corpus currently holds.
            grounding = [str(ref) for ref in plan.get("grounding", [])]

            if existing is None:
                subtopic = Subtopic(
                    topic_id=topic.id,
                    title=cs.title,
                    difficulty=difficulty,
                    subtopic_group_id=group_id,
                    description="",
                    target_cards=target_cards,
                    min_cards=1,
                )
                db.add(subtopic)
            else:
                subtopic = existing

            subtopic.description = cs.description
            subtopic.target_cards = target_cards
            subtopic.min_cards = _min_cards(target_cards, min_cards_fraction)
            #: The pipeline forces `code` to 0 for non-technical topics at generation
            #: time (`nodes.py`'s `is_technical_topic`); the projection stores the
            #: authored quotas as-is.
            subtopic.card_type_quotas = card_types or None
            subtopic.grounding_refs = grounding or None
            subtopic.position = position
            await db.flush()
            kept.add(subtopic.id)
            report.subtopics_upserted += 1

    stale = (
        (
            await db.execute(
                select(Subtopic.id).where(
                    Subtopic.topic_id == topic.id,
                    Subtopic.id.notin_(kept) if kept else Subtopic.id.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if stale:
        await db.execute(delete(Subtopic).where(Subtopic.id.in_(stale)))
        report.subtopics_removed += len(stale)
        logger.info(
            "projection: removed %d subtopic(s) from '%s' no longer in the curriculum",
            len(stale),
            curriculum.topic_name,
        )
