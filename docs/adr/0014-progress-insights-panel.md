# ADR-0014: Right-rail insights — a progress-stats panel, not a relationship graph

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Anubhav, Mayank

## Context

[ADR-0013](0013-topic-relationship-graph.md) built and shipped a topic-relationship graph
for the right rail: `GET /topics/graph`, request-time embedding-similarity edges, a
circular-layout SVG. It was working end-to-end (verified against the seeded stack) when
the product direction changed mid-session: the graph widget itself was the wrong shape for
the slot. What the right rail actually wants there is a compact, glanceable stats box —
cards read this session, topics mastered, quiz tiers passed — not a relationship diagram.

This is a same-session reversal, not a slow-burn architectural regret, so ADR-0013 is
superseded rather than amended (per `docs/adr/README.md`'s lifecycle rule: an Accepted ADR
is immutable, a changed decision gets a new one that points back).

## Decision

Replace the graph slot in the right rail with `InsightsPanel` — a fixed-height box of
small stat tiles, computed **entirely client-side** from data the app already fetches:

- **Cards read this session** — a `Set<cardId>` kept in `AppShell` (lifted up from
  `Feed`'s existing optimistic `seen` set, so a card counts once even if `markSeen` fires
  on it more than once).
- **Topics mastered** — count of `progress[topicId].mastered` across followed topics.
- **Quiz-ready topics** — count of `progress[topicId].quizUnlocked`.
- **Quiz tiers passed** — sum of `tier_quiz_passed` trues across followed topics (real
  field, already returned by `/topics/{id}/progress`; reads as `0` today because no
  quiz-taking flow exists yet to ever set it true — an honest zero, not a placeholder).

No new backend surface. `AppShell` already calls `api.progress(topicId)` once per topic on
load and again via `refreshProgress` after a card is marked seen (that refresh path
survives this ADR unchanged) — `mastered` and `tier_quiz_passed` just needed to be kept in
the lifted `progress` map alongside the `coverage`/`quizUnlocked` fields that were already
there.

`GET /topics/graph`, `TopicGraphOut`/`TopicGraphNodeOut`/`TopicGraphEdgeOut`, and the
cosine-similarity helper are **removed** (not deprecated-in-place) — nothing calls them
once `TopicGraph.tsx` is gone, and shipping an unused endpoint plus a stale "provisional
threshold" comment would actively mislead the next person who reads `topics.py`.

## Consequences

**Easier**
- Zero new backend work, zero new network calls beyond what already existed — the panel
  is a pure read of state `AppShell` already holds.
- No embedding-quality caveat to carry forward. ADR-0013's whole "meaningless under the
  default `hash` embedder" problem doesn't exist here, because nothing here depends on
  embeddings.
- A fixed-height box is trivial to keep visually stable as the rail's other widgets
  (theme picker, topic filter) change height — the graph's SVG had no such guarantee.

**Harder**
- "Quiz tiers passed" will show `0` for every user until a quiz-taking flow actually
  exists — accurate, but not very interesting yet. Revisit once that flow ships.
- The topic-relationship idea (which topics are conceptually near each other) is dropped
  entirely, not deferred to a later version of this widget — if that's wanted again later,
  it starts over from ADR-0013's research, not from this panel.

## Alternatives considered

**Keep the graph, add stats alongside it.** Rejected: the rail is a fixed ~350px column
with the theme picker and topic filter already competing for vertical space; a second
substantial widget doesn't fit without either widget getting cramped, and the direction
change was explicit about wanting the graph gone, not supplemented.

**Fetch the stats from a new backend aggregate endpoint.** Rejected: every number the
panel shows is already either in `AppShell`'s existing per-topic `progress` fetches or
derivable client-side from state the feed already has (the `seen` set). A new endpoint
would duplicate data the client already holds for no benefit.

## Revisit when

- A real quiz-taking flow ships — "quiz tiers passed" stops being permanently zero, and
  it's worth checking whether the stat is still the right one to surface (vs., say, "next
  quiz available" or a pass rate).
- If topic-relationship display comes back as a real ask later, treat it as new work and
  re-read ADR-0013 for what was already learned (embedding caveats, `TopicEdge` being
  unpopulated) rather than re-deriving it.
