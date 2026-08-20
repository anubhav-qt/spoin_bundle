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

**`langgraph` is confined to this package**, the same way ADR-0002 confines
`langchain*` to `langchain_impl.py` -- and within it, to just two files:
`graph.py` (StateGraph, START/END) and `nodes.py` (Send/Command, the fan-out
primitives the nodes return). Nothing here imports `langchain*` at all; the
package only calls the `ContentGenerator` interface, so it has no idea whether
Gemini, local, or `FakeContentGenerator` is behind it.

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
generate_subtopic_cards   Concurrent across groups AND topics. Within one
                          group, tiers run SEQUENTIALLY, lowest difficulty
                          first, because a linked higher tier's card
                          generation receives the lower tier's actual card
                          BODIES as context (ADR-0026) -- it has to exist
                          first. Groups with only one tier (the common case)
                          are unaffected: nothing to sequence. Gates+persists
                          its OWN group's cards (minimal gate, then the
                          correction/verification passes -- see
                          generation/gate.py and ADR-0030) and questions
                          itself, right here, before returning -- cards go
                          live in the feed as soon as THIS group is done
                          (ADR-0026), not held back for every other group or
                          topic in the run to also finish.
  |
  | fan-in (every branch's item_reports merge, across every topic in the run)
  v
gate_and_persist          Everything is ALREADY persisted by this point --
                           this is just final aggregation: builds the run's
                           per-topic report from every group's item_reports,
                           and marks each topic's GenerationJob done. Fan-in
                           is correct HERE (unlike for the writes themselves)
                           because the final report and "done" marking
                           genuinely do need everything finished.
```
"""

# ---------------------------------------------------------------------------
# Split out of a single 1955-line module. The layering below is strict and
# acyclic — each file only imports from the ones above it:
#
#     state.py        types, _Runtime, pure helpers      (no DB, no model)
#     persistence.py  every database read and write      (no model)
#     topic_match.py  ADR-0025's cheap matching entrypoint
#     nodes.py        graph nodes + correction/verify/gate passes
#     graph.py        topology and run entrypoint
#
# This module re-exports the public surface so every existing
# `from spoin.generation.pipeline import ...` keeps working unchanged.
# ---------------------------------------------------------------------------

from __future__ import annotations

from spoin.generation.pipeline.graph import run_generation_pipeline
from spoin.generation.pipeline.nodes import (
    fan_out_topics,
    gate_and_persist,
    generate_subtopic_cards,
    resolve_and_plan_topic,
)
from spoin.generation.pipeline.state import (
    PipelineState,
    SubtopicCardsResult,
    SubtopicGroupPlan,
    SubtopicPlan,
    TopicMatchOutcome,
    TopicPlanResult,
    TopicRequest,
)
from spoin.generation.pipeline.topic_match import match_and_create_topics

__all__ = [
    "PipelineState",
    "SubtopicCardsResult",
    "SubtopicGroupPlan",
    "SubtopicPlan",
    "TopicMatchOutcome",
    "TopicPlanResult",
    "TopicRequest",
    "fan_out_topics",
    "gate_and_persist",
    "generate_subtopic_cards",
    "match_and_create_topics",
    "resolve_and_plan_topic",
    "run_generation_pipeline",
]
