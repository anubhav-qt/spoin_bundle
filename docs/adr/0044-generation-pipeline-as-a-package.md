# ADR-0044: The generation pipeline becomes a package; `langgraph` confined to two files

- **Status:** Accepted
- **Date:** 2026-08-21
- **Deciders:** mayanks0ni
- **Amends:** [ADR-0024](0024-langgraph-for-card-generation-pipeline.md) — its import
  boundary named a single file (`generation/pipeline.py`) that no longer exists. The
  boundary itself is unchanged in spirit and *narrower* in practice; only the path
  changes. Everything else ADR-0024 decided (worker owns scheduling, no persisted
  checkpointer, LangGraph owns one job's control flow) stands untouched.

## Context

`generation/pipeline.py` had grown to **1,955 lines and 35 top-level definitions**. It
held, in one file: the graph topology, every node body, ADR-0025's topic matcher, the
correction and verification passes, the gate, and 33 SQL statements' worth of
persistence. `_process_gate_item` alone was 312 lines.

The cost was not aesthetic. ADR-0024's whole argument is that the graph's *shape* —
fan out per topic, fan out per subtopic group, fan in once — is the thing worth
expressing declaratively. That shape was invisible: `_build_graph` sat at line 1906,
below fourteen hundred lines of the work the nodes do. The module docstring drew the
topology in ASCII precisely because the code no longer showed it.

A second, quieter problem: ADR-0024 committed to "`pipeline.py` is the only place
`langgraph` is imported," enforced by a ruff `banned-api` rule keyed to that exact path.
That rule is only as good as the path it names.

## Decision

**`generation/pipeline.py` becomes `generation/pipeline/`, a package with a strict,
acyclic layering.** Each module may only import from the ones above it:

```
state.py         TypedDicts, _Runtime, pure helpers      no DB, no model
persistence.py   every database read and write           no model
topic_match.py   ADR-0025's match_and_create_topics
nodes.py         graph nodes + correction/verify/gate passes
graph.py         topology and run_generation_pipeline
__init__.py      re-exports the public surface
```

`__init__.py` re-exports `run_generation_pipeline`, `match_and_create_topics`,
`TopicRequest` and the state types, so **every existing import site is unchanged** — the
worker, the CLI, `topics/service.py` and three test modules all still say
`from spoin.generation.pipeline import ...`.

**The `langgraph` boundary tightens rather than widens.** The ruff ignore is not globbed
to the package; it names two files:

```toml
"src/spoin/generation/pipeline/graph.py" = ["TID251"]   # StateGraph, START/END
"src/spoin/generation/pipeline/nodes.py" = ["TID251"]   # Send/Command
```

The other four modules cannot import `langgraph` at all. ADR-0024 permitted it anywhere
in a 1,955-line file; this permits it in two files totalling the graph wiring and the
fan-out primitives the nodes return.

**The split is mechanical, not a rewrite.** Every function body moved byte-for-byte —
verified by comparing the AST of each definition before and after, which showed exactly
three differences, all of them a separate, deliberate change made in the same pass
(`embedder.embed(...)` → `await embedder.aembed(...)`, moving CPU-bound embedding off
the event loop). No behaviour was altered while the file was open.

## Consequences

**Easier**

- `graph.py` is 76 lines. The topology ADR-0024 argued for is now readable in one screen,
  next to nothing else.
- The "nodes cannot touch the `AsyncSession`" constraint ADR-0024 flagged as a real
  hazard — get it wrong and cards are written by a corrupted session — is now visible in
  the module layout: persistence is a layer nodes call, not code interleaved with them.
- A future retry/top-up cycle (ADR-0024's named extension point) is a change to
  `graph.py`, not surgery inside a 2,000-line file.

**Harder**

- Six files where there was one. `nodes.py` is still 1,095 lines — this ADR does not
  claim to have finished the job, only to have separated the parts with genuinely
  different reasons to change. Splitting the gate out further is a real option and
  deliberately not taken here (see Alternatives).
- A definition moving between modules can now trip the `langgraph` ban if it carries a
  `Send` with it. That is the intended behaviour, but it is a new way to be surprised.
- `git log --follow` on the old path is one rename deeper.

**Committed to**

- The layering above stays acyclic. `state.py` imports nothing from its own package.
- `langgraph` appears in `graph.py` and `nodes.py` and nowhere else. Superseding this
  requires an ADR, not a glob.
- `__init__.py` stays a re-export surface with no logic in it, so the public API of the
  package is one file you can read.

## Alternatives considered

**Leave it as one file.** The honest default — the module was working, well commented,
and covered by tests. Rejected because the specific thing ADR-0024 decided (make the
control flow declarative and legible) had stopped being true, which makes it the rare
case where file layout is an architectural concern rather than the local choice the ADR
README correctly says not to write ADRs about.

**Split by stage into one module per node** (`curriculum.py`, `cards.py`, `gate.py`,
`questions.py`). Rejected: `generate_subtopic_cards`, the two correction passes and
`_process_gate_item` are one sequence over a single subtopic group's drafts. Splitting
them puts one control flow across four files and gives none of the pieces an independent
reason to exist. The seam that actually exists is *persistence vs. work vs. wiring*, and
that is the seam taken.

**Glob the ruff ignore to the package** (`pipeline/*.py`). Simpler to write and what was
tried first. Rejected on principle once it also turned out not to match: a package-wide
exemption would let `langgraph` spread to `persistence.py` or `state.py` with nothing
objecting, which is exactly the erosion ADR-0002 and ADR-0024 wrote a banned-api rule to
prevent.

## Revisit when

- `nodes.py` needs a second split — most likely when the gate grows a new pass, since
  `_process_gate_item` is already the largest thing in the package.
- A node genuinely needs to import `langgraph` for something other than `Send`/`Command`,
  which would mean the graph is doing more than fan-out and the two-file ignore is
  hiding it.
- `__init__.py` acquires logic. That is the signal the re-export surface has become a
  module in its own right and the package boundary needs redrawing.
