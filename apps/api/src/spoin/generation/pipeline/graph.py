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
    )
    initial_state: PipelineState = {
        "topic_ids": [str(topic_id) for topic_id in topic_ids],
        "topic_plans": [],
        "item_reports": [],
    }
    final_state = await graph.ainvoke(initial_state, config={"configurable": {"runtime": runtime}})
    report: dict[str, object] = final_state["report"]
    return report
