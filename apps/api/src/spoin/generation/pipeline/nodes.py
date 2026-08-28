"""The graph's nodes, plus the correction / verification / gate passes they run.

One module per stage was considered and rejected: `generate_subtopic_cards`,
the two correction passes and `_process_gate_item` form a single sequence over
one subtopic group's drafts, and splitting them further would spread that
sequence across files without giving any of the pieces an independent reason to
exist. What they no longer contain is the persistence — that is
`persistence.py` — or the graph wiring, which is `graph.py`.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from langgraph.types import Command, Send
from sqlalchemy import func, select

from spoin.content.archetype import classify_archetype
from spoin.content.difficulty_examples import get_difficulty_examples
from spoin.domain.enums import (
    CardStatus,
    CardType,
    Difficulty,
    QuestionKind,
    QuestionStatus,
    RejectionStage,
)
from spoin.domain.models import Card, CardStats, Question, Topic
from spoin.generation.base import (
    CardCorrectionQuery,
    CardDraft,
    CardPlan,
    CardVerificationQuery,
)
from spoin.generation.dedup import find_batch_duplicate, find_corpus_duplicate
from spoin.generation.gate import passes_minimal_gate
from spoin.generation.pipeline.persistence import (
    _create_deep_dive_stubs,
    _current_question_stems,
    _existing_subtopic_hints,
    _load_subtopic_plans,
    _mark_progress_done,
    _recent_rejection_context,
    _reuse_or_create_subtopic,
    _seed_progress,
    _update_subtopic_progress,
)
from spoin.generation.pipeline.state import (
    _NO_DIFFICULTY_EXAMPLES,
    CARD_PROMPT_VERSION,
    PipelineState,
    SubtopicCardsResult,
    SubtopicGroupPlan,
    SubtopicPlan,
    TopicPlanResult,
    _card_matches_type,
    _clean_null_bytes,
    _existing_title_tag,
    _GateItem,
    _min_cards,
    _rejected_card,
    _Runtime,
    _runtime,
    logger,
)


async def _plan_tier_cards(
    runtime: _Runtime,
    *,
    topic_name: str,
    subtopic_title: str,
    subtopic_description: str,
    difficulty: Difficulty,
    count: int,
    type_quotas: dict[str, int],
    existing_titles: list[str],
    builds_on: list[str],
    avoid_bodies: list[str],
    rejection_feedback: list[tuple[str, str]],
) -> list[CardPlan]:
    """One planning call for a whole subtopic-tier (ADR-0059), returning the
    pool of briefs the writer rounds below draw from.

    Never raises for a planning failure and never fails the tier: an empty pool
    means the writer calls run unplanned, which is exactly the pre-ADR-0059
    behaviour. Planning improves what gets written; it is not a dependency of
    writing anything at all, and a tier that lost its quota to a planning call
    would be strictly worse than one that never planned.
    `QuotaExhaustedError` is deliberately NOT caught -- that is the run-level
    stop signal every other call in this pipeline propagates, not a per-call
    failure to shrug off.
    """

    result = await runtime.generator.plan_cards(
        topic_name=topic_name,
        subtopic_title=subtopic_title,
        subtopic_description=subtopic_description,
        difficulty=difficulty,
        count=count,
        type_quotas=type_quotas,
        existing_titles=existing_titles,
        builds_on=builds_on,
        avoid_bodies=avoid_bodies,
        rejection_feedback=rejection_feedback,
    )
    # Failures and an empty plan are DIFFERENT facts and logged as such
    # (CLAUDE.md: a "failed" outcome and a "rejected"/empty one are never the
    # same number) -- a planning call that errored out is a reliability signal;
    # one that returned nothing usable is a prompt signal.
    if result.failures:
        logger.warning(
            "subtopic '%s' [%s]: planning reported %d failure(s) -- %s",
            subtopic_title,
            difficulty.value,
            len(result.failures),
            "; ".join(result.failures[:3]),
        )
    if not result.items:
        logger.info(
            "subtopic '%s' [%s]: no usable plan -- writing unplanned",
            subtopic_title,
            difficulty.value,
        )
        return []
    logger.info(
        "subtopic '%s' [%s]: planned %d card(s) for a request of %d",
        subtopic_title,
        difficulty.value,
        len(result.items),
        count,
    )
    return result.items


def _take_plans(pool: list[CardPlan], card_type: str | None, count: int) -> list[CardPlan]:
    """Pull up to `count` briefs for the type this round is writing, REMOVING
    them from `pool` so no brief is ever written twice.

    Matching on type is best-effort by design: the planner was given the tier's
    quota as guidance, not as a rule (ADR-0059), so its mix can differ from what
    the round-robin below asks for. A round that finds no brief of its type
    falls back to any remaining brief rather than writing unplanned -- the
    concept the brief names is the valuable part, and the round's own
    `card_type` still drives the system prompt that shapes it.
    """

    if not pool:
        return []
    taken: list[CardPlan] = []
    if card_type is not None:
        for plan in list(pool):
            if len(taken) >= count:
                break
            if plan.card_type.strip().lower() == card_type:
                pool.remove(plan)
                taken.append(plan)
    while pool and len(taken) < count:
        taken.append(pool.pop(0))
    return taken


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
        logger.info("topic '%s': generating curriculum...", topic.canonical_name)
        async with runtime.topic_plan_lock:
            existing_subtopic_hints = await _existing_subtopic_hints(runtime.session, topic.id)
        draft = await runtime.generator.generate_curriculum(
            topic.canonical_name, topic.description or "", existing_subtopic_hints or None
        )
        total_tiers = sum(len(group.tiers) for group in draft.subtopics)
        logger.info(
            "topic '%s': curriculum generated -- %d subtopic group(s), %d tier(s) total, "
            "survey=%s, %d deep-dive topic(s) proposed",
            topic.canonical_name,
            len(draft.subtopics),
            total_tiers,
            draft.is_survey,
            len(draft.deep_dive_topics),
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
                    subtopic.card_type_quotas = tier.card_type_quotas or None
                    subtopic.min_cards = _min_cards(
                        tier.target_cards, runtime.settings.min_cards_fraction
                    )
                    subtopic.position = group.position
            topic.curriculum_generated_at = datetime.now(UTC)
            await runtime.session.flush()
            # Committed immediately, not left pending until gate_and_persist's
            # fan-in: card generation runs next with no DB access at all, so a
            # crash anywhere in that phase would otherwise discard a fully
            # generated curriculum along with it (a real gap this closes --
            # see docs/tasks and the run this fix accompanies).
            await runtime.session.commit()
            deep_dive_names = draft.deep_dive_topics
            is_survey = draft.is_survey

    async with runtime.topic_plan_lock:
        subtopic_plans = await _load_subtopic_plans(
            runtime.session,
            topic,
            max_duplicate_feedback_bodies=runtime.settings.max_duplicate_feedback_bodies,
            max_verification_feedback_bodies=runtime.settings.max_verification_feedback_bodies,
            max_existing_question_stems=runtime.settings.max_existing_question_stems,
        )
        await _seed_progress(runtime, topic.id, topic.canonical_name, subtopic_plans)
        await runtime.session.commit()

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
            topic_description=plan["topic_description"],
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


async def generate_subtopic_cards(  # type: ignore[no-untyped-def]
    state: PipelineState, config
) -> dict[str, object]:
    """Runs once per subtopic GROUP that still needs cards, potentially
    concurrently with every other such group, across every topic in this run.
    Tiers WITHIN one group run sequentially, lowest difficulty first, so a
    linked higher tier's `generate_cards` call can receive the lower tier's
    actual card bodies as `builds_on` (ADR-0026) -- groups with only one tier
    (the common case; curricula are never forced to give a concept all three
    tiers) are unaffected, there's nothing to sequence.

    DOES have DB access, via `_gate_and_persist_results` at the end -- ADR-
    0026's decision is that cards persist and go live in the feed as soon as
    their own subtopic/tier's batch completes, not held back until every
    OTHER group/topic in this run also finishes drafting. This function used
    to just return drafts for a separate global writer node to pick up later;
    now it gates+persists its OWN group's cards and questions itself, before
    returning. `gate_and_persist` (still the only function containing the
    actual gate/persist logic -- this just calls it earlier and more often)
    is left as a final, lightweight aggregation-and-mark-done step.
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
    #: Per-tier state the redraft loop below needs after this first round's
    #: gate call -- keyed by subtopic_id (one entry per tier that actually
    #: drafted this round; an already-full tier from the `continue` above
    #: never enters the redraft loop, it has nothing left to close).
    tier_meta: dict[str, dict[str, object]] = {}

    all_card_types = [
        CardType.PROSE.value,
        CardType.CODE.value,
        CardType.DIAGRAM.value,
        CardType.COMPARISON.value,
        CardType.ASCII.value,
    ]

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
                    cards_missing_questions=tier["cards_missing_questions"],
                    existing_question_stems=tier["existing_question_stems"],
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
        # The actual DEFICIT this call should draft -- not the tier's full
        # `target_cards`. A fresh tier (existing_count == 0) has want == target,
        # unchanged from before; a tier a LATER pass is topping up (existing_count
        # > 0, e.g. a scan_and_generate backfill re-invoking this same topic_id)
        # must only draft what's still missing, or every re-run drafts a whole
        # extra `target_cards`-sized batch on top of what's already active --
        # confirmed live: a topic backfilled a second time landed three tiers at
        # roughly DOUBLE their target_cards before this fix.
        want = target - tier["existing_count"]

        # Determine target quotas for each card type in this tier, scaled to
        # the deficit being drafted THIS call, not the tier's full target --
        # otherwise a topped-up tier's type mix skews toward whatever `want`
        # happens to round-robin into rather than the intended split.
        tier_quotas = dict(tier.get("card_type_quotas") or {})
        if not tier_quotas or sum(tier_quotas.values()) != target:
            base_qty = want // len(all_card_types)
            rem = want % len(all_card_types)
            tier_quotas = {
                ct: base_qty + (1 if i < rem else 0) for i, ct in enumerate(all_card_types)
            }
        elif want != target:
            # Original per-type quotas summed to the full target -- rescale
            # proportionally to the deficit so a topping-up call doesn't chase
            # the FULL original quota per type on top of cards already active.
            scale = want / target
            scaled = {ct: round(qty * scale) for ct, qty in tier_quotas.items()}
            drift = want - sum(scaled.values())
            if drift and scaled:
                # Rounding can leave the sum off by a card or two -- put the
                # difference on the type with the largest quota rather than
                # leaving `want` unmet or overshot.
                biggest = max(scaled, key=lambda ct: scaled[ct])
                scaled[biggest] = max(0, scaled[biggest] + drift)
            tier_quotas = scaled

        # The pre-processing gate (ADR-0059): plan the whole deficit in one
        # call before any of it is written, so the writer rounds below are
        # each handed a brief instead of re-inventing the tier's coverage from
        # a list of titles that happen to already exist. Deliberately placed
        # AFTER `tier_quotas` is settled -- the plan is asked to match the
        # shape budget this call actually intends to fill.
        plan_pool = await _plan_tier_cards(
            runtime,
            topic_name=job["topic_name"],
            subtopic_title=tier["title"],
            subtopic_description=tier["description"],
            difficulty=difficulty,
            count=want,
            type_quotas=tier_quotas,
            existing_titles=existing_titles,
            builds_on=lower_tier_bodies,
            avoid_bodies=tier["avoid_duplicate_bodies"],
            rejection_feedback=[
                (entry["body"], entry["reason"]) for entry in tier["rejection_feedback"]
            ],
        )

        # One-time hero call (task 0006 / ADR-0018), before this tier's
        # normal rounds. Gated on `existing_count == 0` (not just `has_hero`)
        # so it only fires the first time this subtopic-tier is ever
        # generated -- literally its first card -- rather than retrofitting
        # a late hero onto a tier that already accumulated ordinary cards
        # under the old (no-op) `is_hero` behavior.
        if tier["existing_count"] == 0 and not tier["has_hero"]:
            hero_result = await runtime.generator.generate_cards(
                topic_name=job["topic_name"],
                subtopic_title=tier["title"],
                subtopic_description=tier["description"],
                difficulty=difficulty,
                count=1,
                existing_titles=existing_titles,
                builds_on=lower_tier_bodies,
                difficulty_examples=difficulty_examples,
                avoid_bodies=tier["avoid_duplicate_bodies"],
                rejection_feedback=[
                    (entry["body"], entry["reason"]) for entry in tier["rejection_feedback"]
                ],
                want_hero=True,
            )
            # The model is asked for exactly 1 card here but is trusted for
            # taste, never for constraints (CLAUDE.md) -- a batch call can
            # still return more than one despite `count=1`. Every item in
            # this result is stamped `is_hero=True` (langchain_impl.py), so
            # letting extras through would mint more than one hero for this
            # subtopic-tier, violating the one-hero invariant. Keep only the
            # first; the rest are dropped, not persisted anywhere.
            hero_items = hero_result.items[:1]
            if len(hero_result.items) > 1:
                logger.warning(
                    "subtopic '%s' [%s]: hero call returned %d cards for a count=1 "
                    "request -- keeping only the first, dropping %d extra(s)",
                    tier["title"],
                    difficulty.value,
                    len(hero_result.items),
                    len(hero_result.items) - 1,
                )
            logger.info(
                "subtopic '%s' [%s]: hero card -- %d card(s), %d generator failure(s)",
                tier["title"],
                difficulty.value,
                len(hero_items),
                len(hero_result.failures),
            )
            failures.extend(hero_result.failures)
            drafts.extend(hero_items)
            existing_titles.extend(
                _existing_title_tag(d.canonical_title, d.title, d.difficulty) for d in hero_items
            )

        # Unbounded drafting: cycle through card types until the deficit is filled
        round_number = 0
        while len(drafts) < want:
            round_number += 1
            remaining = want - len(drafts)

            # Find card types that still have remaining capacity to fill
            unfilled_types = [
                ct
                for ct in all_card_types
                if tier_quotas.get(ct, 0) > 0
                and sum(1 for d in drafts if _card_matches_type(d, ct)) < tier_quotas[ct]
            ]

            if unfilled_types:
                # Pick the unfilled card type with the largest remaining deficit
                chosen_type = max(
                    unfilled_types,
                    key=lambda ct: (
                        tier_quotas[ct] - sum(1 for d in drafts if _card_matches_type(d, ct))
                    ),
                )
                unmet = tier_quotas[chosen_type] - sum(
                    1 for d in drafts if _card_matches_type(d, chosen_type)
                )
                request_count = min(batch_size, remaining, max(1, unmet))
            else:
                chosen_type = None
                request_count = min(batch_size, remaining)

            round_plans = _take_plans(plan_pool, chosen_type, request_count)
            logger.info(
                "subtopic '%s' [%s]: round %d (type=%s) -- requesting %d card(s) "
                "(%d planned, %d/%d so far, existing=%d target=%d)",
                tier["title"],
                difficulty.value,
                round_number,
                chosen_type or "general",
                request_count,
                len(round_plans),
                len(drafts),
                want,
                tier["existing_count"],
                target,
            )
            result = await runtime.generator.generate_cards(
                topic_name=job["topic_name"],
                subtopic_title=tier["title"],
                subtopic_description=tier["description"],
                difficulty=difficulty,
                count=request_count,
                existing_titles=existing_titles,
                builds_on=lower_tier_bodies,
                difficulty_examples=difficulty_examples,
                avoid_bodies=tier["avoid_duplicate_bodies"],
                rejection_feedback=[
                    (entry["body"], entry["reason"]) for entry in tier["rejection_feedback"]
                ],
                card_type=chosen_type,
                plans=round_plans,
            )
            logger.info(
                "subtopic '%s' [%s]: round %d got %d card(s), %d generator failure(s)",
                tier["title"],
                difficulty.value,
                round_number,
                len(result.items),
                len(result.failures),
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
                cards_missing_questions=tier["cards_missing_questions"],
                existing_question_stems=tier["existing_question_stems"],
            )
        )
        lower_tier_bodies = lower_tier_bodies + [draft.body for draft in drafts]
        tier_meta[tier["subtopic_id"]] = {
            "tier": tier,
            "difficulty": difficulty,
            "target": target,
            "existing_count": tier["existing_count"],
            "existing_titles": existing_titles,
        }

    # Gate+persist THIS group's results right now (ADR-0026) rather than
    # handing them to a later global writer -- see this function's docstring.
    generated_at = datetime.now(UTC).isoformat()
    item_reports = await _gate_and_persist_results(
        runtime,
        topic_name=job["topic_name"],
        topic_description=job["topic_description"],
        results=results,
        generated_at=generated_at,
        backend=runtime.settings.generator,
        threshold=runtime.settings.card_duplicate_threshold,
    )
    item_reports = await _redraft_until_bar(
        runtime,
        tier_meta=tier_meta,
        item_reports=item_reports,
        topic_name=job["topic_name"],
        topic_description=job["topic_description"],
        generated_at=generated_at,
        is_standalone=is_standalone,
        difficulty_examples=difficulty_examples,
        batch_size=batch_size,
    )
    return {"item_reports": item_reports}


#: A tier stops redrafting once this many consecutive rounds accept zero
#: cards for it -- one or two unlucky rounds can happen by chance (a small
#: batch, a borderline dedup call), so the guard needs enough consecutive
#: misses to actually distinguish "this tier cannot pass the gate right now"
#: from ordinary variance before it gives up on it for the run. Shared between
#: `stuck_rounds` (gate rejected every draft -- a REJECTED outcome) and
#: `no_verdict_rounds` (the generator call itself returned nothing -- a
#: FAILED outcome, e.g. quota exhaustion or the ADR-0056 client timeout) --
#: same threshold, but tracked as two separate counters so the give-up log
#: names which one actually happened instead of asserting rejection when the
#: real cause was a call that never returned a verdict (CLAUDE.md's "failed
#: vs rejected are never the same number" rule).
_STUCK_ROUND_THRESHOLD = 5

#: Pure defensive backstop against a bug in `_redraft_until_bar`'s own
#: per-tier stuck guard letting a loop run away -- not user-configurable,
#: should never actually trigger in normal operation (the stuck guard
#: resolves in at most `_STUCK_ROUND_THRESHOLD` unproductive rounds per
#: tier). If this ever fires, it means the stuck guard itself is broken,
#: not that a subtopic is legitimately taking this long.
_ABSOLUTE_MAX_REDRAFT_ROUNDS = 200


async def _redraft_until_bar(
    runtime: _Runtime,
    *,
    tier_meta: dict[str, dict[str, object]],
    item_reports: list[dict[str, object]],
    topic_name: str,
    topic_description: str,
    generated_at: str,
    is_standalone: bool,
    difficulty_examples: dict[Difficulty, list[str]],
    batch_size: int,
) -> list[dict[str, object]]:
    """The round above drafts every tier to its full `target_cards` exactly
    once and gates once -- the quality gate then rejects some fraction with
    no loop-back to draft replacements, so a run routinely lands short of
    target even though it "completed" (docs/tasks/0023). This closes that
    gap per subtopic-tier, redrafting round after round -- accepted cards
    only ever go up, never lost, so more rounds strictly cannot make a tier
    worse -- until it clears its bar:

    - A tier with no cards before this run started (`existing_count == 0` --
      its first-ever pass) only has to clear
      `settings.first_pass_completion_fraction` (90% by default). Some
      shortfall on a first pass is normal -- the gate rejecting a fraction
      of every batch isn't a bug -- so a first pass doesn't have to chase
      literal 100% itself.
    - A tier that already had cards before this run started (a LATER pass --
      e.g. a `scan_and_generate` backfill picking the topic back up) chases
      the full 100%: this run IS "the next time a worker picks it back up,"
      so it should not hand off early again.

    Neither case has a round limit. There are two independent stop
    conditions, each `_STUCK_ROUND_THRESHOLD` consecutive rounds:
    - `stuck_rounds`: the gate accepted zero of this tier's drafts -- the
      content is genuinely, repeatedly rejected for a real reason (e.g. the
      missing difficulty-example catalog, task 0011), not an unlucky round or
      two. Logged as REJECTED.
    - `no_verdict_rounds`: the generator call itself came back with zero
      items -- quota exhaustion, a malformed batch response, the ADR-0056
      client-side timeout. The gate never saw this content at all, so it is
      not evidence the content is bad. Logged as FAILED, distinctly (CLAUDE.md's
      "failed vs rejected are never the same number" rule) -- conflating the
      two would misread a quota-exhausted run's give-up log as a content-
      quality problem instead of an availability one.
    `_ABSOLUTE_MAX_REDRAFT_ROUNDS` is a pure defensive backstop against a bug
    in either guard, not a real operating limit -- see its own docstring.
    """

    if not tier_meta:
        return item_reports

    accepted_by_tier: dict[str, int] = {}
    for report in item_reports:
        sid = cast(str, report["subtopic_id"])
        if sid in tier_meta:
            accepted_by_tier[sid] = accepted_by_tier.get(sid, 0) + cast(int, report["accepted"])
    stuck_rounds: dict[str, int] = dict.fromkeys(tier_meta, 0)
    no_verdict_rounds: dict[str, int] = dict.fromkeys(tier_meta, 0)
    all_reports = list(item_reports)

    for round_number in range(1, _ABSOLUTE_MAX_REDRAFT_ROUNDS + 1):
        deficits: dict[str, int] = {}
        for sid, meta in tier_meta.items():
            if (
                stuck_rounds[sid] >= _STUCK_ROUND_THRESHOLD
                or no_verdict_rounds[sid] >= _STUCK_ROUND_THRESHOLD
            ):
                continue
            target = cast(int, meta["target"])
            existing_count = cast(int, meta["existing_count"])
            is_first_pass = existing_count == 0
            total_active = existing_count + accepted_by_tier.get(sid, 0)
            fraction = runtime.settings.first_pass_completion_fraction if is_first_pass else 1.0
            bar = min(target, math.ceil(target * fraction))
            if total_active < bar:
                deficits[sid] = bar - total_active

        if not deficits:
            break

        logger.info(
            "redraft round %d: %d subtopic-tier(s) still under their completion bar -- %s",
            round_number,
            len(deficits),
            deficits,
        )

        round_results: list[SubtopicCardsResult] = []
        for sid, want in deficits.items():
            meta = tier_meta[sid]
            tier = cast(SubtopicPlan, meta["tier"])
            difficulty = cast(Difficulty, meta["difficulty"])
            existing_titles = cast(list[str], meta["existing_titles"])
            count = min(want, batch_size)

            async with runtime.session_lock:
                avoid_bodies, rejection_feedback = await _recent_rejection_context(
                    runtime.session,
                    subtopic_id=uuid.UUID(sid),
                    max_duplicate_feedback_bodies=runtime.settings.max_duplicate_feedback_bodies,
                    max_verification_feedback_bodies=runtime.settings.max_verification_feedback_bodies,
                )
                # Re-queried fresh each round, same reasoning as the
                # rejection context above: round 1 (and any earlier redraft
                # round) may have just persisted new Question rows for this
                # SAME tier, and this round's own question generation needs
                # to avoid repeating those angles, not just whatever existed
                # before this run started.
                existing_question_stems = await _current_question_stems(
                    runtime.session,
                    subtopic_id=uuid.UUID(sid),
                    max_existing_question_stems=runtime.settings.max_existing_question_stems,
                )

            # Redraft rounds plan too (ADR-0059), rather than only the first
            # pass. A tier that lands short is exactly the one whose remaining
            # cards are hardest to place -- everything easy was already
            # written and accepted -- and this is the only call that sees the
            # tier's fresh rejection context BEFORE deciding what to attempt
            # next. Leaving redrafts unplanned would also mean a v2 tier is a
            # mix of planned and unplanned cards, which would muddy exactly
            # the comparison `prompt_version` exists to make.
            round_plans = await _plan_tier_cards(
                runtime,
                topic_name=topic_name,
                subtopic_title=tier["title"],
                subtopic_description=tier["description"],
                difficulty=difficulty,
                count=count,
                type_quotas={},
                existing_titles=existing_titles,
                builds_on=[],
                avoid_bodies=avoid_bodies,
                rejection_feedback=rejection_feedback,
            )
            result = await runtime.generator.generate_cards(
                topic_name=topic_name,
                subtopic_title=tier["title"],
                subtopic_description=tier["description"],
                difficulty=difficulty,
                count=count,
                existing_titles=existing_titles,
                builds_on=[],
                difficulty_examples=(
                    difficulty_examples if is_standalone else _NO_DIFFICULTY_EXAMPLES
                ),
                avoid_bodies=avoid_bodies,
                rejection_feedback=rejection_feedback,
                plans=round_plans,
            )
            logger.info(
                "redraft round %d: subtopic '%s' [%s] -- requested %d, got %d card(s), "
                "%d generator failure(s)",
                round_number,
                tier["title"],
                difficulty.value,
                count,
                len(result.items),
                len(result.failures),
            )
            if not result.items:
                no_verdict_rounds[sid] += 1
                if no_verdict_rounds[sid] >= _STUCK_ROUND_THRESHOLD:
                    logger.info(
                        "redraft: subtopic %s giving up after %d consecutive round(s) with no "
                        "generator verdict at all -- the CALL is FAILING (quota, timeout, or a "
                        "malformed response), not the gate rejecting content -- see the "
                        "generator failure log lines above, not rejected_card rows",
                        sid,
                        no_verdict_rounds[sid],
                    )
                continue
            existing_titles.extend(
                _existing_title_tag(d.canonical_title, d.title, d.difficulty) for d in result.items
            )
            round_results.append(
                SubtopicCardsResult(
                    topic_id=tier["topic_id"],
                    subtopic_id=sid,
                    difficulty=tier["difficulty"],
                    drafts=result.items,
                    generator_failures=result.failures,
                    is_standalone=is_standalone,
                    # Round 1 already drained this tier's pre-run
                    # missing-question backfill; a redraft round only ever
                    # adds brand-new cards, so there is nothing left to
                    # backfill here.
                    cards_missing_questions=[],
                    existing_question_stems=existing_question_stems,
                )
            )

        if not round_results:
            continue  # every deficit tier's call returned nothing this round

        round_reports = await _gate_and_persist_results(
            runtime,
            topic_name=topic_name,
            topic_description=topic_description,
            results=round_results,
            generated_at=generated_at,
            backend=runtime.settings.generator,
            threshold=runtime.settings.card_duplicate_threshold,
        )
        for report in round_reports:
            sid = cast(str, report["subtopic_id"])
            accepted_this_round = cast(int, report["accepted"])
            accepted_by_tier[sid] = accepted_by_tier.get(sid, 0) + accepted_this_round
            stuck_rounds[sid] = 0 if accepted_this_round > 0 else stuck_rounds[sid] + 1
            if stuck_rounds[sid] >= _STUCK_ROUND_THRESHOLD:
                logger.info(
                    "redraft: subtopic %s giving up after %d consecutive round(s) with no "
                    "accepted cards -- the gate is REJECTING this tier's content for a real "
                    "reason (see its rejected_card rows), not failing to run",
                    sid,
                    stuck_rounds[sid],
                )
        all_reports.extend(round_reports)
    else:
        # The loop ran out of rounds without `break`ing (every tier cleared
        # its bar or hit a stuck guard) -- per this function's own docstring,
        # this should never happen; if it does, the stuck guards themselves
        # have a bug and are letting a tier spin instead of giving up on it.
        # Logged loudly rather than silently returning under-target, which is
        # exactly the "completed but nothing says why" gap task 0023 is about.
        logger.warning(
            "redraft: hit _ABSOLUTE_MAX_REDRAFT_ROUNDS (%d) without every tier clearing its "
            "bar or its stuck guard -- this indicates a bug in the stuck guard logic, not a "
            "legitimately slow subtopic; still-deficient tiers: %s",
            _ABSOLUTE_MAX_REDRAFT_ROUNDS,
            deficits,
        )

    return all_reports


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
        result = await runtime.generator.correct_cards(
            queries, difficulty_examples=difficulty_examples
        )
        chunk_failures = list(result.failures)
        failures.extend(result.failures)
        by_index = {item.index: item for item in result.items}
        edited_count = 0
        for index, draft in enumerate(chunk):
            correction = by_index.get(index)
            if correction is None:
                reason = f"correction pass returned no result for card {index}"
                failures.append(reason)
                chunk_failures.append(reason)
                continue
            if correction.was_edited:
                edited_count += 1
                logger.info(
                    "gate: pass 1 edited '%s' (subtopic %s) -- %s",
                    correction.canonical_title,
                    subtopic_id,
                    correction.note or "no note given",
                )
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
        logger.info(
            "gate: pass 1 correction for subtopic %s -- %d/%d card(s) edited this chunk, "
            "%d failure(s)",
            subtopic_id,
            edited_count,
            len(chunk),
            len(result.failures),
        )
        if chunk_failures:
            # The count above says HOW MANY; this says WHY -- same gap task
            # 0012 already found and fixed for question generation, applied
            # here too. Without this, a whole-call failure (e.g. quota
            # exhaustion) is indistinguishable in the log from N genuinely
            # malformed per-card corrections.
            logger.warning(
                "gate: pass 1 correction for subtopic %s had failure(s): %s",
                subtopic_id,
                "; ".join(chunk_failures),
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
        result = await runtime.generator.verify_cards(
            queries, difficulty_examples=difficulty_examples
        )
        chunk_failures = list(result.failures)
        failures.extend(result.failures)
        by_index = {item.index: item for item in result.items}
        chunk_accepted = 0
        for index, (draft, embedding) in enumerate(chunk):
            verdict = by_index.get(index)
            if verdict is None:
                reason = f"verification pass returned no result for card {index}"
                failures.append(reason)
                chunk_failures.append(reason)
                continue
            if not verdict.accepted:
                reason = verdict.reason or "failed verification"
                logger.info(
                    "gate: pass 2 REJECTED '%s' (subtopic %s) -- %s",
                    draft.canonical_title,
                    subtopic_id,
                    reason,
                )
                rejected.append((draft, reason))
                continue
            if verdict.confirmed_difficulty != draft.difficulty:
                logger.info(
                    "gate: pass 2 accepted '%s' (subtopic %s) but re-rated difficulty %s -> %s",
                    draft.canonical_title,
                    subtopic_id,
                    draft.difficulty.value,
                    verdict.confirmed_difficulty.value,
                )
            chunk_accepted += 1
            accepted.append((draft, embedding, verdict.confirmed_difficulty))
        logger.info(
            "gate: pass 2 verification for subtopic %s -- %d/%d accepted this chunk, %d failure(s)",
            subtopic_id,
            chunk_accepted,
            len(chunk),
            len(result.failures),
        )
        if chunk_failures:
            # Same reasoning as pass 1's warning above: a whole-call failure
            # (e.g. quota exhaustion) must not read the same as "every card
            # in this chunk was judged bad content" -- the two get folded
            # together downstream into one "rejected" number, so the actual
            # reason has to survive here in the log or it's lost entirely.
            logger.warning(
                "gate: pass 2 verification for subtopic %s had failure(s): %s",
                subtopic_id,
                "; ".join(chunk_failures),
            )

    return subtopic_id, accepted, rejected, failures


async def _generate_questions_for_group(
    runtime: _Runtime,
    *,
    topic_id: str,
    subtopic_id: str,
    difficulty: str,
    cards: list[tuple[uuid.UUID, str, str]],
    existing_stems: list[str],
    is_backfill: bool,
) -> tuple[str, str, str, list[tuple[Any, uuid.UUID]], list[str]]:
    """Concurrent, no DB writes -- `cards` is `(id, title, body)` rather than
    ORM `Card` rows so this works identically whether the cards were just
    persisted THIS run or are existing active cards fetched from the DB for
    missing-question backfill (see `SubtopicPlan.cards_missing_questions`).
    One subtopic/difficulty's worth of questions, batched per
    `question_batch_size` same as card generation batches per
    `generation_batch_size`.

    `is_backfill` applies to the WHOLE call, never per-card -- callers (see
    `_process_gate_item`) always call this once for newly-drafted cards and,
    separately, once for `cards_missing_questions` backfill, never a mix of
    both in one call. `existing_stems` grows across the two calls within one
    tier (see `_process_gate_item`) so the SECOND call also avoids repeating
    whatever the first one just wrote, not just prior runs' questions."""

    batch_size = runtime.settings.question_batch_size
    parsed_difficulty = Difficulty(difficulty)
    drafts: list[tuple[Any, uuid.UUID]] = []
    failures: list[str] = []

    for start in range(0, len(cards), batch_size):
        chunk = cards[start : start + batch_size]
        result = await runtime.generator.generate_questions(
            cards=[(title, body) for _card_id, title, body in chunk],
            difficulty=parsed_difficulty,
            existing_stems=existing_stems,
            is_backfill=is_backfill,
        )
        failures.extend(result.failures)
        for draft in result.items:
            if 0 <= draft.card_index < len(chunk):
                drafts.append((draft, chunk[draft.card_index][0]))

    return topic_id, subtopic_id, difficulty, drafts, failures


async def _process_gate_item(
    runtime: _Runtime,
    item: _GateItem,
    *,
    generated_at: str,
    backend: str,
    threshold: float,
) -> dict[str, object]:
    """One subtopic-tier's entire trip through the gate (ADR-0030) --
    correction, dedup, verification, persist, then question generation --
    run start to finish independently of every sibling subtopic-tier.
    Concurrent across tiers via `asyncio.gather` in `gate_and_persist`: the
    LLM phases (correction, verification, question generation) touch no DB
    and run fully concurrently (rate limits governed by QuotaGovernor);
    dedup and persist touch `runtime.session`,
    which is not safe for concurrent use across coroutines, so those
    sections are serialized through `runtime.session_lock` instead of
    running as one sequential pass over every tier.

    Deliberately not a fifth global barrier: committing per tier as soon as
    ITS OWN phases finish means a crash in one tier's LLM call (or the whole
    grid running out of quota) only loses that tier's spend, not every
    tier's correction+verification calls sitting uncommitted behind it.
    """

    if item.survivors:
        _, corrected, failures = await _correct_subtopic_drafts(
            runtime,
            subtopic_id=item.subtopic_id,
            topic_name=item.topic_name,
            topic_description=item.topic_description,
            difficulty_examples=item.difficulty_examples,
            drafts=item.survivors,
        )
        item.corrected = corrected
        item.correction_failure_count = len(failures)

    if item.corrected:
        bodies = [draft.body for draft in item.corrected]
        embeddings = await runtime.embedder.aembed(bodies)
        accepted_embeddings: list[list[float]] = []
        subtopic_uuid = uuid.UUID(item.subtopic_id)
        async with runtime.session_lock:
            for draft, embedding in zip(item.corrected, embeddings, strict=True):
                corpus_hit = await find_corpus_duplicate(
                    runtime.session,
                    subtopic_id=subtopic_uuid,
                    embedding=embedding,
                    threshold=threshold,
                )
                if corpus_hit is not None:
                    reason = f"near-duplicate of an existing card (similarity {corpus_hit:.3f})"
                    logger.info(
                        "gate: near-dup REJECTED '%s' (subtopic %s) -- %s",
                        draft.canonical_title,
                        item.subtopic_id,
                        reason,
                    )
                    item.dedup_rejects.append((draft, reason))
                    continue
                batch_hit = find_batch_duplicate(
                    embedding, accepted_embeddings, threshold=threshold
                )
                if batch_hit is not None:
                    reason = f"near-duplicate within this batch (similarity {batch_hit:.3f})"
                    logger.info(
                        "gate: near-dup REJECTED '%s' (subtopic %s) -- %s",
                        draft.canonical_title,
                        item.subtopic_id,
                        reason,
                    )
                    item.dedup_rejects.append((draft, reason))
                    continue
                accepted_embeddings.append(embedding)
                item.dedup_survivors.append((draft, embedding))

    if item.dedup_survivors:
        _, verified, verify_rejects, verify_failures = await _verify_subtopic_drafts(
            runtime,
            subtopic_id=item.subtopic_id,
            difficulty_examples=item.difficulty_examples,
            items=item.dedup_survivors,
        )
        item.verified = verified
        item.verification_rejects = verify_rejects
        item.verification_failure_count = len(verify_failures)

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

    new_cards = [
        Card(
            family_id=uuid.uuid4(),
            topic_id=uuid.UUID(item.topic_id),
            subtopic_id=uuid.UUID(item.subtopic_id),
            difficulty=draft.difficulty,
            judged_difficulty=confirmed_difficulty,
            status=CardStatus.ACTIVE,
            title=_clean_null_bytes(draft.title[:120]),
            canonical_title=_clean_null_bytes(draft.canonical_title[:160]),
            summary=_clean_null_bytes(draft.summary),
            body=_clean_null_bytes(draft.body),
            archetype=classify_archetype(_clean_null_bytes(draft.body)),
            visual_id=_clean_null_bytes(draft.visual_id[:64]) if draft.visual_id else None,
            visual_slots=_clean_null_bytes(draft.visual_slots),
            is_hero=draft.is_hero,
            content_embedding=embedding,
            gen_meta={
                "backend": backend,
                "generated_at": generated_at,
                "batch_id": str(runtime.batch_id),
                "prompt_version": CARD_PROMPT_VERSION,
            },
        )
        for draft, embedding, confirmed_difficulty in item.verified
    ]

    async with runtime.session_lock:
        runtime.session.add_all(rejected_rows)
        runtime.session.add_all(new_cards)
        await runtime.session.flush()
        for card in new_cards:
            runtime.session.add(CardStats(card_id=card.id))
        await runtime.session.flush()
        # Committed as soon as THIS tier's cards are written -- a crash
        # anywhere else in this batch (a different tier, question
        # generation) no longer discards cards already gated here.
        await runtime.session.commit()
        # Recomputed via COUNT rather than trusted as a delta on top of
        # whatever `_seed_progress` wrote -- same reasoning as
        # `EngagementService._bump_progress`: a real, cheap read beats a
        # running total that can drift out of sync with the table it
        # describes. `questions_target` becomes exactly this count: every
        # active card gets exactly one question, backfill included.
        cards_done = await runtime.session.scalar(
            select(func.count())
            .select_from(Card)
            .where(
                Card.subtopic_id == uuid.UUID(item.subtopic_id),
                Card.status == CardStatus.ACTIVE,
            )
        )
        await _update_subtopic_progress(
            runtime,
            uuid.UUID(item.topic_id),
            item.subtopic_id,
            cards_done=cards_done or 0,
            questions_target=cards_done or 0,
        )
        await runtime.session.commit()

    # Genuinely REJECTED (a check ran and judged the content bad) is kept
    # separate from FAILED (the check never ran at all -- e.g. quota
    # exhaustion, a malformed whole-batch response). Folding these together
    # previously made a run that hit quota exhaustion mid-gate look like a
    # content-quality catastrophe in the persisted report, when in fact
    # nothing had been judged bad -- see the pass 1/2 failure-reason
    # warnings above for where to find out WHY a call failed.
    total_rejected = (
        len(item.structural_rejects) + len(item.dedup_rejects) + len(item.verification_rejects)
    )
    total_failed = (
        item.correction_failure_count
        + item.verification_failure_count
        + item.generator_failure_count
    )
    logger.info(
        "subtopic %s [%s]: persisted %d card(s), rejected %d "
        "(structural=%d near_dup=%d verification=%d), failed %d "
        "(correction=%d verification=%d generator=%d)",
        item.subtopic_id,
        item.difficulty,
        len(new_cards),
        total_rejected,
        len(item.structural_rejects),
        len(item.dedup_rejects),
        len(item.verification_rejects),
        total_failed,
        item.correction_failure_count,
        item.verification_failure_count,
        item.generator_failure_count,
    )

    questions_accepted = 0
    questions_rejected = 0
    # Question generation runs on cards accepted THIS run plus any existing
    # active cards under this tier still missing a question (backfill --
    # see SubtopicPlan.cards_missing_questions) -- a tier that was already
    # fully carded (new_cards empty) can still have work to do here. Kept as
    # TWO separate calls (never mixed in one) so `is_backfill` is accurate for
    # the whole call -- the writer needs to know whether it's looking at
    # brand-new content or already-accepted cards that just lack a question,
    # and those two cases genuinely call for different framing (see
    # `generate_questions`'s docstring in base.py).
    new_cards_for_questions: list[tuple[uuid.UUID, str, str]] = [
        (card.id, card.title, card.body) for card in new_cards
    ]
    backfill_cards_for_questions: list[tuple[uuid.UUID, str, str]] = [
        (uuid.UUID(entry["card_id"]), entry["title"], entry["body"])
        for entry in item.existing_cards_missing_questions
    ]
    all_question_drafts: list[tuple[Any, uuid.UUID]] = []
    all_question_failures: list[str] = []
    # Grows across the two calls below so the SECOND call also avoids
    # repeating whatever the FIRST just wrote, not just prior runs' stems.
    running_existing_stems = list(item.existing_question_stems)
    for cards_batch, is_backfill in (
        (new_cards_for_questions, False),
        (backfill_cards_for_questions, True),
    ):
        if not cards_batch:
            continue
        _, _, _, question_drafts, question_failures = await _generate_questions_for_group(
            runtime,
            topic_id=item.topic_id,
            subtopic_id=item.subtopic_id,
            difficulty=item.difficulty,
            cards=cards_batch,
            existing_stems=running_existing_stems,
            is_backfill=is_backfill,
        )
        all_question_drafts.extend(question_drafts)
        all_question_failures.extend(question_failures)
        running_existing_stems = running_existing_stems + [
            draft.stem for draft, _card_id in question_drafts
        ]

    if all_question_drafts or all_question_failures:
        parsed_difficulty = Difficulty(item.difficulty)
        stems = [draft.stem for draft, _card_id in all_question_drafts]
        embeddings = await runtime.embedder.aembed(stems) if stems else []
        new_questions = [
            Question(
                subtopic_id=uuid.UUID(item.subtopic_id),
                card_id=card_id,
                difficulty=parsed_difficulty,
                kind=QuestionKind.MCQ if draft.options is not None else QuestionKind.FREE_TEXT,
                stem=_clean_null_bytes(draft.stem),
                options=_clean_null_bytes(draft.options),
                correct_index=draft.correct_index,
                rubric=_clean_null_bytes(draft.rubric),
                reference_answer=_clean_null_bytes(draft.reference_answer),
                explanation=_clean_null_bytes(draft.explanation),
                status=QuestionStatus.ACTIVE,
                embedding=embedding,
                gen_meta={
                    "backend": backend,
                    "generated_at": generated_at,
                    "batch_id": str(runtime.batch_id),
                    "prompt_version": CARD_PROMPT_VERSION,
                },
            )
            for (draft, card_id), embedding in zip(all_question_drafts, embeddings, strict=True)
        ]
        async with runtime.session_lock:
            runtime.session.add_all(new_questions)
            await runtime.session.flush()
            await runtime.session.commit()
            questions_done = await runtime.session.scalar(
                select(func.count())
                .select_from(Question)
                .where(Question.subtopic_id == uuid.UUID(item.subtopic_id))
            )
            await _update_subtopic_progress(
                runtime,
                uuid.UUID(item.topic_id),
                item.subtopic_id,
                questions_done=questions_done or 0,
            )
            await runtime.session.commit()
        questions_accepted = len(new_questions)
        questions_rejected = len(all_question_failures)
        if all_question_failures:
            logger.info(
                "subtopic %s [%s]: %d question failure(s): %s",
                item.subtopic_id,
                item.difficulty,
                len(all_question_failures),
                "; ".join(all_question_failures),
            )

    return {
        "topic_id": item.topic_id,
        "subtopic_id": item.subtopic_id,
        "difficulty": item.difficulty,
        "accepted": len(new_cards),
        "rejected": total_rejected,
        "failed": total_failed,
        "questions_accepted": questions_accepted,
        "questions_rejected": questions_rejected,
    }


async def _gate_and_persist_results(
    runtime: _Runtime,
    *,
    topic_name: str,
    topic_description: str,
    results: list[SubtopicCardsResult],
    generated_at: str,
    backend: str,
    threshold: float,
) -> list[dict[str, object]]:
    """The actual gate+persist work (ADR-0030's two-pass quality gate --
    structural check, pass 1 correction, near-duplicate detection, pass 2
    verification -- persisting every draft as exactly one of an ACTIVE
    `Card` or a `RejectedCard` row, then questions FROM the cards just
    accepted). Called from `generate_subtopic_cards`, once per subtopic
    GROUP, immediately after that group finishes drafting -- NOT from a
    later global writer node, so cards go live in the feed (ADR-0026) as
    soon as their own group is done rather than waiting on every other
    group/topic in the run. Still the only function containing this logic --
    "one writer" (ADR-0026/0030) describes this function's exclusivity, not
    how many times or when it's called.

    Every subtopic-tier in `results` (all belonging to one group, so at most
    three -- one per difficulty) runs `_process_gate_item` concurrently with
    its siblings, instead of four global correct-everything / dedup-
    everything / verify-everything / persist-everything barriers. See that
    function's docstring for why: a crash partway through a large batch
    should only cost the tiers still in flight, not every tier's already-
    spent LLM calls sitting uncommitted behind the slowest one.
    """

    items: list[_GateItem] = []
    for result in results:
        survivors: list[CardDraft] = []
        structural_rejects: list[tuple[CardDraft, str]] = []
        for draft in result["drafts"]:
            ok, reason = passes_minimal_gate(draft)
            if ok:
                survivors.append(draft)
            else:
                structural_rejects.append((draft, reason or "failed structural gate"))

        examples = get_difficulty_examples() if result["is_standalone"] else _NO_DIFFICULTY_EXAMPLES
        items.append(
            _GateItem(
                topic_id=result["topic_id"],
                subtopic_id=result["subtopic_id"],
                difficulty=result["difficulty"],
                topic_name=topic_name,
                topic_description=topic_description,
                difficulty_examples=examples,
                survivors=survivors,
                structural_rejects=structural_rejects,
                generator_failure_count=len(result["generator_failures"]),
                existing_cards_missing_questions=result["cards_missing_questions"],
                existing_question_stems=result["existing_question_stems"],
            )
        )

    total_drafts = sum(len(item.survivors) + len(item.structural_rejects) for item in items)
    total_structural_rejects = sum(len(item.structural_rejects) for item in items)
    logger.info(
        "gate: topic '%s' -- %d draft(s) across %d subtopic-tier(s) -- %d failed the "
        "structural check",
        topic_name,
        total_drafts,
        len(items),
        total_structural_rejects,
    )

    if not items:
        return []

    return list(
        await asyncio.gather(
            *(
                _process_gate_item(
                    runtime, item, generated_at=generated_at, backend=backend, threshold=threshold
                )
                for item in items
            )
        )
    )


async def gate_and_persist(  # type: ignore[no-untyped-def]
    state: PipelineState, config
) -> dict[str, object]:
    """Final, lightweight step: every group's cards/questions are ALREADY
    persisted by the time this runs (`generate_subtopic_cards` does that
    itself now, via `_gate_and_persist_results`, per ADR-0026 -- see its
    docstring). This node only aggregates `item_reports` into the run's final
    per-topic report and marks each topic's `GenerationJob.progress` done.
    Still a fan-in (every group/topic branch merges here) -- that's correct
    for THIS purpose, since the final report and "done" marking genuinely do
    need everything finished, unlike the card/question writes themselves.
    """

    runtime = _runtime(config)
    item_reports = state.get("item_reports", [])

    reports_by_topic: dict[str, list[dict[str, object]]] = {}
    totals_by_topic: dict[str, tuple[int, int, int, int, int]] = {}
    for report in item_reports:
        topic_id = cast(str, report["topic_id"])
        reports_by_topic.setdefault(topic_id, []).append(
            {
                "subtopic_id": report["subtopic_id"],
                "difficulty": report["difficulty"],
                "accepted": report["accepted"],
                "rejected": report["rejected"],
                "failed": report["failed"],
            }
        )
        prev_accepted, prev_rejected, prev_failed, prev_q_accepted, prev_q_rejected = (
            totals_by_topic.get(topic_id, (0, 0, 0, 0, 0))
        )
        totals_by_topic[topic_id] = (
            prev_accepted + cast(int, report["accepted"]),
            prev_rejected + cast(int, report["rejected"]),
            prev_failed + cast(int, report["failed"]),
            prev_q_accepted + cast(int, report["questions_accepted"]),
            prev_q_rejected + cast(int, report["questions_rejected"]),
        )

    topic_reports: list[dict[str, object]] = []
    for plan in state.get("topic_plans", []):
        topic_id = plan["topic_id"]
        total_accepted, total_rejected, total_failed, q_accepted, q_rejected = totals_by_topic.get(
            topic_id, (0, 0, 0, 0, 0)
        )
        topic_reports.append(
            {
                "topic_id": topic_id,
                "topic_name": plan["topic_name"],
                "is_survey": plan["is_survey"],
                "deep_dive_topic_names": plan["deep_dive_topic_names"],
                "accepted": total_accepted,
                "rejected": total_rejected,
                "failed": total_failed,
                "subtopics": reports_by_topic.get(topic_id, []),
                "questions_accepted": q_accepted,
                "questions_rejected": q_rejected,
            }
        )
        logger.info(
            "topic '%s' done -- %d card(s) accepted, %d rejected, %d failed (not judged -- "
            "e.g. quota exhaustion), %d question(s) accepted, %d rejected",
            plan["topic_name"],
            total_accepted,
            total_rejected,
            total_failed,
            q_accepted,
            q_rejected,
        )

    if topic_reports:
        async with runtime.session_lock:
            for plan in state.get("topic_plans", []):
                await _mark_progress_done(runtime, uuid.UUID(plan["topic_id"]))
            await runtime.session.commit()

    return {"report": {"topics": topic_reports}}
