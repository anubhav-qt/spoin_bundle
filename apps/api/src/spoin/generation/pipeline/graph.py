"""Graph construction and the run entrypoint.

The topology documented in this package's `__init__` is assembled here and
nowhere else: fan out per topic, fan out per subtopic group, fan in once for
the final report. Keeping it in its own module means the shape can be read
without scrolling past the ~1400 lines of work the nodes actually do.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.embeddings import Embedder
from spoin.generation.base import ContentGenerator
from spoin.generation.pipeline.nodes import (
    fan_out_topics,
    gate_and_persist,
    generate_subtopic_cards,
    resolve_and_plan_topic,
)
from spoin.generation.pipeline.state import PipelineState, _Runtime


def _build_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    graph = StateGraph(cast(type[Any], PipelineState))
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
    key_budgets: dict[uuid.UUID, int] | None = None,
) -> dict[str, object]:
    """ADR-0026's one-shot run: curriculum (if needed) -> cards -> questions,
    for topics that ALREADY EXIST (see `match_and_create_topics`). Callable
    directly from a CLI script (today) or a worker job handler (task 0008) --
    this function has no idea which is calling it, or whether a topic_id is
    brand new or a retry of one whose earlier attempt failed partway.

    `key_budgets` (ADR-0078) is the worker's per-topic key allocation, computed
    from each topic's widest difficulty tier. Absent (the CLI) or missing an
    entry means "use `settings.default_topic_key_budget`" -- the run corrects it
    against the real tier width once curriculum exists.
    """

    if not topic_ids:
        return {"topics": []}

    key_budgets = key_budgets or {}
    graph = _build_graph()
    runtime = _Runtime(
        session=session,
        generator=generator,
        embedder=embedder,
        settings=settings,
        batch_id=uuid.uuid4(),
    )
    initial_state: PipelineState = {
        "topic_ids": [str(topic_id) for topic_id in topic_ids],
        "topic_key_budgets": {
            str(topic_id): key_budgets.get(topic_id, settings.default_topic_key_budget)
            for topic_id in topic_ids
        },
        "topic_plans": [],
        "item_reports": [],
    }
    try:
        final_state = await graph.ainvoke(
            initial_state, config={"configurable": {"runtime": runtime}}
        )
    finally:
        # Every lease this run took is freed here, success or crash, so a run
        # that dies mid-flight doesn't strand keys the next worker pass needs
        # (ADR-0078). `gate_and_persist` releases on the happy path too; this is
        # the backstop and is idempotent (release of an already-empty lease is a
        # no-op).
        for lease in list(runtime.topic_leases.values()):
            await generator.release_topic_keys(lease)
        runtime.topic_leases.clear()
    report: dict[str, object] = final_state["report"]
    return report
