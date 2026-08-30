# ADR-0041: Gate+persist per subtopic group, not after a global fan-in

- **Status:** Accepted
- **Date:** 2026-08-20
- **Deciders:** Anubhav
- **Amended by:** [ADR-0074](0074-key-per-subtopic-scheduling.md) -- per-group
  gate+persist for CARDS is unchanged and still the point of this ADR. Question
  generation moves out of the per-group path to a topic-wide phase at the fan-in.
- **Fixes a drift from:** [ADR-0026](0026-one-shot-generation-to-completion.md), whose own
  Decision section already states "cards persist and go live in the feed as soon as their
  subtopic/tier's batch completes" — the graph wiring never actually implemented that.

## Context

Running a two-topic generation pass and checking the DB mid-run surfaced that **zero**
cards had persisted despite dozens of subtopic-tiers having already finished drafting
(visible in the logs as "hero card --" and "round N got M card(s)" lines). Tracing the
graph (`_build_graph()`) showed why: `generate_subtopic_cards` (one branch per subtopic
group, fanned out via `Send`, across every topic in the run) fed its results into
`card_results`, a reducer-accumulated state key that only `gate_and_persist` reads — and
`gate_and_persist` is wired with a plain `add_edge`, which in LangGraph is a fan-in: it
does not run until **every** `generate_subtopic_cards` branch, across every topic and every
group, has returned.

That is a global barrier between "draft everything" and "gate+persist everything" — the
opposite of what ADR-0026 decided. Its Decision section is explicit: card serving and
question generation should proceed "as soon as cards for a tier exist," not wait on the
rest of the run. The code had drifted from the doc it was supposed to implement.

## Decision

**`generate_subtopic_cards` gates and persists its own group's cards and questions itself,
immediately, before returning** — by calling `_gate_and_persist_results` (the gate/dedup/
persist logic extracted, unchanged, from the old `gate_and_persist` body) at the end of its
own function, instead of only returning draft `CardDraft`s for someone else to process
later.

`gate_and_persist` stays in the graph as the final node, still reached via the same
fan-in edge — but by the time it runs, every card and question this run will write is
**already committed**. Its only remaining job is aggregating each group's `item_reports`
into the run's final per-topic report and marking each topic's `GenerationJob.progress`
done. Fan-in is the right shape for that specific purpose (a topic's final report and
"done" flag genuinely do need every one of its groups finished) — it was only wrong as a
gate on the actual DB writes.

`PipelineState.card_results` (raw drafts, accumulated globally) is replaced by
`item_reports` (small per-tier report dicts — accepted/rejected/failed counts, not card
content) for exactly that narrower final purpose. `SubtopicGroupPlan` gained
`topic_description`, threaded from `resolve_and_plan_topic`, since a `Send`-invoked branch
only sees its own payload (not the graph's accumulated state) and `generate_subtopic_cards`
now needs it directly to gate its own group instead of looking it up from `topic_plans`
later.

The "one writer" rule from ADR-0026/0030 is preserved in spirit: `_gate_and_persist_results`
/ `_process_gate_item` remain the *only* functions containing gate/persist logic — this
changes how many times and when that logic runs (once per group, as soon as the group is
ready), not how many places contain it.

## Consequences

**Easier**

- Cards and questions now actually appear in the DB/feed incrementally, matching what
  ADR-0026 already promised and what the live-progress UI implies is happening.
- A crash or quota exhaustion partway through a large multi-topic run now loses only the
  groups still drafting, not every group's already-gated-and-persisted work sitting behind
  a barrier that never got reached.
- Gating for one group can now overlap with drafting for another, rather than strictly
  waiting — a minor throughput win, not the primary motivation.

**Harder**

- `gate_and_persist`'s final report and "topic done" marking are now visibly decoupled from
  when a topic's cards actually became servable — a topic can be fully playable in the feed
  well before its `GenerationJob.progress` reads "done." Not a new problem (ADR-0026 already
  intended this gap to exist), but now it's real instead of theoretical, and anything reading
  `progress.stage` for a "can I serve this topic yet" decision would be wrong to do so.
- One more function (`generate_subtopic_cards`) now touches the DB and needs to reason about
  `runtime.session_lock`, where before only `gate_and_persist`'s call tree did. The lock
  itself already handles this safely (unchanged), but the "no DB access" invariant that used
  to make this function trivially safe to reason about is gone.

## Alternatives considered

**Restructure the graph so `gate_and_persist` itself is `Send`-fanned per group** (one
invocation per group, routed directly from `generate_subtopic_cards` via `Command.goto`,
instead of inlining the call). Rejected as unnecessary complexity: it would need a separate
mechanism to detect "every group of THIS topic has now gated" for the final per-topic report
and done-marking, which a plain function call from inside `generate_subtopic_cards` gets for
free by just... calling it inline and returning the report alongside everything else that
node already returns.

**Persist drafts as they're generated, per round, inside `generate_subtopic_cards`'s round
loop** (finer-grained than per-group). Rejected: the quality gate's correction/dedup/
verification passes work in batches for a real reason (ADR-0005's batching economics,
ADR-0030's calibration), and a subtopic-tier's own rounds aren't independent of each other
(later rounds see `existing_titles` from earlier ones) — per-group is the natural unit
ADR-0026 already specified ("subtopic/tier's batch"), not per-round.

## Revisit when

- `GenerationJob.progress` semantics get relied on for a "can this topic be served yet"
  decision anywhere in the read path — the note above needs to become an actual check
  against real committed card counts instead, not the job's `stage` field.
- A future change reintroduces a reason to batch gate/persist across MULTIPLE groups again
  (e.g. a quality-gate pass that benefits from seeing more than one group's cards at once) —
  would need to reopen this ADR's "per group" granularity, not silently work around it.
