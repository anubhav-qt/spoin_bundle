"""Graph construction and the run entrypoint.

The topology documented in this package's `__init__` is assembled here and
nowhere else: fan out per topic, fan out per subtopic group, fan in once for
the final report. Keeping it in its own module means the shape can be read
without scrolling past the ~1400 lines of work the nodes actually do.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from frog.embeddings import Embedder
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.embeddings import get_corpus_embedder
from spoin.generation.base import ContentGenerator
from spoin.generation.grounding import Grounding
from spoin.generation.pipeline.nodes import (
    fan_out_topics,
    gate_and_persist,
    generate_subtopic_cards,
    resolve_and_plan_topic,
)
from spoin.generation.pipeline.state import PipelineState, _Runtime, logger


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

    Every topic gets a KEY BOX first (ADR-0082): `settings.topic_key_box_size`
    keys that its subtopic branches -- and nothing else -- draw on for the whole
    run. Taken here rather than inside `resolve_and_plan_topic` because a box's
    lifetime is the RUN's, not a node's: one place takes them, one `finally`
    gives them back, and a crash anywhere in between cannot strand keys the next
    worker pass needs.
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
        #: One per RUN, which is what makes its per-subtopic cache correct: the
        #: cache is only valid while the corpus is fixed, and a run is the
        #: natural lifetime for that assumption (it re-checks the corpus version
        #: anyway, because the worker outlives any one run).
        grounding=Grounding(
            #: NOT `embedder`: that one writes `card.content_embedding` (384 dims
            #: today), and the corpus is 1024. See `get_corpus_embedder`.
            get_corpus_embedder(),
            token_budget=settings.grounding_token_budget,
            max_chunks=settings.grounding_max_chunks,
        ),
    )
    initial_state: PipelineState = {
        "topic_ids": [str(topic_id) for topic_id in topic_ids],
        "topic_plans": [],
        "item_reports": [],
    }
    for topic_id in topic_ids:
        box = await generator.lease_key_box(settings.topic_key_box_size)
        if box.key_indices:
            runtime.topic_boxes[str(topic_id)] = box
            logger.info(
                "topic %s: key box %d -- %d key(s) (ADR-0082)",
                topic_id,
                box.box_id,
                len(box.key_indices),
            )
        else:
            # Either a backend with no key pool (`fake`, local -- `box_id` 0, the
            # no-op base implementation) or a pool with nothing free right now.
            # Both mean the same downstream: this topic's branches fall back to
            # ADR-0074's whole-pool claim. Only the second is worth a line, and
            # only as an observation -- the worker admits at most
            # `pool // box_size` jobs precisely so it stays rare.
            await generator.release_key_box(box)
            if box.box_id:
                logger.warning(
                    "topic %s: no keys free to box -- this topic's branches will scan the "
                    "whole pool instead (ADR-0082 fallback)",
                    topic_id,
                )

    try:
        final_state = await graph.ainvoke(
            initial_state, config={"configurable": {"runtime": runtime}}
        )
    finally:
        # Success or crash, every key this run boxed goes back now. A run that
        # dies mid-branch must not leave a third of the pool owned by nobody
        # until the process exits.
        for box in runtime.topic_boxes.values():
            await generator.release_key_box(box)
        runtime.topic_boxes.clear()
    report: dict[str, object] = final_state["report"]
    return report
