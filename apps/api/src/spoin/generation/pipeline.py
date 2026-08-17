"""Two topics-in, corpus-out phases — one-shot generation, as a LangGraph graph.

See ADR-0024 for why this is a graph at all, ADR-0025 for the batched topic
matching phase, and ADR-0026 for the one-shot-completion redesign this module
now implements. This module owns only what happens *inside* generation itself —
scheduling, retry-across-restart, and priority remain the worker/`GenerationJob`'s
job, unchanged.

**Two entrypoints, two transactions, on purpose:**

```
match_and_create_topics()    ADR-0025. Cheap, no card generation. For each
                              incoming (name, description): either alias onto
                              an existing topic (nothing else happens), or mint
                              a brand-new Topic row -- curriculum NOT generated
                              yet. Callers commit this BEFORE calling
                              run_generation_pipeline, so a topic's identity
                              (and any GenerationJob row referencing its id)
                              survives even if generation itself later fails
                              and retries.

run_generation_pipeline()    ADR-0026. Takes topic_ids that ALREADY exist
                              (minted by match_and_create_topics, possibly in an
                              earlier, separately-committed call). Curriculum
                              (if not already generated) -> cards, per subtopic
                              per difficulty tier, with a linked tier's higher-
                              difficulty cards built on its lower tier's actual
                              content -> questions, generated from the cards
                              just written. One topic, run once, done --
                              idempotent if called again for a topic that
                              already finished (nothing left to generate).
```

**`langgraph` is confined to this module**, the same way ADR-0002 confines
`langchain*` to `langchain_impl.py` -- this module never imports `langchain*`
either, it only calls the `ContentGenerator` interface, so it has no idea
whether Gemini, local, or `FakeContentGenerator` is behind it.

```
START
  |  Send fan-out, one branch per topic_id (independent -- a topic already
  |  curriculum'd and just topping up cards never waits on a sibling topic
  |  still doing its first curriculum pass)
  v
resolve_and_plan_topic     Per topic (already exists; ADR-0025 decided that
                           upstream). Curriculum call only if
                           curriculum_generated_at is unset. Groups its
                           subtopics by subtopic_group_id (a curriculum
                           "concept"'s 1-3 difficulty tiers).
  |
  | Send fan-out, one branch per subtopic GROUP (not per subtopic-tier --
  | see generate_subtopic_cards for why)
  v
generate_subtopic_cards   No DB access (concurrent across groups AND topics).
                          Within one group, tiers run SEQUENTIALLY, lowest
                          difficulty first, because a linked higher tier's
                          card generation receives the lower tier's actual
                          card BODIES as context (ADR-0026) -- it has to exist
                          first. Groups with only one tier (the common case)
                          are unaffected: nothing to sequence.
  |
  | fan-in (every branch's results merge, across every topic in the run)
  v
gate_and_persist          The ONLY card/question-writing node, one writer, no
                           concurrency to reason about for the DB itself.
                           Persists cards (minimal gate -- see generation/gate.py),
                           THEN concurrently (asyncio.gather, same semaphore as
                           everywhere else) generates questions FROM the cards
                           just written, per subtopic/difficulty, and persists
                           those too. A topic isn't done until both exist.
```
"""

from __future__ import annotations

import asyncio
import math
import operator
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, Send
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.content.archetype import classify_archetype
from spoin.content.difficulty_examples import get_difficulty_examples
from spoin.core.config import Settings
from spoin.domain.enums import (
    CardStatus,
    Difficulty,
    QuestionKind,
    QuestionStatus,
    RejectionStage,
    TopicEdgeKind,
)
from spoin.domain.models import (
    Card,
    CardStats,
    Question,
    RejectedCard,
    Subtopic,
    Topic,
    TopicAlias,
    TopicEdge,
)
from spoin.embeddings import Embedder, normalize_topic_text
from spoin.generation.base import (
    CardCorrectionQuery,
    CardDraft,
    CardVerificationQuery,
    ContentGenerator,
    TopicMatchCandidate,
    TopicMatchQuery,
    TopicMatchResult,
)
from spoin.generation.dedup import find_batch_duplicate, find_corpus_duplicate
from spoin.generation.gate import passes_minimal_gate

#: ADR-0030: no calibration examples for a linked subtopic-tier -- it gets
#: real, concept-specific calibration from `builds_on` instead.
_NO_DIFFICULTY_EXAMPLES: dict[Difficulty, list[str]] = {difficulty: [] for difficulty in Difficulty}

_SLUG_KEEP = "abcdefghijklmnopqrstuvwxyz0123456789-"


def _slugify(name: str) -> str:
    lowered = "-".join(name.strip().lower().split())
    return "".join(char for char in lowered if char in _SLUG_KEEP) or "topic"


def _existing_title_tag(canonical_title: str, title: str, difficulty: Difficulty) -> str:
    """ADR-0022 + ADR-0007: the already-covered list a generator sees must carry
    the canonical title (so the model can tell a subject is taken), the display
    title (so it doesn't invent the same joke twice under new wording), AND the
    difficulty it was written at (so a beginner and advanced card on the same
    concept differ in depth, not just wording)."""

    label = f"{canonical_title} ({title})" if canonical_title != title else canonical_title
    return f"{label} [{difficulty.value}]"


def _min_cards(target_cards: int, fraction: float) -> int:
    return max(1, round(target_cards * fraction))


# --------------------------------------------------------------------- state --


class TopicRequest(TypedDict):
    name: str
    description: str


class TopicMatchOutcome(TypedDict):
    """One `match_and_create_topics` result: either an alias onto an existing
    topic (nothing else happened) or a freshly-minted, not-yet-generated one."""

    topic_id: str
    topic_name: str
    matched_existing: bool


class SubtopicPlan(TypedDict):
    topic_id: str
    topic_name: str
    subtopic_id: str
    #: Groups this subtopic with its sibling difficulty tiers of the same
    #: curriculum-authored concept -- what generate_subtopic_cards fans out on.
    subtopic_group_id: str
    difficulty: str
    title: str
    description: str
    target_cards: int
    #: Pre-fetched in resolve_and_plan_topic -- see module docstring for why
    #: this can't be a DB read inside generate_subtopic_cards. Spans every
    #: sibling subtopic in the same subtopic_group_id (ADR-0007's cross-tier ask).
    existing_titles: list[str]
    existing_count: int
    #: Bodies of this EXACT subtopic-tier's (not group-wide -- near-dup
    #: detection is subtopic-scoped, see generation/dedup.py) most recent
    #: `rejected_card` rows with stage=near_duplicate, from a prior run.
    #: Prevention feedback (ADR-0030 addendum): the writer sees actual
    #: rejected content and is told not to reproduce it, rather than
    #: rediscovering the same duplicate only to have it rejected again.
    avoid_duplicate_bodies: list[str]


class SubtopicGroupPlan(TypedDict):
    """One curriculum concept's 1-3 difficulty tiers, ordered lowest first --
    the Send fan-out unit for card generation (ADR-0026)."""

    topic_id: str
    topic_name: str
    tiers: list[SubtopicPlan]


class TopicPlanResult(TypedDict):
    topic_id: str
    topic_name: str
    #: Fed to the quality gate's correction pass as the canonical topic
    #: description (ADR-0030) -- pulled from `Topic.description`, not stored
    #: anywhere else in the plan.
    topic_description: str
    is_survey: bool
    deep_dive_topic_names: list[str]
    subtopics: list[SubtopicPlan]


class SubtopicCardsResult(TypedDict):
    topic_id: str
    subtopic_id: str
    difficulty: str
    drafts: list[CardDraft]
    generator_failures: list[str]
    #: True iff this subtopic-tier has no sibling tiers in its
    #: `subtopic_group_id` -- decides whether the quality gate's two passes
    #: get the hand-curated difficulty example catalog (ADR-0030) instead of
    #: relying on `builds_on`'s real sibling-tier context.
    is_standalone: bool


class PipelineState(TypedDict, total=False):
    #: Already-existing Topic ids (ADR-0025 decided that upstream).
    topic_ids: list[str]
    #: Only set on a per-branch Send invocation (outer fan-out).
    topic_job: dict[str, str]
    #: Globally accumulated across every topic branch -- used by gate_and_persist
    #: to build the final per-topic report. NOTE: this is also the only way
    #: `resolve_and_plan_topic` gets its own subtopics to a downstream fan-out --
    #: see that function's docstring for why a plain (non-reducer) key doesn't
    #: work here: concurrent topic branches in the same superstep all write into
    #: the SAME shared channels, and a plain "last value" channel raises
    #: `InvalidUpdateError` the moment two branches write to it in one step.
    #: `Send`-created branches are NOT isolated forks with their own local state.
    topic_plans: Annotated[list[TopicPlanResult], operator.add]
    #: Only set on a per-branch Send invocation (inner fan-out).
    subtopic_group_job: SubtopicGroupPlan
    card_results: Annotated[list[SubtopicCardsResult], operator.add]
    report: dict[str, object]


@dataclass
class _Runtime:
    """Dependencies threaded through `config["configurable"]` rather than graph
    state -- none of these are pipeline *data*."""

    session: AsyncSession
    generator: ContentGenerator
    embedder: Embedder
    settings: Settings
    batch_id: uuid.UUID
    semaphore: asyncio.Semaphore
    topic_plan_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


#: `config` is deliberately left untyped on every node function below (here and
#: in resolve_and_plan_topic / generate_subtopic_cards / gate_and_persist).
#: LangGraph's own node config type is `RunnableConfig` (from langchain_core), and
#: at runtime it inspects each node's `config` parameter annotation -- if present
#: and not exactly `RunnableConfig`, it emits a `UserWarning` ("should be typed as
#: RunnableConfig"), which this repo's `filterwarnings = ["error"]` pytest config
#: turns into a hard test failure. Importing `RunnableConfig` here to satisfy it
#: would violate ADR-0002/0024's "pipeline.py never imports langchain*" boundary
#: (enforced by tests/test_architecture.py) for a type that carries no
#: model/prompt surface at all. Leaving the parameter unannotated is the one
#: option LangGraph's own inspection treats as a non-issue.
def _runtime(config) -> _Runtime:  # type: ignore[no-untyped-def]
    configurable = config["configurable"]
    runtime = configurable["runtime"]
    assert isinstance(runtime, _Runtime)
    return runtime


# ---------------------------------------------------------- topic matching (ADR-0025) --


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
    embeddings = embedder.embed(normalized_names)

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
            outcomes.append(
                TopicMatchOutcome(
                    topic_id=str(topic.id), topic_name=topic.canonical_name, matched_existing=True
                )
            )
        else:
            topic = Topic(
                slug=_slugify(request["name"]),
                canonical_name=request["name"],
                description=request["description"],
            )
            session.add(topic)
            await session.flush()
            topic.embedding = embedding
            outcomes.append(
                TopicMatchOutcome(
                    topic_id=str(topic.id), topic_name=topic.canonical_name, matched_existing=False
                )
            )

    await session.flush()
    return outcomes


# ------------------------------------------------------------- topic resolution --


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


async def _load_subtopic_plans(
    session: AsyncSession, topic: Topic, *, max_duplicate_feedback_bodies: int
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
            await session.execute(
                select(RejectedCard.body)
                .where(
                    RejectedCard.subtopic_id == subtopic.id,
                    RejectedCard.stage == RejectionStage.NEAR_DUPLICATE,
                )
                .order_by(RejectedCard.created_at.desc())
                .limit(max_duplicate_feedback_bodies)
            )
        ).scalars().all()
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
                existing_titles=[_existing_title_tag(c, t, d) for c, t, d in existing],
                existing_count=this_subtopic_count,
                avoid_duplicate_bodies=list(avoid_bodies),
            )
        )
    return plans


async def resolve_and_plan_topic(  # type: ignore[no-untyped-def]
    state: PipelineState, config
) -> Command[Any]:
    """The topic this branch is for already exists -- ADR-0025's matching phase
    decided that before this graph even started. All this does now is the
    curriculum pass (if not already done) and grouping subtopics by difficulty
    tier for the card-generation fan-out.

    Returns a `Command` (state update + routing) instead of a plain dict,
    specifically so the fan-out to `generate_subtopic_cards` can use THIS
    invocation's own freshly-computed `plan` directly -- a separate conditional-edge
    function reading a shared state key doesn't work here (see PipelineState's
    `topic_plans` docstring: concurrent topic branches can't each write a
    non-reducer key in the same step). `Command.goto` sidesteps that entirely.
    """

    runtime = _runtime(config)
    topic_id = uuid.UUID(state["topic_job"]["topic_id"])

    async with runtime.topic_plan_lock:
        topic = await runtime.session.get(Topic, topic_id)
    assert topic is not None, f"GenerationJob referenced missing topic {topic_id}"

    need_curriculum = topic.curriculum_generated_at is None
    deep_dive_names: list[str] = []
    is_survey = topic.is_survey

    if need_curriculum:
        async with runtime.topic_plan_lock:
            existing_subtopic_hints = await _existing_subtopic_hints(runtime.session, topic.id)
        async with runtime.semaphore:
            draft = await runtime.generator.generate_curriculum(
                topic.canonical_name, topic.description or "", existing_subtopic_hints or None
            )
        async with runtime.topic_plan_lock:
            topic.is_survey = draft.is_survey
            await _create_deep_dive_stubs(
                runtime.session, parent=topic, names=draft.deep_dive_topics
            )
            for group in draft.subtopics:
                tier_rows = [
                    (
                        *(
                            await _reuse_or_create_subtopic(
                                runtime.session,
                                topic_id=topic.id,
                                title=group.title,
                                difficulty=tier.difficulty,
                            )
                        ),
                        tier,
                    )
                    for tier in group.tiers
                ]
                # A new group adopts an EXISTING subtopic's group id if any of its
                # tiers reused one -- keeps that subtopic's prior tier siblings (if
                # any) connected to the new tiers landing alongside it, rather than
                # forking a second, disconnected group for the same concept. A
                # reused row's OWN group id is never overwritten.
                group_id = next(
                    (row[0].subtopic_group_id for row in tier_rows if row[1]), uuid.uuid4()
                )
                for subtopic, reused, tier in tier_rows:
                    if not reused:
                        subtopic.subtopic_group_id = group_id
                    subtopic.description = tier.description
                    subtopic.target_cards = tier.target_cards
                    subtopic.min_cards = _min_cards(
                        tier.target_cards, runtime.settings.min_cards_fraction
                    )
                    subtopic.position = group.position
            topic.curriculum_generated_at = datetime.now(UTC)
            await runtime.session.flush()
            deep_dive_names = draft.deep_dive_topics
            is_survey = draft.is_survey

    async with runtime.topic_plan_lock:
        subtopic_plans = await _load_subtopic_plans(
            runtime.session,
            topic,
            max_duplicate_feedback_bodies=runtime.settings.max_duplicate_feedback_bodies,
        )

    plan = TopicPlanResult(
        topic_id=str(topic.id),
        topic_name=topic.canonical_name,
        topic_description=topic.description or "",
        is_survey=is_survey,
        deep_dive_topic_names=deep_dive_names,
        subtopics=subtopic_plans,
    )

    groups: dict[str, list[SubtopicPlan]] = {}
    for subtopic_plan in subtopic_plans:
        groups.setdefault(subtopic_plan["subtopic_group_id"], []).append(subtopic_plan)
    group_plans = [
        SubtopicGroupPlan(
            topic_id=plan["topic_id"],
            topic_name=plan["topic_name"],
            tiers=sorted(tiers, key=lambda sp: Difficulty(sp["difficulty"]).rank),
        )
        for tiers in groups.values()
    ]

    # Every subtopic group gets a branch -- deliberately NOT filtered down to
    # only under-target ones here (see generate_subtopic_cards, which does that
    # per-tier). `CurriculumDraft.subtopics` requires at least one entry, so
    # every topic branch is guaranteed >=1 group Send, keeping every topic's
    # path to `gate_and_persist` the same shape.
    return Command(
        update={"topic_plans": [plan]},
        goto=[
            Send("generate_subtopic_cards", {"subtopic_group_job": group_plan})
            for group_plan in group_plans
        ],
    )


def fan_out_topics(state: PipelineState) -> list[Send]:
    return [
        Send("resolve_and_plan_topic", {"topic_job": {"topic_id": topic_id}})
        for topic_id in state["topic_ids"]
    ]


# ---------------------------------------------------------------- card generation --


async def generate_subtopic_cards(  # type: ignore[no-untyped-def]
    state: PipelineState, config
) -> dict[str, object]:
    """No DB access -- see module docstring. Runs once per subtopic GROUP that
    still needs cards, potentially concurrently with every other such group,
    across every topic in this run. Tiers WITHIN one group run sequentially,
    lowest difficulty first, so a linked higher tier's `generate_cards` call can
    receive the lower tier's actual card bodies as `builds_on` (ADR-0026) --
    groups with only one tier (the common case; curricula are never forced to
    give a concept all three tiers) are unaffected, there's nothing to sequence.
    """

    runtime = _runtime(config)
    job = state["subtopic_group_job"]
    batch_size = runtime.settings.generation_batch_size
    #: A tier with sibling tiers gets real calibration from `builds_on`
    #: instead of the generic catalog (ADR-0030) -- see this function's
    #: docstring: groups with one tier are the common case.
    is_standalone = len(job["tiers"]) == 1
    difficulty_examples = get_difficulty_examples() if is_standalone else _NO_DIFFICULTY_EXAMPLES

    results: list[SubtopicCardsResult] = []
    lower_tier_bodies: list[str] = []

    for tier in job["tiers"]:
        difficulty = Difficulty(tier["difficulty"])
        target = tier["target_cards"]

        if tier["existing_count"] >= target:
            results.append(
                SubtopicCardsResult(
                    topic_id=tier["topic_id"],
                    subtopic_id=tier["subtopic_id"],
                    difficulty=tier["difficulty"],
                    drafts=[],
                    generator_failures=[],
                    is_standalone=is_standalone,
                )
            )
            # Nothing generated THIS run for this tier, so it contributes no
            # bodies to `lower_tier_bodies` for a higher linked tier above it --
            # a known gap when a tier was already-covered by an earlier call
            # (task 0010's follow-up, not solved here: this node has no DB
            # access to fetch that prior content).
            continue

        drafts: list[CardDraft] = []
        failures: list[str] = []
        existing_titles = list(tier["existing_titles"])
        # +1 round of slack: a batch that comes back short of `count` (partial
        # failure, ADR-0005) shouldn't need a perfectly-sized final call to
        # still reach target.
        max_rounds = math.ceil(target / batch_size) + 1

        for _ in range(max_rounds):
            remaining = target - len(drafts)
            if remaining <= 0:
                break
            async with runtime.semaphore:
                result = await runtime.generator.generate_cards(
                    topic_name=job["topic_name"],
                    subtopic_title=tier["title"],
                    subtopic_description=tier["description"],
                    difficulty=difficulty,
                    count=min(batch_size, remaining),
                    existing_titles=existing_titles,
                    builds_on=lower_tier_bodies,
                    difficulty_examples=difficulty_examples,
                    avoid_bodies=tier["avoid_duplicate_bodies"],
                )
            failures.extend(result.failures)
            if not result.items:
                break  # no usable progress this round -- stop
            drafts.extend(result.items)
            existing_titles.extend(
                _existing_title_tag(d.canonical_title, d.title, d.difficulty) for d in result.items
            )

        results.append(
            SubtopicCardsResult(
                topic_id=tier["topic_id"],
                subtopic_id=tier["subtopic_id"],
                difficulty=tier["difficulty"],
                drafts=drafts,
                generator_failures=failures,
                is_standalone=is_standalone,
            )
        )
        lower_tier_bodies = lower_tier_bodies + [draft.body for draft in drafts]

    return {"card_results": results}


# ------------------------------------------------------- persist cards + questions --


def _rejected_card(
    *,
    topic_id: str,
    subtopic_id: str,
    draft: CardDraft,
    stage: RejectionStage,
    reason: str,
    generated_at: str,
    backend: str,
    batch_id: uuid.UUID,
) -> RejectedCard:
    return RejectedCard(
        topic_id=uuid.UUID(topic_id),
        subtopic_id=uuid.UUID(subtopic_id),
        requested_difficulty=draft.difficulty,
        title=draft.title,
        canonical_title=draft.canonical_title,
        summary=draft.summary,
        body=draft.body,
        stage=stage,
        reason=reason,
        gen_meta={"backend": backend, "generated_at": generated_at, "batch_id": str(batch_id)},
    )


async def _correct_subtopic_drafts(
    runtime: _Runtime,
    *,
    subtopic_id: str,
    topic_name: str,
    topic_description: str,
    difficulty_examples: dict[Difficulty, list[str]],
    drafts: list[CardDraft],
) -> tuple[str, list[CardDraft], list[str]]:
    """ADR-0030 pass 1. Concurrent across subtopics (no DB access -- pure
    generator calls, same principle as `_generate_questions_for_group`).
    Returns corrected drafts in receipt order; a draft whose correction never
    came back (malformed/missing item) is DROPPED and reported as a failure --
    there is nothing safe to persist without a corrected body."""

    batch_size = runtime.settings.judge_batch_size
    corrected: list[CardDraft] = []
    failures: list[str] = []

    for start in range(0, len(drafts), batch_size):
        chunk = drafts[start : start + batch_size]
        queries = [
            CardCorrectionQuery(
                index=index,
                topic_name=topic_name,
                topic_description=topic_description,
                title=draft.title,
                canonical_title=draft.canonical_title,
                summary=draft.summary,
                body=draft.body,
            )
            for index, draft in enumerate(chunk)
        ]
        async with runtime.semaphore:
            result = await runtime.generator.correct_cards(
                queries, difficulty_examples=difficulty_examples
            )
        failures.extend(result.failures)
        by_index = {item.index: item for item in result.items}
        for index, draft in enumerate(chunk):
            correction = by_index.get(index)
            if correction is None:
                failures.append(f"correction pass returned no result for card {index}")
                continue
            corrected.append(
                draft.model_copy(
                    update={
                        "title": correction.title,
                        "canonical_title": correction.canonical_title,
                        "summary": correction.summary,
                        "body": correction.body,
                    }
                )
            )

    return subtopic_id, corrected, failures


async def _verify_subtopic_drafts(
    runtime: _Runtime,
    *,
    subtopic_id: str,
    difficulty_examples: dict[Difficulty, list[str]],
    items: list[tuple[CardDraft, list[float]]],
) -> tuple[
    str, list[tuple[CardDraft, list[float], Difficulty]], list[tuple[CardDraft, str]], list[str]
]:
    """ADR-0030 pass 2. `items` is (corrected draft, its post-correction
    embedding) for every card that survived dedup. Concurrent across
    subtopics, same reasoning as `_correct_subtopic_drafts`. Returns
    (subtopic_id, accepted[(draft, embedding, confirmed_difficulty)],
    rejected[(draft, reason)], failures)."""

    batch_size = runtime.settings.judge_batch_size
    accepted: list[tuple[CardDraft, list[float], Difficulty]] = []
    rejected: list[tuple[CardDraft, str]] = []
    failures: list[str] = []

    for start in range(0, len(items), batch_size):
        chunk = items[start : start + batch_size]
        queries = [
            CardVerificationQuery(
                index=index,
                canonical_title=draft.canonical_title,
                body=draft.body,
                requested_difficulty=draft.difficulty,
            )
            for index, (draft, _embedding) in enumerate(chunk)
        ]
        async with runtime.semaphore:
            result = await runtime.generator.verify_cards(
                queries, difficulty_examples=difficulty_examples
            )
        failures.extend(result.failures)
        by_index = {item.index: item for item in result.items}
        for index, (draft, embedding) in enumerate(chunk):
            verdict = by_index.get(index)
            if verdict is None:
                failures.append(f"verification pass returned no result for card {index}")
                continue
            if not verdict.accepted:
                rejected.append((draft, verdict.reason or "failed verification"))
                continue
            accepted.append((draft, embedding, verdict.confirmed_difficulty))

    return subtopic_id, accepted, rejected, failures


async def _generate_questions_for_group(
    runtime: _Runtime, *, topic_id: str, subtopic_id: str, difficulty: str, cards: list[Card]
) -> tuple[str, str, str, list[tuple[Any, uuid.UUID]], list[str]]:
    """Concurrent, no DB writes (only reads the just-persisted `cards` passed
    in). One subtopic/difficulty's worth of questions, batched per
    `question_batch_size` same as card generation batches per `generation_batch_size`."""

    batch_size = runtime.settings.question_batch_size
    parsed_difficulty = Difficulty(difficulty)
    drafts: list[tuple[Any, uuid.UUID]] = []
    failures: list[str] = []

    for start in range(0, len(cards), batch_size):
        chunk = cards[start : start + batch_size]
        async with runtime.semaphore:
            result = await runtime.generator.generate_questions(
                cards=[(card.title, card.body) for card in chunk], difficulty=parsed_difficulty
            )
        failures.extend(result.failures)
        for draft in result.items:
            if 0 <= draft.card_index < len(chunk):
                drafts.append((draft, chunk[draft.card_index].id))

    return topic_id, subtopic_id, difficulty, drafts, failures


@dataclass
class _GateItem:
    """One subtopic-tier's worth of drafts, tracked through the whole gate
    (ADR-0030) so the two concurrent LLM phases and the sequential DB phase
    can all find their way back to the right subtopic/topic report."""

    topic_id: str
    subtopic_id: str
    difficulty: str
    topic_name: str
    topic_description: str
    difficulty_examples: dict[Difficulty, list[str]]
    survivors: list[CardDraft]
    #: (draft, reason) for cards that never made it past structural
    #: validation -- kept as the ORIGINAL draft, since correction never ran.
    structural_rejects: list[tuple[CardDraft, str]]
    generator_failure_count: int
    #: Filled in by later phases.
    corrected: list[CardDraft] = field(default_factory=list)
    correction_failure_count: int = 0
    dedup_survivors: list[tuple[CardDraft, list[float]]] = field(default_factory=list)
    #: (draft, reason) for near-duplicate rejects, post-correction.
    dedup_rejects: list[tuple[CardDraft, str]] = field(default_factory=list)
    verified: list[tuple[CardDraft, list[float], Difficulty]] = field(default_factory=list)
    #: (draft, reason) for pass-2 rejects, post-correction.
    verification_rejects: list[tuple[CardDraft, str]] = field(default_factory=list)
    verification_failure_count: int = 0


async def gate_and_persist(  # type: ignore[no-untyped-def]
    state: PipelineState, config
) -> dict[str, object]:
    """The only writer node. Runs the two-pass quality gate (ADR-0030) --
    structural check, then pass 1 correction, then near-duplicate detection,
    then pass 2 verification -- persisting every draft as exactly one of an
    ACTIVE `Card` or a `RejectedCard` row, then generates and persists
    questions FROM the accepted cards -- a topic isn't done (ADR-0026) until
    both exist.

    The two LLM phases (correction, verification) run concurrently across
    every subtopic-tier in this batch (`asyncio.gather`, same semaphore
    governing every other generator call) since neither touches the DB.
    Near-duplicate detection sits between them and DOES touch the DB (a
    corpus lookup per card), so it stays sequential, same as every other
    write in this node.
    """

    runtime = _runtime(config)
    generated_at = datetime.now(UTC).isoformat()
    backend = runtime.settings.generator
    threshold = runtime.settings.card_duplicate_threshold

    by_topic: dict[str, list[SubtopicCardsResult]] = {}
    for result in state.get("card_results", []):
        by_topic.setdefault(result["topic_id"], []).append(result)

    # ---- assemble one _GateItem per subtopic-tier, structural gate first --
    items: list[_GateItem] = []
    for plan in state.get("topic_plans", []):
        for result in by_topic.get(plan["topic_id"], []):
            survivors: list[CardDraft] = []
            structural_rejects: list[tuple[CardDraft, str]] = []
            for draft in result["drafts"]:
                ok, reason = passes_minimal_gate(draft)
                if ok:
                    survivors.append(draft)
                else:
                    structural_rejects.append((draft, reason or "failed structural gate"))

            examples = (
                get_difficulty_examples() if result["is_standalone"] else _NO_DIFFICULTY_EXAMPLES
            )
            items.append(
                _GateItem(
                    topic_id=result["topic_id"],
                    subtopic_id=result["subtopic_id"],
                    difficulty=result["difficulty"],
                    topic_name=plan["topic_name"],
                    topic_description=plan["topic_description"],
                    difficulty_examples=examples,
                    survivors=survivors,
                    structural_rejects=structural_rejects,
                    generator_failure_count=len(result["generator_failures"]),
                )
            )

    # ---- phase 1: correction, concurrent across subtopic-tiers ------------
    correction_results = (
        await asyncio.gather(
            *(
                _correct_subtopic_drafts(
                    runtime,
                    subtopic_id=item.subtopic_id,
                    topic_name=item.topic_name,
                    topic_description=item.topic_description,
                    difficulty_examples=item.difficulty_examples,
                    drafts=item.survivors,
                )
                for item in items
                if item.survivors
            )
        )
        if any(item.survivors for item in items)
        else []
    )
    corrections_by_subtopic = {
        subtopic_id: (corrected, failures)
        for subtopic_id, corrected, failures in correction_results
    }
    for item in items:
        corrected, failures = corrections_by_subtopic.get(item.subtopic_id, ([], []))
        item.corrected = corrected
        item.correction_failure_count = len(failures)

    # ---- phase 2: near-duplicate detection, sequential (DB reads) --------
    for item in items:
        if not item.corrected:
            continue
        bodies = [draft.body for draft in item.corrected]
        embeddings = runtime.embedder.embed(bodies)
        accepted_embeddings: list[list[float]] = []
        subtopic_uuid = uuid.UUID(item.subtopic_id)
        for draft, embedding in zip(item.corrected, embeddings, strict=True):
            corpus_hit = await find_corpus_duplicate(
                runtime.session, subtopic_id=subtopic_uuid, embedding=embedding, threshold=threshold
            )
            if corpus_hit is not None:
                item.dedup_rejects.append(
                    (draft, f"near-duplicate of an existing card (similarity {corpus_hit:.3f})")
                )
                continue
            batch_hit = find_batch_duplicate(embedding, accepted_embeddings, threshold=threshold)
            if batch_hit is not None:
                item.dedup_rejects.append(
                    (draft, f"near-duplicate within this batch (similarity {batch_hit:.3f})")
                )
                continue
            accepted_embeddings.append(embedding)
            item.dedup_survivors.append((draft, embedding))

    # ---- phase 3: verification, concurrent across subtopic-tiers ---------
    verification_results = (
        await asyncio.gather(
            *(
                _verify_subtopic_drafts(
                    runtime,
                    subtopic_id=item.subtopic_id,
                    difficulty_examples=item.difficulty_examples,
                    items=item.dedup_survivors,
                )
                for item in items
                if item.dedup_survivors
            )
        )
        if any(item.dedup_survivors for item in items)
        else []
    )
    verification_by_subtopic = {
        subtopic_id: (accepted, rejected, failures)
        for subtopic_id, accepted, rejected, failures in verification_results
    }
    for item in items:
        verified, verify_rejects, verify_failures = verification_by_subtopic.get(
            item.subtopic_id, ([], [], [])
        )
        item.verified = verified
        item.verification_rejects = verify_rejects
        item.verification_failure_count = len(verify_failures)

    # ---- phase 4: persist, sequential (the only writer) -------------------
    topic_reports: list[dict[str, object]] = []
    pending_questions: list[tuple[str, str, str, list[Card]]] = []
    reports_by_topic: dict[str, list[dict[str, object]]] = {}
    totals_by_topic: dict[str, tuple[int, int]] = {}

    for item in items:
        rejected_rows = [
            _rejected_card(
                topic_id=item.topic_id,
                subtopic_id=item.subtopic_id,
                draft=draft,
                stage=RejectionStage.STRUCTURAL,
                reason=reason,
                generated_at=generated_at,
                backend=backend,
                batch_id=runtime.batch_id,
            )
            for draft, reason in item.structural_rejects
        ]
        rejected_rows += [
            _rejected_card(
                topic_id=item.topic_id,
                subtopic_id=item.subtopic_id,
                draft=draft,
                stage=RejectionStage.NEAR_DUPLICATE,
                reason=reason,
                generated_at=generated_at,
                backend=backend,
                batch_id=runtime.batch_id,
            )
            for draft, reason in item.dedup_rejects
        ]
        rejected_rows += [
            _rejected_card(
                topic_id=item.topic_id,
                subtopic_id=item.subtopic_id,
                draft=draft,
                stage=RejectionStage.VERIFICATION,
                reason=reason,
                generated_at=generated_at,
                backend=backend,
                batch_id=runtime.batch_id,
            )
            for draft, reason in item.verification_rejects
        ]
        runtime.session.add_all(rejected_rows)

        new_cards = [
            Card(
                family_id=uuid.uuid4(),
                topic_id=uuid.UUID(item.topic_id),
                subtopic_id=uuid.UUID(item.subtopic_id),
                difficulty=draft.difficulty,
                judged_difficulty=confirmed_difficulty,
                status=CardStatus.ACTIVE,
                title=draft.title,
                canonical_title=draft.canonical_title,
                summary=draft.summary,
                body=draft.body,
                visual_id=draft.visual_id,
                visual_slots=draft.visual_slots,
                content_embedding=embedding,
                gen_meta={
                    "backend": backend,
                    "generated_at": generated_at,
                    "batch_id": str(runtime.batch_id),
                },
            )
            for draft, embedding, confirmed_difficulty in item.verified
        ]
        runtime.session.add_all(new_cards)
        await runtime.session.flush()
        for card in new_cards:
            card.archetype = classify_archetype(card.body)
            runtime.session.add(CardStats(card_id=card.id))

        if new_cards:
            pending_questions.append((item.topic_id, item.subtopic_id, item.difficulty, new_cards))

        total_rejected = (
            len(item.structural_rejects)
            + item.correction_failure_count
            + len(item.dedup_rejects)
            + len(item.verification_rejects)
            + item.verification_failure_count
            + item.generator_failure_count
        )
        reports_by_topic.setdefault(item.topic_id, []).append(
            {
                "subtopic_id": item.subtopic_id,
                "difficulty": item.difficulty,
                "accepted": len(new_cards),
                "rejected": total_rejected,
            }
        )
        prev_accepted, prev_rejected = totals_by_topic.get(item.topic_id, (0, 0))
        totals_by_topic[item.topic_id] = (
            prev_accepted + len(new_cards),
            prev_rejected + total_rejected,
        )

    for plan in state.get("topic_plans", []):
        topic_id = plan["topic_id"]
        total_accepted, total_rejected = totals_by_topic.get(topic_id, (0, 0))
        topic_reports.append(
            {
                "topic_id": topic_id,
                "topic_name": plan["topic_name"],
                "is_survey": plan["is_survey"],
                "deep_dive_topic_names": plan["deep_dive_topic_names"],
                "accepted": total_accepted,
                "rejected": total_rejected,
                "subtopics": reports_by_topic.get(topic_id, []),
                "questions_accepted": 0,
                "questions_rejected": 0,
            }
        )

    await runtime.session.flush()

    question_results = (
        await asyncio.gather(
            *(
                _generate_questions_for_group(
                    runtime, topic_id=t, subtopic_id=s, difficulty=d, cards=cards
                )
                for t, s, d, cards in pending_questions
            )
        )
        if pending_questions
        else []
    )

    question_counts_by_topic: dict[str, tuple[int, int]] = {}
    for topic_id, subtopic_id, difficulty, drafts, failures in question_results:
        parsed_difficulty = Difficulty(difficulty)
        stems = [draft.stem for draft, _card_id in drafts]
        embeddings = runtime.embedder.embed(stems) if stems else []
        new_questions: list[Question] = []
        for (draft, card_id), embedding in zip(drafts, embeddings, strict=True):
            new_questions.append(
                Question(
                    subtopic_id=uuid.UUID(subtopic_id),
                    card_id=card_id,
                    difficulty=parsed_difficulty,
                    kind=QuestionKind.MCQ if draft.options is not None else QuestionKind.FREE_TEXT,
                    stem=draft.stem,
                    options=draft.options,
                    correct_index=draft.correct_index,
                    rubric=draft.rubric,
                    reference_answer=draft.reference_answer,
                    explanation=draft.explanation,
                    status=QuestionStatus.ACTIVE,
                    embedding=embedding,
                    gen_meta={
                        "backend": runtime.settings.generator,
                        "generated_at": generated_at,
                        "batch_id": str(runtime.batch_id),
                    },
                )
            )
        runtime.session.add_all(new_questions)
        accepted, rejected = question_counts_by_topic.get(topic_id, (0, 0))
        question_counts_by_topic[topic_id] = (
            accepted + len(new_questions),
            rejected + len(failures),
        )

    await runtime.session.flush()

    for topic_report in topic_reports:
        accepted, rejected = question_counts_by_topic.get(topic_report["topic_id"], (0, 0))
        topic_report["questions_accepted"] = accepted
        topic_report["questions_rejected"] = rejected

    return {"report": {"topics": topic_reports}}


# ------------------------------------------------------------------- entrypoint --


def _build_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    graph = StateGraph(PipelineState)
    graph.add_node(
        "resolve_and_plan_topic", resolve_and_plan_topic, destinations=("generate_subtopic_cards",)
    )
    graph.add_node("generate_subtopic_cards", generate_subtopic_cards)
    graph.add_node("gate_and_persist", gate_and_persist)

    graph.add_conditional_edges(START, fan_out_topics, ["resolve_and_plan_topic"])
    graph.add_edge("generate_subtopic_cards", "gate_and_persist")
    graph.add_edge("gate_and_persist", END)

    return graph.compile()


async def run_generation_pipeline(
    session: AsyncSession,
    generator: ContentGenerator,
    embedder: Embedder,
    settings: Settings,
    *,
    topic_ids: list[uuid.UUID],
) -> dict[str, object]:
    """ADR-0026's one-shot run: curriculum (if needed) -> cards -> questions,
    for topics that ALREADY EXIST (see `match_and_create_topics`). Callable
    directly from a CLI script (today) or a worker job handler (task 0008) --
    this function has no idea which is calling it, or whether a topic_id is
    brand new or a retry of one whose earlier attempt failed partway.
    """

    if not topic_ids:
        return {"topics": []}

    graph = _build_graph()
    runtime = _Runtime(
        session=session,
        generator=generator,
        embedder=embedder,
        settings=settings,
        batch_id=uuid.uuid4(),
        semaphore=asyncio.Semaphore(settings.max_concurrent_generation_calls),
    )
    initial_state: PipelineState = {
        "topic_ids": [str(topic_id) for topic_id in topic_ids],
        "topic_plans": [],
        "card_results": [],
    }
    final_state = await graph.ainvoke(initial_state, config={"configurable": {"runtime": runtime}})
    report: dict[str, object] = final_state["report"]
    return report
