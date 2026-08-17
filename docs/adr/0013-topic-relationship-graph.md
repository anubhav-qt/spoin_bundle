# ADR-0013: Topic-relationship graph — request-time embedding similarity, topics as nodes

- **Status:** Superseded by [ADR-0014](0014-progress-insights-panel.md)
- **Date:** 2026-08-16
- **Deciders:** Anubhav

## Context

Building the three-column desktop shell (extending [ADR-0012](0012-feed-visual-design.md)),
the right rail needed a graphical "insights" widget. The first version explored in session
was a card/subtopic-level knowledge map — nodes for individual cards, edges for
prerequisite/sequel/related relationships within a topic. That was scoped back after
checking the content model: [content-model.md](../architecture/content-model.md) states
outright that "cards are standalone and unordered by design" and that `Subtopic.position`
is "only a curriculum-authoring hint" — a prequel/sequel reading order between cards would
contradict a stated design principle, not just be new work. The direction settled on
instead: **nodes are topics**, scoped to whatever the user currently has selected (or all
subscribed topics if none are selected), and the graph should visibly enrich as the user's
progress updates.

Two things were checked before deciding how to source topic-to-topic edges:

- `TopicEdge` (`apps/api/src/slocho/domain/models/topic.py`) is modeled for exactly this —
  its own docstring says "Edges are for discovery only" — but **nothing writes a row
  anywhere**: not generation, not `seed.py`. Zero rows exist today. Building the graph
  against it would ship an always-empty graph.
- `Topic.embedding` is real and populated — the same vector
  [ADR-0004](0004-topic-canonicalization.md)'s canonicalization uses. Cosine similarity
  between two topics' embeddings is a legitimate, cheap proxy for "these are related" and
  needs no new generation-time work or storage.

The catch: the default embedder
(`apps/api/src/slocho/core/config.py`, `embedder: EmbedderBackend = "hash"`) is
`HashEmbedder`, whose own docstring states it is "not semantically meaningful... any
threshold measured against this is meaningless." Task
[0001](../tasks/0001-topic-threshold-calibration.md) exists precisely because thresholds
against the _real_ embedder (`fastembed`) aren't calibrated yet either — that task
calibrates for canonicalization aliasing, a different consumer of the same embeddings.

## Decision

`GET /topics/graph` returns one node per requested topic (coverage, `quiz_unlocked`,
`mastered` — the same fields `/topics/{id}/progress` already computes, via a shared
`_progress_snapshot` helper) and one edge per topic pair whose embedding cosine similarity
clears `TOPIC_GRAPH_EDGE_THRESHOLD = 0.5`, computed **in Python at request time** over the
small in-memory set (never more topics than one user follows — no SQL self-join, no
stored edge table).

The threshold is explicitly provisional, not a calibrated fact:

- It borrows a plausible constant rather than waiting on task 0001, because this consumer
  (graph display) tolerates being wrong in a way canonicalization cannot — a spurious or
  missing edge just makes the picture slightly off, it never merges two real topics into
  one or silently misroutes generation.
- Under the default `hash` embedder (what `docker compose up` gives you without extra
  config), similarity between any two topics is effectively noise, so the graph's edges
  will look approximately random locally unless `EMBEDDER=fastembed` is set for the `api`
  service. This is a known, called-out limitation, not a bug to chase.

Node state ("enriches dynamically") comes from the client refetching a topic's progress
right after a card in that topic is marked seen (`Feed.tsx`'s `markSeen` → `AppShell`'s
`refreshProgress`), not from polling or anything new server-side.

## Consequences

**Easier**

- No new table, no migration, no generation-pipeline change — reuses two data sources
  (`Topic.embedding`, the existing progress computation) that already exist and are
  already correct for their original purposes.
- The graph degrades honestly: a topic with no embedding yet (nothing has triggered
  canonicalization/generation) still renders as a node, just with no edges to it.

**Harder**

- Edge weight is not a real "relatedness" signal until task 0001 lands and/or
  `TOPIC_GRAPH_EDGE_THRESHOLD` gets calibrated against it — right now it is a guess.
- Anyone testing locally with the default `hash` embedder will see a graph whose edges
  don't mean anything, which can read as a bug if this ADR isn't read first.
- If `TopicEdge` ever gets populated by real generation-time work, this endpoint has two
  possible sources of truth and needs to pick one (see Revisit below) rather than merging
  both silently.

## Alternatives considered

**Card/subtopic-level graph with prequel/sequel/related edges.** Rejected: contradicts
content-model.md's explicit "cards are standalone and unordered by design," and no data
exists to source real prerequisite semantics from — would need new generation-time work,
which is out of scope for a UI pass.

**Source edges from `TopicEdge`.** Rejected for now: zero rows exist anywhere in the
system, so the graph would ship permanently empty. Revisit the moment something starts
writing to that table.

**Wait for task 0001, ship the graph without edges until then.** Rejected: coverage alone
(nodes with no connective structure) drops the actual ask — the user wants a _relationship_
graph, not a topic list with fill bars. A provisional, clearly-flagged threshold beats
shipping something that isn't the feature.

## Revisit when

- Task 0001 lands and gives a calibrated similarity threshold — replace the constant and
  drop this ADR's "provisional" framing.
- Anything starts writing `TopicEdge` rows (a generation-time discovery step, most likely)
  — switch the edge source to that table, since it carries real curated meaning instead of
  a geometric proxy, and decide how (or whether) to blend it with embedding similarity.
- Real usage on the seeded (`hash`-embedder) stack shows the noisy-edges caveat is
  confusing enough in practice that local dev needs `fastembed` as its default rather than
  an opt-in env var.
