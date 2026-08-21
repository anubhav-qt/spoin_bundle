# ADR-0043: Routers are transport; every domain gets a service module

- **Status:** Accepted
- **Date:** 2026-08-21
- **Deciders:** mayanks0ni

## Context

Four of the six API domains already followed a layering nobody had written down. `feed`,
`engagement`, `notes` and `profile` each had a service module holding the queries and the
domain rules, and a router that parsed, delegated and serialized — `routers/feed.py` held
6 SQL statements, `routers/notes.py` held 2.

Two domains did not:

| | lines | SQL statements in the router |
|---|---|---|
| `routers/topics.py` | 709 | 48 |
| `routers/quiz.py` | 476 | 20 |

`submit_free_text` was the clearest case: 148 lines doing HTTP validation, a per-user
daily quota check, five database queries, **a direct LLM call**, ADR-0009's
prompt-injection heuristic, the weighted scoring arithmetic, the entire tier-progression
state machine (promotion advances `current_difficulty`, mastery latches `mastered_at`,
placement attempts touch neither), a remediation lookup, and the commit.

That progression state machine is the part that mattered. It is a domain rule — the same
rules `engagement/service.py` reasons about — and it was reachable **only through an HTTP
request**. It could not be unit tested, called from a worker, or exercised without a live
generator. Its float-rounding subtlety (`0.7 + 0.3 * (1/3)` is `0.7999999999999999`, which
fails a `>= 0.80` pass mark the user genuinely earned) had a comment explaining it and no
test pinning it, because pinning it required Postgres and an LLM.

The coupling had already leaked: `routers/quiz.py` imported `ensure_unlock_latched` from
`routers/topics.py`. Two transport modules importing each other to share a domain rule is
precisely the shape a service layer exists to prevent.

## Decision

**A router parses the request, calls one service, and serializes the result. Queries and
domain rules live in a service module named for its domain.**

```
api/routers/quiz.py     141 lines, 0 SQL   ->  quiz/service.py    lifecycle, scoring,
                                               quiz/grading.py    progression, injection guard
api/routers/topics.py   128 lines, 0 SQL   ->  topics/service.py  subscriptions, discovery,
                                                                  tier progression
```

Both routers now depend on `topics/service.py` for `ensure_unlock_latched`; neither
imports the other.

**Services may raise `HTTPException`.** This is a deliberate exception to the usual
"transport types don't belong in the domain" instinct, and it matches what `NotesService`
already did. The status codes here *are* the API contract the client depends on — 403
tier-not-reached, 409 already-graded, 429 daily cap — and introducing
`QuizTierLockedError` only to translate it back into the same 403 one layer up adds a
file and a lookup table without changing behaviour or enabling a caller that doesn't
exist yet.

**Read methods may return `*Out` schemas.** They are plain Pydantic DTOs with no FastAPI
coupling, and `ProfileService` already returned them. Defining a parallel dataclass for
each of eight response shapes doubles the type count and changes nothing.

## Consequences

**Easier**

- The rules are testable without HTTP. `test_quiz_grading.py` needs no database, no LLM
  and no fixtures; the rounding regression above is now a four-line assertion. The
  coverage gate and the unlock latch are pinned directly in `test_topics_service.py`,
  including the case the latch exists for — 8/10 unlocked must survive ten more cards
  landing and becoming 8/20.
- A worker or an admin path can call these rules. Today nothing does, which is exactly
  why it was easy not to notice they were unreachable.
- Reviewing a router diff means reading ~15 lines, not auditing whether a query changed.

**Harder**

- Two more modules per domain, and one more hop to read when tracing a request.
- The `HTTPException`-in-a-service exception is a judgement call that will look wrong to
  anyone applying the general rule without reading this. It is written down here so the
  argument can be had once.
- `TopicsService` is 700 lines. It is a faithful move, not a redesign, and it inherits
  every shape the router had — including `request_topic`, which still calls the generator
  inline (ADR-0025) and is the one method here that is not pure serving-layer work.

**Committed to**

- New endpoints put their queries in a service, not the router.
- No router imports another router.
- Services stay free of `Request`, `Response`, `Depends` and status-code *branching*;
  raising a status is allowed, reading transport state is not.

## Alternatives considered

**Repositories under the services.** The obvious next layer, and rejected. The queries
here are used by exactly one caller each and are mostly single joins; a repository would
add indirection whose only benefit is a swappable persistence backend nobody wants —
this codebase is Postgres-only by design (pgvector, `DISTINCT ON`, partial indexes). The
problem was queries living in *transport*, which a service fixes; it was never that they
live in SQLAlchemy.

**A domain-exception hierarchy plus a FastAPI exception handler.** The textbook answer.
Rejected for the reason in the Decision: every exception would map one-to-one onto the
status it replaced, so the mapping layer is pure ceremony until a non-HTTP caller exists.
Revisit condition below.

**Leave `quiz.py` and `topics.py` alone and document the inconsistency.** Genuinely
considered — they worked and were well tested through the API. Rejected because the
progression state machine is the highest-risk logic in the product and was the least
testable code in it.

## Revisit when

- A non-HTTP caller needs these rules — a worker, a CLI, a scheduled job. That is the
  moment `HTTPException` in a service stops being pragmatic and starts being wrong, and
  the domain-exception hierarchy earns its keep.
- `TopicsService` needs splitting. It is one module because it was one router; discovery,
  subscription and progression are three plausible seams if it grows.
- Someone adds a query to a router. Nothing currently *enforces* this ADR — unlike hard
  rules 1, 3, 5 and 7, there is no check in `tests/test_architecture.py` asserting that
  `api/routers/*.py` contains no `select(`. Writing one is the natural follow-up, and
  until it exists this ADR is convention rather than a guarantee.
