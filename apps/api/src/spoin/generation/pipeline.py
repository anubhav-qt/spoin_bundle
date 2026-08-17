"""Many topics, curriculum through corpus — the vertical slice, as a LangGraph graph.

See ADR-0024 for why this is a graph at all and why it does NOT own scheduling,
retry-across-restart, or priority: that's the worker/`GenerationJob`'s job, unchanged.
This module owns only what happens *inside* one generation run.

**`langgraph` is confined to this module**, the same way ADR-0002 confines
`langchain*` to `langchain_impl.py`. This module never imports `langchain*` either —
it only calls the `ContentGenerator` interface, so it has no idea whether Gemini,
local, or `FakeContentGenerator` is behind it. It also never imports
`generation/quota.py` — key rotation is entirely `langchain_impl.py`'s concern, one
layer further in; this module makes calls through the interface and has no idea
keys exist.

```
START
  |  Send fan-out, one branch per requested topic
  v
resolve_and_plan_topic     Per topic. ADR-0004 topic resolution (embed -> band
                           decision -> auto-merge / mid-band judge / new) THEN,
                           only if curriculum_generated_at is unset, the curriculum
                           call + subtopic-group persistence. A topic already
                           curriculum'd skips straight to loading its existing
                           subtopics — no LLM call, no re-planning.
  |
  | Send fan-out, one branch per subtopic THIS topic still needs cards for
  v
generate_subtopic_cards   No DB access (concurrent across subtopics AND topics —
                           see ADR-0024's "Harder" section on why this node can't
                           touch the AsyncSession). Loops sequential batches within
                           ONE subtopic (ADR-0007).
  |
  | fan-in (state reducer merges every branch's results, across every topic)
  v
gate_and_persist          One call, sequential, the only card-writing node. Groups
                           results back by topic for the final report. Minimal
                           pass-through gate (generation/gate.py) — the real gate
                           (dedup, judge) is a separate, later step.
```

**Concurrency cap:** every real generator call (curriculum, topic-match judge, card
generation) acquires `runtime.semaphore` first — without it, a request with several
topics times many subtopics each would fire dozens of simultaneous calls, blowing
through `quota_rpm` and turning key exhaustion into a burst of simultaneous failures
instead of a predictable one-at-a-time rotation (that rotation itself is
`langchain_impl.py` + `generation/quota.py`'s job, not this module's).

**Why `resolve_and_plan_topic`'s DB work is lock-guarded, not lock-free like
`generate_subtopic_cards`:** unlike card generation, topic resolution genuinely
needs to read the DB (embedding similarity search) before it knows whether to call
the LLM at all, so "no DB access in a concurrent node" isn't an option here. Instead,
`runtime.topic_plan_lock` serializes the cheap DB bookkeeping across topic branches
while their LLM calls (still gated by the semaphore) can overlap freely.
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
from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty, TopicEdgeKind
from spoin.domain.models import Card, CardStats, Subtopic, Topic, TopicAlias, TopicEdge
from spoin.embeddings import Embedder, normalize_topic_text
from spoin.generation.base import CardDraft, ContentGenerator
from spoin.generation.gate import passes_minimal_gate

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


class SubtopicPlan(TypedDict):
    topic_id: str
    topic_name: str
    subtopic_id: str
    difficulty: str
    title: str
    description: str
    target_cards: int
    #: Pre-fetched in resolve_and_plan_topic — see module docstring for why this
    #: can't be a DB read inside generate_subtopic_cards. Spans every sibling
    #: subtopic in the same subtopic_group_id (ADR-0007's cross-difficulty ask).
    existing_titles: list[str]
    existing_count: int


class TopicPlanResult(TypedDict):
    topic_id: str
    topic_name: str
    is_survey: bool
    deep_dive_topic_names: list[str]
    merged_into_existing: bool
    subtopics: list[SubtopicPlan]


class SubtopicCardsResult(TypedDict):
    topic_id: str
    subtopic_id: str
    difficulty: str
    drafts: list[CardDraft]
    generator_failures: list[str]


class PipelineState(TypedDict, total=False):
    topic_requests: list[TopicRequest]
    #: Only set on a per-branch Send invocation (outer fan-out).
    topic_job: TopicRequest
    #: Globally accumulated across every topic branch — used by gate_and_persist
    #: to build the final per-topic report. NOTE: this is also the only way
    #: `resolve_and_plan_topic` gets its own subtopics to a downstream fan-out —
    #: see that function's docstring for why a plain (non-reducer) key doesn't
    #: work here: concurrent topic branches in the same superstep all write into
    #: the SAME shared channels, and a plain "last value" channel raises
    #: `InvalidUpdateError` the moment two branches write to it in one step.
    #: `Send`-created branches are NOT isolated forks with their own local state.
    topic_plans: Annotated[list[TopicPlanResult], operator.add]
    #: Only set on a per-branch Send invocation (inner fan-out).
    subtopic_job: SubtopicPlan
    card_results: Annotated[list[SubtopicCardsResult], operator.add]
    report: dict[str, object]


@dataclass
class _Runtime:
    """Dependencies threaded through `config["configurable"]` rather than graph
    state — none of these are pipeline *data*."""

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
#: at runtime it inspects each node's `config` parameter annotation — if present
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


# ------------------------------------------------------------- topic resolution --


async def _find_nearest_topic(
    session: AsyncSession, embedding: list[float]
) -> tuple[Topic, float] | None:
    row = (
        await session.execute(
            select(Topic, Topic.embedding.cosine_distance(embedding).label("distance"))
            .where(Topic.embedding.is_not(None))
            .order_by("distance")
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    topic, distance = row
    return topic, 1.0 - distance


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


async def _subtopic_titles_for_topic(session: AsyncSession, topic_id: uuid.UUID) -> list[str]:
    rows = (
        await session.execute(
            select(Subtopic.title).where(Subtopic.topic_id == topic_id).distinct()
        )
    ).all()
    return [row[0] for row in rows]


async def _create_deep_dive_stubs(
    session: AsyncSession, *, parent: Topic, names: list[str]
) -> None:
    """ADR-0007: deep-dive topics are created as canonical topics immediately,
    without curricula — those are generated lazily on first subscription."""

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
    """Titles (with description) of subtopics already under THIS topic — fed to
    `generate_curriculum` as `existing_subtopics` so the model can reuse an exact
    title verbatim when a subtopic it wants is already covered (prevention, same
    pattern already used for card titles — see `generate_cards`'s
    `existing_titles`). No embeddings, no separate judge call: this is a taste
    decision the curriculum call already makes, in the same request, with full
    context — not one that benefits from independent verification the way
    `difficulty` does."""

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
    """Exact title+difficulty match only — the curriculum call is trusted to have
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


async def _load_subtopic_plans(session: AsyncSession, topic: Topic) -> list[SubtopicPlan]:
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
        plans.append(
            SubtopicPlan(
                topic_id=str(topic.id),
                topic_name=topic.canonical_name,
                subtopic_id=str(subtopic.id),
                difficulty=subtopic.difficulty.value,
                title=subtopic.title,
                description=subtopic.description,
                target_cards=subtopic.target_cards,
                existing_titles=[_existing_title_tag(c, t, d) for c, t, d in existing],
                existing_count=this_subtopic_count,
            )
        )
    return plans


async def resolve_and_plan_topic(  # type: ignore[no-untyped-def]
    state: PipelineState, config
) -> Command[Any]:
    """Returns a `Command` (state update + routing) instead of a plain dict,
    specifically so the fan-out to `generate_subtopic_cards` can use THIS
    invocation's own freshly-computed `plan` directly — a separate conditional-edge
    function reading a shared state key doesn't work here (see PipelineState's
    `topic_plans` docstring: concurrent topic branches can't each write a
    non-reducer key in the same step). `Command.goto` sidesteps that entirely: the
    Sends it carries are pure Python data from this function's own local variable,
    never round-tripped through a shared channel at all."""

    runtime = _runtime(config)
    job = state["topic_job"]
    name, description = job["name"], job["description"]

    async with runtime.topic_plan_lock:
        embedding = runtime.embedder.embed_one(normalize_topic_text(name))
        nearest = await _find_nearest_topic(runtime.session, embedding)

    topic: Topic | None = None
    merged_into_existing = False
    related_hints: list[str] = []

    if nearest is not None:
        matched_topic, similarity = nearest
        if similarity >= runtime.settings.topic_merge_high:
            topic = matched_topic
            merged_into_existing = True
            async with runtime.topic_plan_lock:
                await _ensure_alias(
                    runtime.session, topic, name, decided_by="auto_merge", similarity=similarity
                )
        elif similarity > runtime.settings.topic_merge_low:
            # Mid-band: the judge call is an LLM call, made OUTSIDE the DB lock so
            # it can overlap with other topic branches; only gated by the
            # concurrency semaphore, same as every other generator call.
            async with runtime.topic_plan_lock:
                matched_titles = await _subtopic_titles_for_topic(runtime.session, matched_topic.id)
            async with runtime.semaphore:
                verdict = await runtime.generator.judge_topic_match(
                    name, description, matched_topic.canonical_name, matched_titles
                )
            related_hints = verdict.relevant_subtopic_titles
            if verdict.same_topic:
                topic = matched_topic
                merged_into_existing = True
                async with runtime.topic_plan_lock:
                    await _ensure_alias(
                        runtime.session, topic, name, decided_by="llm_judge", similarity=similarity
                    )
        # else: similarity <= topic_merge_low -> falls through, topic stays None (new)

    async with runtime.topic_plan_lock:
        if topic is None:
            topic = Topic(slug=_slugify(name), canonical_name=name, description=description)
            runtime.session.add(topic)
            await runtime.session.flush()
            topic.embedding = embedding
        need_curriculum = topic.curriculum_generated_at is None

    deep_dive_names: list[str] = []
    is_survey = topic.is_survey

    if need_curriculum:
        async with runtime.topic_plan_lock:
            existing_subtopic_hints = await _existing_subtopic_hints(runtime.session, topic.id)
        async with runtime.semaphore:
            draft = await runtime.generator.generate_curriculum(
                name, description, related_hints or None, existing_subtopic_hints or None
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
                # tiers reused one — keeps that subtopic's prior tier siblings (if
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
        subtopic_plans = await _load_subtopic_plans(runtime.session, topic)

    plan = TopicPlanResult(
        topic_id=str(topic.id),
        topic_name=topic.canonical_name,
        is_survey=is_survey,
        deep_dive_topic_names=deep_dive_names,
        merged_into_existing=merged_into_existing,
        subtopics=subtopic_plans,
    )
    # Every subtopic in the plan gets a branch — deliberately NOT filtered down to
    # only under-target ones here. `CurriculumDraft.subtopics` requires at least
    # one entry, so every topic branch is guaranteed >=1 subtopic Send, which
    # keeps every topic's path to `gate_and_persist` the same shape (topic -> >=1
    # subtopic branch -> gate_and_persist). A topic-conditional empty fan-out
    # would let some topics reach `gate_and_persist` in an earlier superstep than
    # others, risking it firing more than once and double-inserting the earlier
    # topics' cards. The "already at target, skip the call" optimization still
    # happens — just inside `generate_subtopic_cards` itself, a safe place for it.
    return Command(
        update={"topic_plans": [plan]},
        goto=[
            Send("generate_subtopic_cards", {"subtopic_job": subtopic})
            for subtopic in plan["subtopics"]
        ],
    )


def fan_out_topics(state: PipelineState) -> list[Send]:
    return [
        Send("resolve_and_plan_topic", {"topic_job": request})
        for request in state["topic_requests"]
    ]


# ---------------------------------------------------------------- card generation --


async def generate_subtopic_cards(  # type: ignore[no-untyped-def]
    state: PipelineState, config
) -> dict[str, object]:
    """No DB access — see module docstring. Runs once per subtopic that still
    needs cards, potentially concurrently with every other such subtopic, across
    every topic in this run."""

    runtime = _runtime(config)
    job = state["subtopic_job"]
    difficulty = Difficulty(job["difficulty"])
    batch_size = runtime.settings.generation_batch_size
    target = job["target_cards"]

    if job["existing_count"] >= target:
        return {
            "card_results": [
                SubtopicCardsResult(
                    topic_id=job["topic_id"],
                    subtopic_id=job["subtopic_id"],
                    difficulty=job["difficulty"],
                    drafts=[],
                    generator_failures=[],
                )
            ]
        }

    drafts: list[CardDraft] = []
    failures: list[str] = []
    existing_titles = list(job["existing_titles"])
    # +1 round of slack: a batch that comes back short of `count` (partial failure,
    # ADR-0005) shouldn't need a perfectly-sized final call to still reach target.
    max_rounds = math.ceil(target / batch_size) + 1

    for _ in range(max_rounds):
        remaining = target - len(drafts)
        if remaining <= 0:
            break
        async with runtime.semaphore:
            result = await runtime.generator.generate_cards(
                topic_name=job["topic_name"],
                subtopic_title=job["title"],
                subtopic_description=job["description"],
                difficulty=difficulty,
                count=min(batch_size, remaining),
                existing_titles=existing_titles,
            )
        failures.extend(result.failures)
        if not result.items:
            break  # no usable progress this round (empty batch or all-malformed) — stop
        drafts.extend(result.items)
        existing_titles.extend(
            _existing_title_tag(d.canonical_title, d.title, d.difficulty) for d in result.items
        )

    return {
        "card_results": [
            SubtopicCardsResult(
                topic_id=job["topic_id"],
                subtopic_id=job["subtopic_id"],
                difficulty=job["difficulty"],
                drafts=drafts,
                generator_failures=failures,
            )
        ]
    }


async def gate_and_persist(  # type: ignore[no-untyped-def]
    state: PipelineState, config
) -> dict[str, object]:
    runtime = _runtime(config)
    generated_at = datetime.now(UTC).isoformat()

    by_topic: dict[str, list[SubtopicCardsResult]] = {}
    for result in state.get("card_results", []):
        by_topic.setdefault(result["topic_id"], []).append(result)

    topic_reports: list[dict[str, object]] = []
    for plan in state.get("topic_plans", []):
        topic_id = plan["topic_id"]
        total_accepted = 0
        total_rejected = 0
        subtopic_reports: list[dict[str, object]] = []

        for result in by_topic.get(topic_id, []):
            subtopic_id = uuid.UUID(result["subtopic_id"])
            drafts = result["drafts"]
            bodies = [draft.body for draft in drafts]
            embeddings = runtime.embedder.embed(bodies) if bodies else []

            new_cards: list[Card] = []
            rejected_reasons: list[str] = list(result["generator_failures"])
            for draft, embedding in zip(drafts, embeddings, strict=True):
                ok, reason = passes_minimal_gate(draft)
                if not ok:
                    rejected_reasons.append(reason or "failed minimal gate")
                    continue
                new_cards.append(
                    Card(
                        family_id=uuid.uuid4(),
                        topic_id=uuid.UUID(topic_id),
                        subtopic_id=subtopic_id,
                        difficulty=draft.difficulty,
                        status=CardStatus.ACTIVE,
                        title=draft.title,
                        canonical_title=draft.canonical_title,
                        summary=draft.summary,
                        body=draft.body,
                        visual_id=draft.visual_id,
                        visual_slots=draft.visual_slots,
                        content_embedding=embedding,
                        gen_meta={
                            "backend": runtime.settings.generator,
                            "generated_at": generated_at,
                            "batch_id": str(runtime.batch_id),
                        },
                    )
                )

            runtime.session.add_all(new_cards)
            await runtime.session.flush()
            for card in new_cards:
                card.archetype = classify_archetype(card.body)
                runtime.session.add(CardStats(card_id=card.id))

            total_accepted += len(new_cards)
            total_rejected += len(rejected_reasons)
            subtopic_reports.append(
                {
                    "subtopic_id": result["subtopic_id"],
                    "difficulty": result["difficulty"],
                    "accepted": len(new_cards),
                    "rejected": len(rejected_reasons),
                }
            )

        topic_reports.append(
            {
                "topic_id": topic_id,
                "topic_name": plan["topic_name"],
                "is_survey": plan["is_survey"],
                "deep_dive_topic_names": plan["deep_dive_topic_names"],
                "merged_into_existing": plan["merged_into_existing"],
                "accepted": total_accepted,
                "rejected": total_rejected,
                "subtopics": subtopic_reports,
            }
        )

    await runtime.session.flush()
    return {"report": {"topics": topic_reports}}


# ------------------------------------------------------------------- entrypoint --


def _build_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    graph = StateGraph(PipelineState)
    # destinations= documents resolve_and_plan_topic's dynamic Command(goto=...)
    # routing for graph introspection/visualization — it doesn't add a static
    # edge (Command handles that at runtime, per-branch).
    # NodeConfig (a plain dict alias, see its definition above) doesn't match
    # LangGraph's overloads, which want the real `RunnableConfig` type — the
    # narrower type import isn't worth pulling `langchain_core` into this module
    # for (see NodeConfig's docstring). Runtime behavior is unaffected: LangGraph
    # passes a plain dict-like config object regardless of the annotation.
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
    topic_requests: list[TopicRequest],
) -> dict[str, object]:
    """The public entrypoint. Callable directly from a CLI script (today) or a
    worker job handler (once GenerationJob wiring lands) — this function has no
    idea which is calling it. Accepts many topics at once so independent topics
    run as independent graph branches: one topic already fully curriculum'd and
    just topping up cards never waits on a sibling topic still doing its first
    curriculum pass.
    """

    if not topic_requests:
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
        "topic_requests": topic_requests,
        "topic_plans": [],
        "card_results": [],
    }
    final_state = await graph.ainvoke(initial_state, config={"configurable": {"runtime": runtime}})
    report: dict[str, object] = final_state["report"]
    return report
