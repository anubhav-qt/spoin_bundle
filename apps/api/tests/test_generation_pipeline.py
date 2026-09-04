"""End-to-end tests for the LangGraph generation pipeline (ADR-0024/0025/0026).

Uses the real `session` fixture (Postgres + pgvector, skipped if unavailable) since
topic matching needs real cosine-distance queries — a `FakeContentGenerator` stands
in for the LLM, so no network/quota is involved.
"""

from __future__ import annotations

import uuid
from typing import cast

from frog.embeddings import HashEmbedder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty, RejectionStage
from spoin.domain.models import Card, Question, RejectedCard, Subtopic, Topic, TopicAlias
from spoin.generation.base import (
    AsciiFetchQuery,
    AsciiFetchResult,
    BatchResult,
    CardVerificationResult,
    ContentGenerator,
)
from spoin.generation.fake import FakeContentGenerator
from spoin.generation.pipeline import (
    TopicRequest,
    match_and_create_topics,
    run_generation_pipeline,
)
from spoin.generation.pipeline.persistence import (
    _load_subtopic_plans,
    _recent_rejection_context,
)
from spoin.generation.pipeline.state import CARD_PROMPT_VERSION


async def _plan_and_generate(
    session: AsyncSession,
    settings: Settings,
    *names: str,
    generator: ContentGenerator | None = None,
) -> dict[str, object]:
    """Test convenience: run both phases in one (transaction-per-call semantics
    don't matter for these tests — only production's worker/CLI care about
    committing between them, see pipeline.py's module docstring)."""

    generator = generator if generator is not None else FakeContentGenerator()
    embedder = HashEmbedder(settings.embedding_dim)
    requests = [TopicRequest(name=name, description="") for name in names]

    outcomes = await match_and_create_topics(
        session, generator, embedder, settings, topic_requests=requests
    )
    new_topic_ids = [
        uuid.UUID(outcome["topic_id"]) for outcome in outcomes if not outcome["matched_existing"]
    ]
    generation_report = await run_generation_pipeline(
        session, generator, embedder, settings, topic_ids=new_topic_ids
    )
    generated_by_id = {t["topic_id"]: t for t in generation_report["topics"]}  # type: ignore[index]

    topics = []
    for outcome in outcomes:
        if outcome["matched_existing"]:
            topics.append(
                {
                    "topic_id": outcome["topic_id"],
                    "topic_name": outcome["topic_name"],
                    "merged_into_existing": True,
                    "accepted": 0,
                    "rejected": 0,
                }
            )
        else:
            report = dict(generated_by_id[outcome["topic_id"]])
            report["merged_into_existing"] = False
            topics.append(report)
    return {"topics": topics}


async def test_fresh_topic_generates_cards_dual_titles_and_questions(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _plan_and_generate(session, settings, "Photosynthesis")
    (topic_report,) = report["topics"]

    assert topic_report["merged_into_existing"] is False
    assert topic_report["accepted"] > 0
    assert topic_report["rejected"] == 0
    assert topic_report["questions_accepted"] > 0

    cards = (
        (await session.execute(select(Card).where(Card.topic_id == topic_report["topic_id"])))
        .scalars()
        .all()
    )
    assert len(cards) == topic_report["accepted"]
    for card in cards:
        assert card.canonical_title  # ADR-0022: always present
        assert card.status.value == "active"
        assert card.content_embedding is not None

    questions = (
        (
            await session.execute(
                select(Question)
                .join(Card, Card.id == Question.card_id)
                .where(Card.topic_id == topic_report["topic_id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(questions) == topic_report["questions_accepted"]
    for question in questions:
        assert question.card_id in {card.id for card in cards}


async def test_rerun_skips_curriculum_and_does_not_duplicate(
    session: AsyncSession, settings: Settings
) -> None:
    first = await _plan_and_generate(session, settings, "Rust Ownership")
    second = await _plan_and_generate(session, settings, "Rust Ownership")

    first_topic = first["topics"][0]
    second_topic = second["topics"][0]

    assert first_topic["merged_into_existing"] is False
    assert second_topic["merged_into_existing"] is True
    assert first_topic["topic_id"] == second_topic["topic_id"]
    # Matched onto the existing topic — no generation ran a second time.
    assert second_topic["accepted"] == 0

    subtopics = (
        (
            await session.execute(
                select(Subtopic).where(Subtopic.topic_id == first_topic["topic_id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(subtopics) > 0


async def test_independent_topics_in_one_run_do_not_cross_contaminate(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _plan_and_generate(session, settings, "Quantum Computing", "Sourdough Baking")
    names = {t["topic_name"] for t in report["topics"]}
    ids = {t["topic_id"] for t in report["topics"]}

    assert names == {"Quantum Computing", "Sourdough Baking"}
    assert len(ids) == 2  # distinct topics, neither merged into the other
    for topic_report in report["topics"]:
        assert topic_report["merged_into_existing"] is False
        assert topic_report["accepted"] > 0


async def test_min_cards_derived_from_fraction_setting(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _plan_and_generate(session, settings, "Thermodynamics")
    topic_id = report["topics"][0]["topic_id"]

    subtopics = (
        (await session.execute(select(Subtopic).where(Subtopic.topic_id == topic_id)))
        .scalars()
        .all()
    )
    for subtopic in subtopics:
        expected = max(1, round(subtopic.target_cards * settings.min_cards_fraction))
        assert subtopic.min_cards == expected


async def test_exact_repeat_name_auto_merges_via_batched_match(
    session: AsyncSession, settings: Settings
) -> None:
    await _plan_and_generate(session, settings, "Kubernetes")
    report = await _plan_and_generate(session, settings, "Kubernetes")
    topic_report = report["topics"][0]

    assert topic_report["merged_into_existing"] is True
    alias = await session.scalar(
        select(TopicAlias).where(TopicAlias.normalized_text == "kubernetes")
    )
    assert alias is not None
    assert alias.decided_by == "llm_batch_match"


async def test_unrelated_topics_do_not_auto_merge(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _plan_and_generate(session, settings, "Photosynthesis", "Rust Ownership")
    for topic_report in report["topics"]:
        assert topic_report["merged_into_existing"] is False

    topics = (await session.execute(select(Topic))).scalars().all()
    assert len(topics) == 2


async def test_first_topic_ever_skips_the_llm_call_when_no_candidates_exist(
    session: AsyncSession, settings: Settings
) -> None:
    """No existing topics at all -> nothing to possibly match -> match_topics
    is never called (ADR-0025's "not a judgment call" case)."""

    generator = FakeContentGenerator()
    embedder = HashEmbedder(settings.embedding_dim)
    calls: list[object] = []
    original = generator.match_topics

    async def _tracking_match_topics(queries):  # type: ignore[no-untyped-def]
        calls.append(queries)
        return await original(queries)

    generator.match_topics = _tracking_match_topics  # type: ignore[method-assign]

    outcomes = await match_and_create_topics(
        session,
        generator,
        embedder,
        settings,
        topic_requests=[TopicRequest(name="Brand New Topic", description="")],
    )

    assert calls == []
    assert outcomes[0]["matched_existing"] is False


async def test_verification_rejection_is_persisted_to_rejected_card(
    session: AsyncSession, settings: Settings
) -> None:
    """ADR-0030: pass 2 can reject, and a rejection is stored, never silently
    dropped."""

    generator = FakeContentGenerator(reject_one_per_verify_batch=True)
    report = await _plan_and_generate(session, settings, "Cell Biology", generator=generator)
    topic_report = report["topics"][0]

    assert topic_report["rejected"] > 0

    rejected_rows = (
        (
            await session.execute(
                select(RejectedCard).where(RejectedCard.topic_id == topic_report["topic_id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(rejected_rows) > 0
    assert all(row.stage == RejectionStage.VERIFICATION for row in rejected_rows)
    assert all(row.reason for row in rejected_rows)
    # A rejected draft never becomes an active Card, ever, for the same family.
    active_bodies = {
        card.body
        for card in (
            await session.execute(select(Card).where(Card.topic_id == topic_report["topic_id"]))
        )
        .scalars()
        .all()
    }
    assert not active_bodies & {row.body for row in rejected_rows}


class _PlanRecordingGenerator(FakeContentGenerator):
    """Records whether each `generate_cards` call arrived with briefs attached,
    so a test can assert the planning stage's output actually reaches the
    writer rather than just that the call happened (ADR-0059)."""

    def __init__(self) -> None:
        super().__init__()
        #: (want_hero, number of plans) per generate_cards call, in call order.
        self.calls: list[tuple[bool, int]] = []

    async def generate_cards(self, **kwargs: object) -> BatchResult:  # type: ignore[override]
        plans = kwargs.get("plans") or []
        self.calls.append((bool(kwargs.get("want_hero")), len(cast(list[object], plans))))
        return await super().generate_cards(**kwargs)  # type: ignore[arg-type]


async def test_planned_cards_reach_the_writer_and_are_stamped_with_the_prompt_version(
    session: AsyncSession, settings: Settings
) -> None:
    """ADR-0059: the pre-processing gate briefs every ordinary writer call, and
    everything the run persists records which prompt version produced it."""

    generator = _PlanRecordingGenerator()
    report = await _plan_and_generate(session, settings, "Plate Tectonics", generator=generator)
    topic_report = report["topics"][0]

    ordinary_calls = [count for want_hero, count in generator.calls if not want_hero]
    assert ordinary_calls, "expected at least one non-hero writer call"
    assert all(count > 0 for count in ordinary_calls), (
        "every ordinary writer call should carry briefs from the planning stage"
    )
    # The hero call is deliberately unplanned -- one card with its own framing
    # and nothing to differentiate it from (ADR-0059).
    assert all(count == 0 for want_hero, count in generator.calls if want_hero)

    cards = (
        (await session.execute(select(Card).where(Card.topic_id == topic_report["topic_id"])))
        .scalars()
        .all()
    )
    assert cards
    assert all(card.gen_meta["prompt_version"] == CARD_PROMPT_VERSION for card in cards)

    questions = (
        (
            await session.execute(
                select(Question)
                .join(Card, Card.id == Question.card_id)
                .where(Card.topic_id == topic_report["topic_id"])
            )
        )
        .scalars()
        .all()
    )
    assert all(q.gen_meta["prompt_version"] == CARD_PROMPT_VERSION for q in questions)


class _FailingPlannerGenerator(FakeContentGenerator):
    """Planning always fails. Everything downstream must still work."""

    async def plan_cards(self, **kwargs: object) -> BatchResult:  # type: ignore[override]
        return BatchResult(items=[], failures=["plan_cards call failed: simulated"])


async def test_planning_failure_falls_back_to_unplanned_generation(
    session: AsyncSession, settings: Settings
) -> None:
    """ADR-0059: planning improves what gets written, it is not a dependency of
    writing anything. A tier whose planning call dies must still produce cards --
    a lost improvement, never a lost card."""

    report = await _plan_and_generate(
        session, settings, "Volcanology", generator=_FailingPlannerGenerator()
    )
    topic_report = report["topics"][0]

    assert topic_report["accepted"] > 0
    cards = (
        (await session.execute(select(Card).where(Card.topic_id == topic_report["topic_id"])))
        .scalars()
        .all()
    )
    assert cards
    # Still v2 content: the prompt version records which pipeline wrote the
    # card, not whether that pipeline's planning call happened to succeed.
    assert all(card.gen_meta["prompt_version"] == CARD_PROMPT_VERSION for card in cards)


class _DuplicateCardsGenerator(FakeContentGenerator):
    """Forces an exact intra-batch near-duplicate: the second card in every
    `generate_cards` batch of >=2 gets the first card's body verbatim, so the
    dedup running-set check (ADR-0030) has something real to catch."""

    async def generate_cards(self, **kwargs: object) -> BatchResult:  # type: ignore[override]
        result = await super().generate_cards(**kwargs)  # type: ignore[arg-type]
        if len(result.items) >= 2:
            items = list(result.items)
            items[1] = items[1].model_copy(update={"body": items[0].body})
            result = BatchResult(items=items, failures=result.failures)
        return result


async def test_near_duplicate_cards_are_rejected_and_persisted(
    session: AsyncSession, settings: Settings
) -> None:
    report = await _plan_and_generate(
        session, settings, "Marine Biology", generator=_DuplicateCardsGenerator()
    )
    topic_report = report["topics"][0]

    assert topic_report["rejected"] > 0

    rejected_rows = (
        (
            await session.execute(
                select(RejectedCard).where(
                    RejectedCard.topic_id == topic_report["topic_id"],
                    RejectedCard.stage == RejectionStage.NEAR_DUPLICATE,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rejected_rows) > 0


class _RecordingDuplicateGenerator(FakeContentGenerator):
    """Forces exactly one intra-batch near-duplicate on its FIRST
    `generate_cards` call only (so the topic's first run produces a real
    `rejected_card` row), and records every call's `avoid_bodies` kwarg so a
    later run can be asserted to have seen it."""

    def __init__(self) -> None:
        super().__init__()
        self.avoid_bodies_seen: list[list[str]] = []
        self._forced = False

    async def generate_cards(self, **kwargs: object) -> BatchResult:  # type: ignore[override]
        self.avoid_bodies_seen.append(list(kwargs["avoid_bodies"]))  # type: ignore[arg-type]
        result = await super().generate_cards(**kwargs)  # type: ignore[arg-type]
        if not self._forced and len(result.items) >= 2:
            self._forced = True
            items = list(result.items)
            items[1] = items[1].model_copy(update={"body": items[0].body})
            result = BatchResult(items=items, failures=result.failures)
        return result


async def test_rejected_duplicate_body_feeds_forward_into_next_run(
    session: AsyncSession, settings: Settings
) -> None:
    """ADR-0030 addendum: a near-duplicate rejection is fed back as
    `avoid_bodies` on the NEXT run's `generate_cards` call for the same
    subtopic-tier, so the writer sees the actual rejected content."""

    generator = _RecordingDuplicateGenerator()
    embedder = HashEmbedder(settings.embedding_dim)
    outcomes = await match_and_create_topics(
        session,
        generator,
        embedder,
        settings,
        topic_requests=[TopicRequest(name="Ornithology", description="")],
    )
    topic_id = uuid.UUID(outcomes[0]["topic_id"])

    await run_generation_pipeline(session, generator, embedder, settings, topic_ids=[topic_id])

    rejected_rows = (
        (
            await session.execute(
                select(RejectedCard).where(
                    RejectedCard.topic_id == topic_id,
                    RejectedCard.stage == RejectionStage.NEAR_DUPLICATE,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rejected_rows) > 0
    rejected_body = rejected_rows[0].body

    calls_before = len(generator.avoid_bodies_seen)
    second_report = await run_generation_pipeline(
        session, generator, embedder, settings, topic_ids=[topic_id]
    )
    # The under-target subtopic actually got topped up in this second run.
    assert second_report["topics"][0]["accepted"] > 0  # type: ignore[index]

    calls_after = generator.avoid_bodies_seen[calls_before:]
    assert any(rejected_body in seen for seen in calls_after)


async def test_subtopic_card_type_quotas_and_diverse_archetypes(
    session: AsyncSession, settings: Settings
) -> None:
    """Predetermined quotas in curriculum ensure cards with ASCII art, comparison,
    code, diagram, and prose are generated and persisted."""
    report = await _plan_and_generate(session, settings, "Operating Systems")
    (topic_report,) = report["topics"]
    topic_id = uuid.UUID(topic_report["topic_id"])  # type: ignore[arg-type]

    subtopics = (
        (await session.execute(select(Subtopic).where(Subtopic.topic_id == topic_id)))
        .scalars()
        .all()
    )
    assert len(subtopics) > 0
    for subtopic in subtopics:
        assert subtopic.card_type_quotas is not None
        assert "ascii" in subtopic.card_type_quotas
        assert "code" in subtopic.card_type_quotas
        assert "comparison" in subtopic.card_type_quotas
        assert "diagram" in subtopic.card_type_quotas
        assert "prose" in subtopic.card_type_quotas
        assert sum(subtopic.card_type_quotas.values()) == subtopic.target_cards

    cards = (await session.execute(select(Card).where(Card.topic_id == topic_id))).scalars().all()
    assert len(cards) > 0

    has_ascii = any(card.visual_id is not None for card in cards)
    has_code = any("code" in card.archetype for card in cards)
    has_comparison = any("comparison" in card.archetype for card in cards)
    has_diagram = any("diagram" in card.archetype for card in cards)

    assert has_ascii, "Expected generated cards to include ASCII art cards"
    assert has_code, "Expected generated cards to include code cards"
    assert has_comparison, "Expected generated cards to include comparison cards"
    assert has_diagram, "Expected generated cards to include diagram cards"


class _FixedSceneGenerator(FakeContentGenerator):
    """`fetch_ascii_scenes` always picks the SAME curated id (ADR-0080), so a
    test can assert the PIPELINE -- not the model -- enforces one-use-per-topic."""

    async def fetch_ascii_scenes(
        self,
        queries: list[AsciiFetchQuery],
        *,
        topic_name: str,
        subtopic_title: str,
        difficulty: Difficulty,
        exclude_ids: frozenset[str],
    ) -> BatchResult[AsciiFetchResult]:
        items: list[AsciiFetchResult] = []
        for q in queries:
            if "art_shared" in exclude_ids:
                items.append(AsciiFetchResult(index=q.index, matched=False))
            else:
                items.append(
                    AsciiFetchResult(
                        index=q.index,
                        matched=True,
                        src_id="art_shared",
                        label="shared-scene",
                        art="  o\n /|\\\n / \\",
                        alt="a shared placeholder scene",
                    )
                )
        return BatchResult(items=items)


async def test_ascii_fetcher_scene_is_single_use_within_a_topic(
    session: AsyncSession, settings: Settings
) -> None:
    """ADR-0080: even when the fetcher would pick the same curated scene for
    every ascii card, at most one active card in the topic carries it -- the
    rest fall back to a writer-drawn scene -- and `topic_used_ascii_ids` reads
    exactly that one id back for the next pass."""

    from spoin.generation.pipeline.persistence import topic_used_ascii_ids

    report = await _plan_and_generate(
        session, settings, "Operating Systems", generator=_FixedSceneGenerator()
    )
    (topic_report,) = report["topics"]
    topic_id = uuid.UUID(topic_report["topic_id"])  # type: ignore[arg-type]

    cards = (
        (
            await session.execute(
                select(Card).where(Card.topic_id == topic_id, Card.status == CardStatus.ACTIVE)
            )
        )
        .scalars()
        .all()
    )
    shared = [c for c in cards if (c.visual_slots or {}).get("src_id") == "art_shared"]
    assert len(shared) <= 1, "a curated scene must be used at most once per topic"

    used = await topic_used_ascii_ids(session, topic_id)
    assert used <= {"art_shared"}
    if shared:
        assert used == {"art_shared"}


async def _active_count(session: AsyncSession, subtopic_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Card)
            .where(Card.subtopic_id == subtopic_id, Card.status == CardStatus.ACTIVE)
        )
        or 0
    )


async def test_second_pass_only_drafts_the_true_deficit(
    session: AsyncSession, settings: Settings
) -> None:
    """A tier under target after one run must only draft its remaining
    deficit on a second pass -- not another full `target_cards` batch on top
    of what's already active. Confirmed live 2026-08-24: a real topic
    backfilled a second time landed three subtopics at roughly DOUBLE their
    target_cards, before this fix (`generate_subtopic_cards`'s draft loop
    used to bound itself by the tier's absolute target, ignoring
    `existing_count` entirely)."""

    embedder = HashEmbedder(settings.embedding_dim)
    # Rejects exactly one card per tier's verify batch -- every tier lands at
    # target-1 (9/10 for the fake curriculum) after round 1, cleanly meeting
    # the 90% first-pass bar, so the redraft loop above does not fire and
    # every tier's true deficit going into pass two is exactly 1.
    generator = FakeContentGenerator(reject_one_per_verify_batch=True)
    first = await _plan_and_generate(session, settings, "Plate Tectonics", generator=generator)
    topic_id = uuid.UUID(first["topics"][0]["topic_id"])  # type: ignore[arg-type]

    subtopics = (
        (await session.execute(select(Subtopic).where(Subtopic.topic_id == topic_id)))
        .scalars()
        .all()
    )
    assert subtopics
    before = {s.id: await _active_count(session, s.id) for s in subtopics}
    assert all(before[s.id] < s.target_cards for s in subtopics), (
        "test setup assumption broken: every tier should be under target after round 1"
    )

    # A second pass -- "a worker picking the topic back up". Reuses the SAME
    # generator instance (not a fresh `FakeContentGenerator()`) so its
    # internal card counter keeps incrementing rather than resetting -- a
    # fresh instance would produce near-identical bodies to pass one's,
    # which the dedup gate would then legitimately reject, muddying what
    # this test is actually about.
    generator._reject_one = False
    await run_generation_pipeline(session, generator, embedder, settings, topic_ids=[topic_id])

    improved = False
    for subtopic in subtopics:
        after = await _active_count(session, subtopic.id)
        # The actual bug this guards against: before this fix, a second pass
        # drafted a WHOLE EXTRA `target_cards` batch regardless of what was
        # already active, landing real subtopics at roughly double target.
        # `after` may still land short of `target_cards` for a subtopic
        # whose one deficit card happens to collide as a near-duplicate of
        # an earlier fake card (HashEmbedder has no real semantics, and the
        # fake generator's bodies are near-boilerplate for one subtopic-tier
        # -- an artifact of this test double, not a redraft-loop failure);
        # exceeding it is never legitimate.
        assert after <= subtopic.target_cards, (
            f"subtopic {subtopic.id} ended with {after} active cards after a second pass "
            f"(target {subtopic.target_cards}, had {before[subtopic.id]} before it) -- a "
            "second pass must never draft past the tier's real target"
        )
        assert after >= before[subtopic.id]
        improved = improved or after > before[subtopic.id]
    # At least the common case (no dedup collision) must actually close a
    # real deficit, not merely fail to make things worse.
    assert improved


class _FractionRejectGenerator(FakeContentGenerator):
    """Deterministically rejects every Nth card (by index) in every
    `verify_cards` batch -- unlike `reject_one_per_verify_batch` (drops
    exactly one card total), this lands a tier meaningfully under its
    completion bar after round 1, giving the redraft loop real work to do."""

    def __init__(self, *, reject_every: int) -> None:
        super().__init__()
        self._reject_every = reject_every

    async def verify_cards(self, queries, **kwargs):  # type: ignore[no-untyped-def,override]
        return BatchResult(
            items=[
                CardVerificationResult(
                    index=query.index,
                    accepted=query.index % self._reject_every != 0,
                    confirmed_difficulty=query.requested_difficulty,
                    reason="" if query.index % self._reject_every != 0 else "simulated rejection",
                )
                for query in queries
            ]
        )


class _AlwaysRejectGenerator(FakeContentGenerator):
    """Rejects every single card in `verify_cards`, always -- proves the
    redraft loop's per-tier stuck guard actually stops it rather than
    spinning until the absolute backstop."""

    async def verify_cards(self, queries, **kwargs):  # type: ignore[no-untyped-def,override]
        return BatchResult(
            items=[
                CardVerificationResult(
                    index=query.index,
                    accepted=False,
                    confirmed_difficulty=query.requested_difficulty,
                    reason="simulated: always reject",
                )
                for query in queries
            ]
        )


async def test_redraft_loop_improves_on_a_single_round(
    session: AsyncSession, settings: Settings
) -> None:
    """Round 1 alone would land a 50%-rejected tier at half its target (5/10
    for the fake curriculum) and stop there -- the exact "completed" but
    well-under-target outcome docs/tasks/0023 documents. The redraft loop
    should close a meaningful chunk of that gap within its round budget."""

    report = await _plan_and_generate(
        session, settings, "Igneous Rocks", generator=_FractionRejectGenerator(reject_every=2)
    )
    topic_id = uuid.UUID(report["topics"][0]["topic_id"])  # type: ignore[arg-type]

    subtopics = (
        (await session.execute(select(Subtopic).where(Subtopic.topic_id == topic_id)))
        .scalars()
        .all()
    )
    assert subtopics
    for subtopic in subtopics:
        active = await _active_count(session, subtopic.id)
        # A single round with this generator accepts exactly half of
        # target_cards (5/10); the redraft loop must do meaningfully better
        # than that without ever exceeding the tier's real target.
        assert active > subtopic.target_cards // 2
        assert active <= subtopic.target_cards


async def test_a_redrafted_tier_gets_exactly_one_question_pass(
    session: AsyncSession, settings: Settings
) -> None:
    """ADR-0074's question phase runs once per subtopic-TIER, not once per item
    report -- and `_redraft_until_bar` emits one report per round, so a tier
    that needed several rounds arrives at the fan-in named several times.

    Two ways that goes wrong if the reports are not merged first, both silent:
    the tier's questions get generated repeatedly (concurrent passes racing for
    the same unquestioned cards, and real quota spent on every extra one), and
    the run's report counts the same questions once per round. This generator
    rejects half of every batch, which is what forces the redraft rounds the
    bug needs.

    The report figure and the row count must agree exactly -- that equality is
    the assertion; `> 0` alone would pass with the double-count in place.
    """

    report = await _plan_and_generate(
        session, settings, "Sedimentary Rocks", generator=_FractionRejectGenerator(reject_every=2)
    )
    topic_report = report["topics"][0]
    topic_id = uuid.UUID(topic_report["topic_id"])  # type: ignore[arg-type]

    subtopic_ids = (
        (await session.execute(select(Subtopic.id).where(Subtopic.topic_id == topic_id)))
        .scalars()
        .all()
    )
    questions = (
        (await session.execute(select(Question).where(Question.subtopic_id.in_(subtopic_ids))))
        .scalars()
        .all()
    )

    assert topic_report["questions_accepted"] > 0
    assert len(questions) == topic_report["questions_accepted"]
    # One question per card at most: a second pass over the same tier would
    # have written more questions than there are cards to ask about.
    cards = (
        (await session.execute(select(Card.id).where(Card.topic_id == topic_id))).scalars().all()
    )
    assert len({question.card_id for question in questions}) == len(questions)
    assert len(questions) <= len(cards)


async def test_redraft_loop_stuck_guard_stops_on_persistent_rejection(
    session: AsyncSession, settings: Settings
) -> None:
    """A tier the gate rejects every single time (a real, systemic content
    problem -- e.g. the missing difficulty_examples catalog, task 0011, not
    a fluke) must stop redrafting on its own rather than spending the rest
    of a day's quota on itself. This is the safety property the whole
    redraft loop depends on."""

    report = await _plan_and_generate(
        session, settings, "Metamorphic Rocks", generator=_AlwaysRejectGenerator()
    )
    topic_id = uuid.UUID(report["topics"][0]["topic_id"])  # type: ignore[arg-type]
    topic_report = report["topics"][0]

    # Every draft this run was rejected -- nothing became an active card,
    # and the run still terminated (proven simply by reaching this line).
    assert topic_report["accepted"] == 0
    assert topic_report["rejected"] > 0

    cards = (await session.execute(select(Card).where(Card.topic_id == topic_id))).scalars().all()
    assert len(cards) == 0


async def test_structural_rejection_feeds_forward_into_next_run(
    session: AsyncSession, settings: Settings
) -> None:
    """A STRUCTURAL-stage rejection carries a judged reason exactly like a
    VERIFICATION-stage one -- both belong in `rejection_feedback`, the list
    shown to the writer on a later run/redraft round. Before this fix, only
    VERIFICATION rejections were ever queried back out, so a tier that kept
    failing the cheap structural check (missing element, wrong length --
    generation/gate.py) looked, to a rerun, identical to a tier that had
    never been rejected at all. Exercises `_load_subtopic_plans` (the initial-
    round query) and `_recent_rejection_context` (the redraft loop's re-query)
    directly rather than through a full second pipeline run, since a tier
    that already cleared its completion bar on the first pass never drafts
    again and so never proves anything about what it WOULD have been shown."""

    outcomes = await _plan_and_generate(session, settings, "Volcanology")
    topic_id = uuid.UUID(outcomes["topics"][0]["topic_id"])  # type: ignore[index]

    topic = await session.get(Topic, topic_id)
    assert topic is not None
    subtopic = (
        await session.execute(select(Subtopic).where(Subtopic.topic_id == topic_id).limit(1))
    ).scalar_one()

    structural_reason = "missing a required code block for this card type"
    session.add(
        RejectedCard(
            topic_id=topic_id,
            subtopic_id=subtopic.id,
            requested_difficulty=subtopic.difficulty,
            title="Structurally broken draft",
            canonical_title="structurally broken draft",
            summary="n/a",
            body="incomplete body",
            stage=RejectionStage.STRUCTURAL,
            reason=structural_reason,
        )
    )
    await session.commit()

    plans = await _load_subtopic_plans(
        session,
        topic,
        max_duplicate_feedback_bodies=settings.max_duplicate_feedback_bodies,
        max_verification_feedback_bodies=settings.max_verification_feedback_bodies,
        max_existing_question_stems=settings.max_existing_question_stems,
    )
    plan = next(p for p in plans if p["subtopic_id"] == str(subtopic.id))
    assert any(fb["reason"] == structural_reason for fb in plan["rejection_feedback"])

    _avoid_bodies, redraft_feedback = await _recent_rejection_context(
        session,
        subtopic_id=subtopic.id,
        max_duplicate_feedback_bodies=settings.max_duplicate_feedback_bodies,
        max_verification_feedback_bodies=settings.max_verification_feedback_bodies,
    )
    assert any(reason == structural_reason for _body, reason in redraft_feedback)
