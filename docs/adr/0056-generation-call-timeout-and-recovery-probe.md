# ADR-0056: Client-side request timeout, and a background recovery probe for a stalled model

- **Status:** Accepted (amends [ADR-0028](0028-key-model-quota-ladder.md))
- **Date:** 2026-08-24
- **Deciders:** Anubhav

## Context

Live testing surfaced a real production incident: requesting the topic "The Epic of
Gilgamesh" hung the `POST /topics` request indefinitely. Server logs showed quota acquired
for key 0 / `gemini-3.7-flash`, then nothing -- no error, no timeout, no response, ever.

`langchain_impl.py`'s `_client()` constructed `ChatGoogleGenerativeAI` with `max_retries=0`
but no `timeout`. When the provider stalls (the TCP stream stays open but nothing comes
back), nothing raises, so `_invoke_with_retry` never gets a chance to rotate to the next
`(key, model)` cell -- the call, and the request it's part of, just never resolves.

The first fix attempt was wrong and shipped a real regression: it added a `timeout` and
caught `google.api_core.exceptions.DeadlineExceeded` on the theory that a stall would raise
that class. `google.api_core` is not a dependency of this project's actual stack
(`langchain-google-genai>=4.0` depends on `google-genai`, which does not import
`google.api_core` at all -- confirmed via `pip show`) and was only present in the
developer's host Python as an unrelated leftover from a different package. The moment that
code reached the container, `langchain_impl.py` failed to import at all
(`ModuleNotFoundError`), turning every `POST /topics` call into a 500 -- a strictly worse
outcome than the original hang, and a direct instance of this repo's own "verify against the
real environment, not what happens to be on the host" lesson.

Testing the real, container-matching `ainvoke()` async path (not `invoke()`, and not the
host's inconsistent dependency set) showed the actual shape: a timeout surfaces as
`google.genai.errors.ServerError` with `.code == 504` -- the exact same exception class
already used for an ordinary 503 "high demand" overload, distinguished only by the numeric
code. There is no separate exception type to catch.

## Decision

**A configured client-side timeout.** `Settings.gemini_request_timeout_seconds` (default
60s) is passed to every `ChatGoogleGenerativeAI` construction. A stalled call now raises
(as the `ServerError` described above) instead of hanging forever.

**`_invoke_with_backoff` distinguishes 503 from 504.** A 503 keeps the existing same-cell
retry with exponential backoff (Google's own docs call it "usually temporary"). A 504 skips
that retry and raises on the very first attempt: the call already burned its *full* timeout
budget once just to produce that error, so retrying the same cell again would burn the same
budget a second time for nothing.

**A `ServerError` (either code) now excludes the model persistently, not just for the
current call.** Previously, `_invoke_with_retry`'s exclusion (`unavailable_models`) was a
local variable, scoped to one call -- the next unrelated call would try the same stalled
model from scratch and pay the same timeout again. `QuotaGovernor` gained
`exclude_model()`/`include_model()`, an in-memory set checked by `_acquire_locked` alongside
the existing per-call `exclude_models` parameter, so the exclusion now outlives the call that
discovered it.

**A background recovery probe checks when it's back**, instead of leaving it excluded until
someone happens to hit it with real traffic again. `GeminiContentGenerator._probe_model`,
started fire-and-forget the moment a model is excluded:

- Cycles through a **different key each attempt** (not just the one that stalled), spaced so
  every configured key gets tried at least once inside the budget -- a stall on one key isn't
  strong evidence the whole model, or every other key, is actually down.
- Bounded at **20 minutes** total. Each attempt counts against today's `QuotaLedger` exactly
  like a real acquired call (`record_probe_attempt`) -- a probe is one real request against
  the provider's own daily limit, not free reconnaissance.
- On success: `include_model()`, and today's ledger counts are left exactly as they are --
  probing does not reset spend, generation resumes from wherever the day's count already
  stood.
- On giving up: every key actually tried gets `mark_exhausted()`'d (same posture as a real
  429), so the model stays out of rotation for the rest of the day via the existing
  ledger-based skip -- not via the in-memory flag, which is released either way so any key the
  probe never got to remains available for real traffic to discover on its own.

**Only actually completes in a long-lived process.** The probe is a 20-minute in-process
`asyncio.create_task`, tied to the `GeminiContentGenerator` singleton for that process
(`get_content_generator()`'s `@lru_cache`). That's the API process (uvicorn, persistent) and
local dev's `--watch` worker loop -- but production's worker runs as a short-lived batch cron
pass (~15 min, see `apps/worker/README.md`), which usually exits before a 20-minute probe
finishes. In that case the task is just cancelled at process exit -- harmless, and the next
cron pass rediscovers the same model fresh at the cost of one more timeout. This is an
accepted limitation, not a bug: the probe's real value is in the process that's actually
long-lived, which is exactly where the incident that motivated this ADR happened
(`POST /topics`, synchronous, in the API process).

## Consequences

**Easier**

- A stalled call no longer hangs a request indefinitely -- it fails within
  `gemini_request_timeout_seconds` and rotates to the next cell, same as any other cell
  failure.
- A model discovered stalled doesn't keep costing every subsequent unrelated call the same
  60-second timeout tax until someone happens to notice and fix it manually.
- Recovery is automatic and doesn't burn the day's real quota beyond the probe's own bounded
  attempts -- generation resumes exactly where it left off, not from a reset ledger.

**Harder**

- Two failure-shaped things (a genuinely overloaded model, a stalled/hung one) now share one
  exception class distinguished only by an HTTP-style code (503 vs 504) that lives inside the
  provider's own error envelope -- a future SDK version that stops setting `.code` accurately
  would silently break this distinction with no type-level guard.
- The exclusion/probe state is in-memory only (same posture as the existing RPM window and
  flash-lite cooldowns), so it does not survive a process restart, and does not coordinate
  across multiple processes (e.g. the API process and a concurrently-running worker) --
  each discovers a stalled model independently.
- The probe budget (20 min) and cadence (spread across every configured key) are
  hand-picked, not tuned against a real incident history yet -- same caveat ADR-0028 already
  carries for its hand-copied RPD/RPM figures.
- In the production batch-cron worker specifically, the probe mechanism mostly doesn't get a
  chance to do anything -- see "Only actually completes in a long-lived process," above.

## Alternatives considered

**Persist the exclusion/probe state to Postgres**, matching how RPD survives a restart.
Rejected for now, same reasoning ADR-0028 already gives for keeping RPM in-memory: this is a
live-availability signal, not a fact that needs to survive a restart, and every process that
discovers a stall will simply rediscover it (at the cost of one timeout) if the in-memory
state is gone. Revisit if the production worker becomes a persistent process (paid tier) and
losing probe state on a routine restart becomes a real, repeated cost.

**Retry a 504 on the same cell too, same as a 503.** Rejected: a 504 already means the call
sat for the *entire* configured timeout with no response -- retrying it again would mean
waiting that full budget a second (and via `_SERVER_ERROR_RETRIES`, potentially third) time
before ever moving on, which is a much worse user-facing latency than immediately rotating.

**Always probe with the one key that stalled.** Rejected per explicit direction: cycling
through a different key each attempt is what actually distinguishes "this one key is bad"
from "the whole model is down" -- probing the same key repeatedly would never surface that
distinction.

**Don't count probe attempts against the ledger.** Rejected per explicit direction: a probe
is a real request against the provider regardless of why it was made, and treating it as
free would let the local ledger drift further from the provider's actual daily usage than it
already can (ADR-0028's documented drift risk).

## Revisit when

- The production worker becomes a persistent process (paid tier, per ADR-0003) -- the probe
  becomes fully effective there instead of mostly not completing in time.
- A real incident shows the 20-minute budget or per-key cadence is miscalibrated (gives up
  too early, or wastes too many real requests probing a model that's genuinely down for the
  day).
- Multiple concurrently-running processes routinely fight over the same stalled model,
  making the in-memory-only, per-process nature of the exclusion/probe state a real cost
  worth persisting.
