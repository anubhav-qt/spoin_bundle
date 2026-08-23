# Task 0022: Slug-collision fallback in topic matching skips alias recording

**Owner:** unassigned

## The problem

`match_and_create_topics` (`apps/api/src/spoin/generation/pipeline/topic_match.py`) has
two branches that resolve an incoming topic name onto an *existing* `Topic` row instead of
minting a new one:

1. The LLM finds a semantic match among the pgvector candidates -> calls `_ensure_alias(...)`
   to record the user's typed name as an alias of the matched topic.
2. No semantic match, but `_slugify(name)` collides with an existing topic's `slug` -> reuses
   that row, `matched_existing=True` -- but never calls `_ensure_alias(...)`.

Branch 2 was added in commit `e6947a6` to fix a real bug (an unhandled `IntegrityError` on
insert when two different-looking names slugified to the same string). The fix is correct
and shipped. What it didn't do is treat the collision as a match worth recording the same
way branch 1 does.

`_slugify` (`apps/api/src/spoin/generation/pipeline/state.py`) keeps only `[a-z0-9-]` and
strips everything else, so names like "Node.js" / "Nodejs", "C++" / "C", or "AI/ML" / "AI ML"
can collapse onto the same slug without the LLM ever judging them related. When that happens
today, the user's exact typed name is silently dropped instead of being recorded as an alias
-- so the next person who types that same name pays for another embedding + LLM-batch pass
and hits the same silent merge again, instead of the alias cache short-circuiting it the way
ADR-0025 intends for every other match path.

## Why it matters

ADR-0025 commits to "`topic_alias` still caches every decision permanently... a pair is
never re-judged once decided." The slug-collision path is a real decision (this name now
means that topic) that isn't being cached, which quietly violates that commitment for one
specific code path. It's also the one merge path with no similarity score or LLM reasoning
attached to it -- worth flagging for whoever next touches topic matching, per this repo's
"a hard rule gets enforced twice, not documented once" norm; right now it's enforced zero
times outside this doc.

Confirmed via code review 2026-08-23, not yet observed in a live run.

## What to do

In the slug-collision branch (`topic_match.py`, the `existing_by_slug is not None` case),
call `_ensure_alias(session, topic, request["name"], ...)` the same way the LLM-match branch
does, before returning `matched_existing=True`. Add a test asserting a slug-colliding name
(e.g. two names that `_slugify` maps to the same string) ends up in `topic_alias` after the
call, not just merged silently.

## Timebox

Small -- one missing function call plus a test, on the order of 30 minutes.
