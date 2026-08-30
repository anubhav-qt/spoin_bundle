# Task 0032: Let a user request several custom topics in one submission, each with an optional description

**Owner:** unassigned
**Blocked on:** nothing

## Status (2026-08-30, `feat/v1-finish-line`)

**Backend shipped** — commit `1f72fc6`. `POST /topics/batch`
(`TopicsService.request_topics_batch`): one `validate_topic_names` + one
`match_and_create_topics` call for the whole list, per-row outcomes
(`generating` / `subscribed` / `already_subscribed` / `rejected` + `detail`),
capped at `Settings.custom_topic_batch_max` (5), guest-gated, one `FeedPlan`
clear + one commit. `api.requestTopics(entries)` is in `lib/api.ts`. 7 tests in
`tests/test_topics_batch.py`; `make test` green.

**Frontend still to build** — the `RequestTopicBox` rows UI described below. Two
reasons it wasn't done in the same pass: (1) it's a visible redesign of a
right-rail box, so per the v1 plan's Phase 2.5 it wants a `/design` pass +
owner sign-off first; (2) `RequestTopicBox.tsx` carries an uncommitted Wave-1
change (the F9 `onFollowed(topic, hasCards?)` signature) that a full rework
would entangle with — that change should land first. The description-field and
list-of-rows work is otherwise exactly as specified below, now that the
`/topics/batch` endpoint and `api.requestTopics` exist.

## The problem

`RequestTopicBox.tsx` is one text input, one "Add" button, one topic at a time. Behind
it, `POST /topics` (`topics/service.py`'s `request_topic`) validates and matches
exactly one topic name per call — even though the machinery underneath it,
`match_and_create_topics` (ADR-0025) and `generator.validate_topic_names`, already
takes a LIST and is specifically built to run as one batched call over several topics
at once. The CLI entrypoint (`generate_topics.py`,
`python -m spoin.generate_topics "Docker" "Kubernetes::Container orchestration"`) is
the only caller that actually uses that shape today — it's "how we test from the
backend with multiple topics," in the words of the request that opened this task.

Two gaps, not one:

1. **The frontend only offers one topic at a time**, with no way to queue several
   before submitting.
2. **There is no `description` field in the UI at all**, even though the backend
   already accepts one — `lib/api.ts`'s `api.requestTopic(name, entryDifficulty?,
   description?)` and the server's `request_topic(..., description: str)` both support
   it, and `RequestedTopic`/`match_and_create_topics` thread it through to the
   generation pipeline as context for the curriculum/card writer ("the thinker," in
   the request that opened this task — `subtopic_description`/`topic_description`
   arguments the card and curriculum prompts already read). Today it's simply
   `description.strip()` on an always-empty string; the UI has never sent one.

## What to build

### Frontend (`apps/web`)

Replace the single name input in `RequestTopicBox.tsx` with a **list of entry rows**,
starting at one, each with:
- a required name field (same `maxLength={120}` as today)
- an **optional** description field — "1–2 sentences on what you want to learn," a
  `<textarea>` or a second `<input>`, not required to submit

A **`+`** control adds another row, up to a capped count (pick something reasonable —
5 is a defensible starting point; there's no backend cap to inherit since single-topic
requests today have no per-submission limit, only the removed-for-now per-user total
cap from [Task 0024](0024-reintroduce-custom-topic-limit.md), which is a different
axis). Each row gets its own remove control once there's more than one.

**One submit button** sends every filled row in a single request (see the batch
endpoint below) — not N sequential `POST /topics` calls. Firing N separate requests
would call `validate_topic_names` and `match_and_create_topics` N separate times
instead of once each, defeating the entire point of them being batched interfaces
(ADR-0005: "every method takes a collection... the free tier meters requests, not
tokens" — N single-item calls costs N times the quota a single N-item call costs).

**Per-row result reporting.** A batch submission can genuinely partially fail — one
name rejected by `validate_topic_names`, another already-subscribed, a third minted
fine. The UI needs to show each row's own outcome (a checkmark/reuse of the existing
error-notice styling per row), not one blanket toast for the whole batch. This mirrors
how `TopicDiscoveryModal`'s "Your Requests" tab already lists several in-flight custom
topics side by side — the visual vocabulary for "several of these, each in its own
state" already exists in the codebase, it's just never been the SUBMISSION form's
own shape before.

**Tracking after submission needs no new plumbing.** `GenerationTrackerProvider`
already tracks an array of in-flight generations
(`generations: {topicId, displayName}[]`), and `RequestTopicBox` already renders one
`GenerationProgressPanel` per tracked generation in a loop. Submitting 5 topics at
once just means calling `track()` 5 times instead of once — the display side of this
task is already built.

### Backend (`apps/api`)

A new endpoint — `POST /topics/batch` is the natural name, mirroring how
`match_and_create_topics` itself is named — taking a list of
`{name: str, description: str | None, entry_difficulty: Difficulty | None}` (same
per-item shape `POST /topics` takes today, just as a list) and returning a list of
per-item results, index-matched to the request (the same `request_index` convention
`TopicNameQuery`/`TopicNameVerdict` and `match_and_create_topics`'s own
`TopicRequest`/outcome pairing already use — ADR-0025's pattern, not a new one).

Internally this is close to `request_topic`'s existing body, generalized from one item
to N:
- ONE call to `generator.validate_topic_names(queries)` for every name in the batch
  (not N calls) — same reasoning as the frontend section above.
- ONE call to `match_and_create_topics(..., topic_requests=[...])` for every
  request that passed validation.
- Per already-subscribed / already-following results, same 409-equivalent handling
  as today, but as a per-item status in the response rather than an HTTP error for
  the whole call — a batch where 4 of 5 succeed should not report as a failure.
- Still gated to non-guest users, same as today (`request_topic`'s existing guest
  check) — a guest's account is ephemeral, so nothing here should change that.
- A `GenerationJob` gets enqueued per genuinely-new topic, exactly as today — this
  task changes how many topics one HTTP call can mint, not how generation itself
  works. `run_generation_pipeline`/the worker pool already handles N jobs running
  concurrently; nothing there needs to change.

`lib/api.ts` needs a new `api.requestTopics(entries: {name, description?,
entryDifficulty?}[])` alongside the existing single-topic `api.requestTopic` (which
can stay — a single quick add from elsewhere in the UI has no reason to route through
the batch form).

## Why it matters

This is a real underuse of ADR-0025's own design: the batched matcher exists
specifically so several topics cost one LLM call instead of several, and today
nothing in the product actually exercises that path except a developer-only CLI
script. It's also a straightforwardly better user experience — someone onboarding
several topics at once (the exact scenario the CLI script exists to simulate) currently
has to sit through N sequential ~1-minute waits (per `RequestTopicBox`'s own comment
on why the "Checking your topic…" / "Still working…" staged copy exists) instead of
one.

## What NOT to do

- Don't build this as N parallel client-side `fetch` calls to the EXISTING
  single-topic endpoint. It looks like it solves the UX problem (the waits overlap),
  but it still burns N validation calls against quota instead of one, which is the
  actual point of ADR-0025's batching and the actual reason a new endpoint is worth
  building instead of a purely client-side fix.
- Don't remove `api.requestTopic`/the single-topic `POST /topics` endpoint — keep both;
  this is additive.
- Don't add a new per-user total-custom-topics cap as part of this task — that's
  [Task 0024](0024-reintroduce-custom-topic-limit.md)'s separate, already-tracked
  concern. This task's cap (the `+` button's max row count) is about one submission's
  size, not a user's running total.
