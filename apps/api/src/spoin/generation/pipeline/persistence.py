"""Every database read and write the pipeline performs, in one place.

These were interleaved with generation logic across the original 1955-line
module, which made the graph's actual shape hard to see: a reader tracing
"what happens to a subtopic" had to step over alias upserts, progress-row
seeding and job lookups to find it.

Nothing here calls a model. Nodes decide *what* to persist; this module knows
*how*.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty, QuestionStatus, RejectionStage, TopicEdgeKind
from spoin.domain.models import (
    Card,
    GenerationJob,
    Question,
    RejectedCard,
    Subtopic,
    Topic,
    TopicAlias,
    TopicEdge,
)
from spoin.embeddings import normalize_topic_text
from spoin.generation.base import ContentGenerator, CurriculumDraft
from spoin.generation.pipeline.state import (
    SubtopicPlan,
    _existing_title_tag,
    _min_cards,
    _Runtime,
    _slugify,
)


async def _find_top_topic_candidates(
    session: AsyncSession, embedding: list[float], *, limit: int
) -> list[tuple[Topic, float]]:
    rows = (
        await session.execute(
            select(Topic, Topic.embedding.cosine_distance(embedding).label("distance"))
            .where(Topic.embedding.is_not(None))
            .order_by("distance")
            .limit(limit)
        )
    ).all()
    return [(topic, 1.0 - distance) for topic, distance in rows]


async def _ensure_alias(
    session: AsyncSession, topic: Topic, raw_name: str, *, decided_by: str, similarity: float | None
) -> None:
    normalized = normalize_topic_text(raw_name)
    existing = await session.scalar(
        select(TopicAlias).where(TopicAlias.normalized_text == normalized)
    )
    if existing is None:
        session.add(
            TopicAlias(
                normalized_text=normalized,
                raw_text=raw_name,
                topic_id=topic.id,
                decided_by=decided_by,
                similarity=similarity,
            )
        )


async def _create_deep_dive_stubs(
    session: AsyncSession, *, parent: Topic, names: list[str]
) -> None:
    """ADR-0007: deep-dive topics are created as canonical topics immediately,
    without curricula -- those are generated lazily on first subscription."""

    for name in names:
        slug = _slugify(name)
        child = await session.scalar(select(Topic).where(Topic.slug == slug))
        if child is None:
            child = Topic(slug=slug, canonical_name=name, is_seeded=parent.is_seeded)
            session.add(child)
            await session.flush()
        edge = await session.scalar(
            select(TopicEdge).where(
                TopicEdge.from_topic_id == parent.id,
                TopicEdge.to_topic_id == child.id,
                TopicEdge.kind == TopicEdgeKind.DEEP_DIVE,
            )
        )
        if edge is None:
            session.add(
                TopicEdge(
                    from_topic_id=parent.id, to_topic_id=child.id, kind=TopicEdgeKind.DEEP_DIVE
                )
            )


async def _existing_subtopic_hints(session: AsyncSession, topic_id: uuid.UUID) -> list[str]:
    """Titles (with description) of subtopics already under THIS topic -- fed to
    `generate_curriculum` as `existing_subtopics` so the model can reuse an exact
    title verbatim when a subtopic it wants is already covered (prevention, same
    pattern already used for card titles -- see `generate_cards`'s
    `existing_titles`). Empty for a topic reaching this for the first time
    (the normal case post-ADR-0025); non-empty when `run_generation_pipeline` is
    called again for a topic that already has some subtopics from an earlier
    call -- see `generate_curriculum`'s docstring."""

    rows = (
        await session.execute(
            select(Subtopic.title, Subtopic.description)
            .where(Subtopic.topic_id == topic_id)
            .distinct()
        )
    ).all()
    return [f"{title} :: {description}" if description else title for title, description in rows]


async def _reuse_or_create_subtopic(
    session: AsyncSession, *, topic_id: uuid.UUID, title: str, difficulty: Difficulty
) -> tuple[Subtopic, bool]:
    """Exact title+difficulty match only -- the curriculum call is trusted to have
    already reused an existing title verbatim where it judged that appropriate
    (see `_existing_subtopic_hints`); this is just the mechanical lookup that
    honors that decision. Returns (row, was_reused)."""

    existing = await session.scalar(
        select(Subtopic).where(
            Subtopic.topic_id == topic_id,
            Subtopic.title == title,
            Subtopic.difficulty == difficulty,
        )
    )
    if existing is not None:
        return existing, True
    subtopic = Subtopic(
        topic_id=topic_id,
        title=title,
        difficulty=difficulty,
        description="",
        target_cards=5,
        min_cards=1,
    )
    session.add(subtopic)
    await session.flush()
    return subtopic, False


async def ensure_curriculum(
    session: AsyncSession,
    generator: ContentGenerator,
    settings: Settings,
    topic: Topic,
) -> CurriculumDraft | None:
    """Generate and persist `topic`'s curriculum if it has none, and COMMIT it.

    Idempotent: returns `None` immediately when `topic.curriculum_generated_at`
    is already set. Extracted from `resolve_and_plan_topic` (ADR-0081) so the
    worker can run it as a phase BEFORE key-budget admission -- once the
    subtopic rows exist, `topic_tier_width` returns a real number and the topic
    gets a real key lease instead of the provisional `default_topic_key_budget`.

    The caller owns concurrency control: `resolve_and_plan_topic` holds
    `topic_plan_lock` around this (its session is shared across `Send` branches);
    the worker's curriculum phase calls it once per topic on that topic's own
    session, so no lock is needed there.
    """

    if topic.curriculum_generated_at is not None:
        return None

    existing_hints = await _existing_subtopic_hints(session, topic.id)
    draft = await generator.generate_curriculum(
        topic.canonical_name, topic.description or "", existing_hints or None
    )
    topic.is_survey = draft.is_survey
    await _create_deep_dive_stubs(session, parent=topic, names=draft.deep_dive_topics)
    for group in draft.subtopics:
        tier_rows = [
            (
                *(
                    await _reuse_or_create_subtopic(
                        session,
                        topic_id=topic.id,
                        title=group.title,
                        difficulty=tier.difficulty,
                    )
                ),
                tier,
            )
            for tier in group.tiers
        ]
        # A new group adopts an EXISTING subtopic's group id if any of its tiers
        # reused one -- keeps that concept's prior tier siblings connected to the
        # new tiers landing alongside it. A reused row's OWN group id is never
        # overwritten.
        group_id = next((row[0].subtopic_group_id for row in tier_rows if row[1]), uuid.uuid4())
        for subtopic, reused, tier in tier_rows:
            if not reused:
                subtopic.subtopic_group_id = group_id
            subtopic.description = tier.description
            subtopic.target_cards = tier.target_cards
            subtopic.card_type_quotas = tier.card_type_quotas or None
            subtopic.min_cards = _min_cards(tier.target_cards, settings.min_cards_fraction)
            subtopic.position = group.position
    topic.curriculum_generated_at = datetime.now(UTC)
    await session.flush()
    await session.commit()
    return draft


async def topic_tier_width(session: AsyncSession, topic_id: uuid.UUID) -> int | None:
    """The topic's key budget (ADR-0078): the largest number of subtopics in any
    one difficulty tier -- the widest a single tier can ever fan out, and
    therefore how many keys the topic can actually keep busy at once.

    `None` when the topic has no curriculum yet (no subtopic rows): the caller
    falls back to `settings.default_topic_key_budget` and the real width is
    computed once `resolve_and_plan_topic` has persisted the curriculum.
    """

    rows = (
        (
            await session.execute(
                select(func.count())
                .select_from(Subtopic)
                .where(Subtopic.topic_id == topic_id)
                .group_by(Subtopic.difficulty)
            )
        )
        .scalars()
        .all()
    )
    return max(rows) if rows else None


async def topic_used_ascii_ids(session: AsyncSession, topic_id: uuid.UUID) -> set[str]:
    """Every curated-library entry id already used by an ASCII card in this
    topic (ADR-0080), from active cards (`Card.visual_slots['src_id']`) and from
    rejected drafts (`RejectedCard.gen_meta['src_id']` -- stamped there because
    `RejectedCard` has no `visual_slots` column). The fetcher passes these to
    `top_candidates` as `exclude_ids` so one library scene is used at most once
    per topic, for the topic's whole life across every worker pass.
    """

    active = (
        await session.execute(
            select(Card.visual_slots["src_id"].astext).where(
                Card.topic_id == topic_id,
                Card.status == CardStatus.ACTIVE,
                Card.visual_slots["src_id"].astext.is_not(None),
            )
        )
    ).scalars().all()
    rejected = (
        await session.execute(
            select(RejectedCard.gen_meta["src_id"].astext).where(
                RejectedCard.topic_id == topic_id,
                RejectedCard.gen_meta["src_id"].astext.is_not(None),
            )
        )
    ).scalars().all()
    return {value for value in (*active, *rejected) if value}


async def _load_subtopic_plans(
    session: AsyncSession,
    topic: Topic,
    *,
    max_duplicate_feedback_bodies: int,
    max_verification_feedback_bodies: int,
    max_existing_question_stems: int,
) -> list[SubtopicPlan]:
    subtopics = (
        (await session.execute(select(Subtopic).where(Subtopic.topic_id == topic.id)))
        .scalars()
        .all()
    )

    plans: list[SubtopicPlan] = []
    for subtopic in subtopics:
        existing = (
            await session.execute(
                select(Card.canonical_title, Card.title, Card.difficulty)
                .join(Subtopic, Subtopic.id == Card.subtopic_id)
                .where(
                    Subtopic.subtopic_group_id == subtopic.subtopic_group_id,
                    Card.status == CardStatus.ACTIVE,
                )
            )
        ).all()
        this_subtopic_count = sum(1 for _, _, d in existing if d == subtopic.difficulty)
        # Subtopic-scoped, not group-scoped -- matches where the near-dup
        # check itself is scoped (generation/dedup.py's find_corpus_duplicate).
        avoid_bodies = (
            (
                await session.execute(
                    select(RejectedCard.body)
                    .where(
                        RejectedCard.subtopic_id == subtopic.id,
                        RejectedCard.stage == RejectionStage.NEAR_DUPLICATE,
                    )
                    .order_by(RejectedCard.created_at.desc())
                    .limit(max_duplicate_feedback_bodies)
                )
            )
            .scalars()
            .all()
        )
        rejection_feedback_rows = (
            await session.execute(
                select(RejectedCard.body, RejectedCard.reason)
                .where(
                    RejectedCard.subtopic_id == subtopic.id,
                    # Both stages carry a judged reason worth showing the writer
                    # (unlike NEAR_DUPLICATE above, which is a body-similarity
                    # match with nothing to explain) -- STRUCTURAL was persisted
                    # but never fed back until this was added, so a tier that
                    # keeps failing structural checks looked identical to one
                    # never rejected at all, on every rerun.
                    RejectedCard.stage.in_(
                        [RejectionStage.STRUCTURAL, RejectionStage.VERIFICATION]
                    ),
                )
                .order_by(RejectedCard.created_at.desc())
                .limit(max_verification_feedback_bodies)
            )
        ).all()
        missing_question_cards = await load_cards_missing_questions(
            session, subtopic_id=subtopic.id
        )
        existing_question_stems = await _current_question_stems(
            session,
            subtopic_id=subtopic.id,
            max_existing_question_stems=max_existing_question_stems,
        )
        # Subtopic-scoped (not group-wide, unlike `existing` above) -- a hero
        # is one-per-subtopic-tier, matching `CardDraft.is_hero`'s scope.
        has_hero = (
            await session.execute(
                select(Card.id)
                .where(
                    Card.subtopic_id == subtopic.id,
                    Card.status == CardStatus.ACTIVE,
                    Card.is_hero.is_(True),
                )
                .limit(1)
            )
        ).first() is not None
        plans.append(
            SubtopicPlan(
                topic_id=str(topic.id),
                topic_name=topic.canonical_name,
                subtopic_id=str(subtopic.id),
                subtopic_group_id=str(subtopic.subtopic_group_id),
                difficulty=subtopic.difficulty.value,
                title=subtopic.title,
                description=subtopic.description,
                target_cards=subtopic.target_cards,
                card_type_quotas=subtopic.card_type_quotas or {},
                existing_titles=[_existing_title_tag(c, t, d) for c, t, d in existing],
                existing_count=this_subtopic_count,
                avoid_duplicate_bodies=list(avoid_bodies),
                rejection_feedback=[
                    {"body": body, "reason": reason} for body, reason in rejection_feedback_rows
                ],
                cards_missing_questions=[
                    {"card_id": str(card_id), "title": title, "body": body}
                    for card_id, title, body in missing_question_cards
                ],
                existing_question_stems=list(existing_question_stems),
                has_hero=has_hero,
                # Placeholder -- overwritten by the budget pass below.
                target_questions=0,
            )
        )

    # Dynamic question budget: spread 200-300 questions across all subtopic-
    # tiers proportional to each tier's `target_cards`. This caps the total
    # regardless of how many subtopics the curriculum produced, without
    # starving any single tier (floor of 1 per tier).
    topic_question_min = 200
    topic_question_max = 300
    total_target_cards = sum(p["target_cards"] for p in plans)
    if total_target_cards > 0 and plans:
        # Choose a budget: clamp the sum of target_cards to the 200-300 band.
        topic_question_budget = max(topic_question_min, min(topic_question_max, total_target_cards))
        for plan in plans:
            plan["target_questions"] = max(
                1,
                round(topic_question_budget * plan["target_cards"] / total_target_cards),
            )
    return plans


async def load_cards_missing_questions(
    session: AsyncSession, *, subtopic_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, str]]:
    """Active cards under one subtopic-tier that have no `Question` row yet.

    Called twice for different reasons, which is why it is shared rather than
    inlined: once by `_load_subtopic_plans` at the start of a run (a prior run
    persisted cards and was interrupted before writing their questions), and
    once by the topic-wide question phase (ADR-0074), where after the card phase
    this is simply "everything that needs a question" -- cards written moments
    ago and older stragglers alike, told apart by the caller from the ids the
    card phase reported.
    """

    rows = (
        await session.execute(
            select(Card.id, Card.title, Card.body)
            .outerjoin(Question, Question.card_id == Card.id)
            .where(
                Card.subtopic_id == subtopic_id,
                Card.status == CardStatus.ACTIVE,
                Question.id.is_(None),
            )
        )
    ).all()
    return [(card_id, title, body) for card_id, title, body in rows]


async def _current_question_stems(
    session: AsyncSession,
    *,
    subtopic_id: uuid.UUID,
    max_existing_question_stems: int,
) -> list[str]:
    """Factored out of `_load_subtopic_plans` so `generate_subtopic_cards`'s
    redraft loop (nodes.py's `_redraft_until_bar`) can re-query it mid-run --
    a redraft round writes its own Question rows via `_gate_and_persist_results`,
    and the NEXT redraft round for that same tier needs to see them, not just
    whatever existed when `_load_subtopic_plans` ran at the start of this run."""

    return list(
        (
            await session.execute(
                select(Question.stem)
                .where(
                    Question.subtopic_id == subtopic_id,
                    Question.status == QuestionStatus.ACTIVE,
                )
                .order_by(Question.created_at.desc())
                .limit(max_existing_question_stems)
            )
        )
        .scalars()
        .all()
    )


async def _recent_rejection_context(
    session: AsyncSession,
    *,
    subtopic_id: uuid.UUID,
    max_duplicate_feedback_bodies: int,
    max_verification_feedback_bodies: int,
) -> tuple[list[str], list[tuple[str, str]]]:
    """The same two queries `_load_subtopic_plans` runs once at the top of a
    run, callable again mid-run. `generate_subtopic_cards`'s redraft loop
    (nodes.py) needs a subtopic-tier's own just-persisted rejections as
    feedback for its next round -- those rows didn't exist yet when
    `_load_subtopic_plans` ran at the start of THIS run, so re-querying is
    the only way a redraft round sees them (this is what makes the feedback
    genuinely same-run, not just carried over from an earlier invocation)."""

    avoid_bodies = (
        (
            await session.execute(
                select(RejectedCard.body)
                .where(
                    RejectedCard.subtopic_id == subtopic_id,
                    RejectedCard.stage == RejectionStage.NEAR_DUPLICATE,
                )
                .order_by(RejectedCard.created_at.desc())
                .limit(max_duplicate_feedback_bodies)
            )
        )
        .scalars()
        .all()
    )
    rejection_feedback_rows = (
        await session.execute(
            select(RejectedCard.body, RejectedCard.reason)
            .where(
                RejectedCard.subtopic_id == subtopic_id,
                # Same STRUCTURAL+VERIFICATION pairing as _load_subtopic_plans --
                # see that query's comment.
                RejectedCard.stage.in_([RejectionStage.STRUCTURAL, RejectionStage.VERIFICATION]),
            )
            .order_by(RejectedCard.created_at.desc())
            .limit(max_verification_feedback_bodies)
        )
    ).all()
    return list(avoid_bodies), [(body, reason) for body, reason in rejection_feedback_rows]


async def _running_job(runtime: _Runtime, topic_id: uuid.UUID) -> GenerationJob | None:
    job: GenerationJob | None = await runtime.session.scalar(
        select(GenerationJob).where(
            GenerationJob.topic_id == topic_id, GenerationJob.status == "running"
        )
    )
    return job


async def _seed_progress(
    runtime: _Runtime, topic_id: uuid.UUID, topic_name: str, subtopic_plans: list[SubtopicPlan]
) -> None:
    """Called once per topic, right after this run's subtopic-tier plans are
    loaded (whether or not curriculum generation ran THIS call -- a resumed
    topic already has one). `cards_done`/`questions_done` start from what's
    already active from a prior run, not zero, so a resumed job's bars don't
    visibly regress."""

    job = await _running_job(runtime, topic_id)
    if job is None:
        return
    job.progress = {
        "stage": "cards",
        "topic_name": topic_name,
        "subtopics": [
            {
                "subtopic_id": sp["subtopic_id"],
                "group_title": sp["title"],
                "difficulty": sp["difficulty"],
                "cards_target": sp["target_cards"],
                "cards_done": sp["existing_count"],
                "questions_target": sp["target_questions"],
                "questions_done": sp["existing_count"] - len(sp["cards_missing_questions"]),
            }
            for sp in subtopic_plans
        ],
    }


async def _update_subtopic_progress(
    runtime: _Runtime, topic_id: uuid.UUID, subtopic_id: str, **fields: object
) -> None:
    job = await _running_job(runtime, topic_id)
    if job is None or not job.progress:
        return
    progress = dict(job.progress)
    raw_subtopics = cast("list[dict[str, object]]", progress.get("subtopics", []))
    subtopics = [dict(entry) for entry in raw_subtopics]
    for entry in subtopics:
        if entry.get("subtopic_id") == subtopic_id:
            entry.update(fields)
            break
    progress["subtopics"] = subtopics
    job.progress = progress


async def _mark_progress_done(runtime: _Runtime, topic_id: uuid.UUID) -> None:
    job = await _running_job(runtime, topic_id)
    if job is None:
        return
    progress = dict(job.progress or {})
    progress["stage"] = "done"
    job.progress = progress
