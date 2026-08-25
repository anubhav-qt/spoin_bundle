# Task 0025: Extract the quota governor into a standalone library

**Owner:** unassigned -- deliberately not started. Do not begin this until spoin v1 has
shipped; it exists so the intent is written down before the pattern is forgotten, not as
live work.

## The problem

`apps/api/src/spoin/generation/quota.py` solves a general problem that has nothing to do with
spoin specifically: coordinating a fleet of free-tier API keys, each with per-model daily and
per-minute limits, across an unknown number of concurrent processes, without ever
misclassifying a temporary throttle as a permanent exhaustion. That problem shows up anywhere
someone is stretching a free tier across multiple keys -- which is most hobby/early-stage LLM
usage -- and nothing off-the-shelf solves the specific shape of it (see "Prior art", below).

Right now the solution is entangled with spoin: it depends on `spoin.core.db.session_scope`
and the `QuotaLedger`/`QuotaRequest` SQLAlchemy models, and its only classifier
(`_classify_rate_limit` in `langchain_impl.py`) knows exactly one provider's error envelope
(Gemini's, via `google-genai`). Neither dependency is deep, which is exactly why extraction is
worth doing once there's room for it.

## Why it matters

This is genuinely distinctive, not just "we already wrote it so why not publish it":

- **The key × model grid with a fallback ladder** (ADR-0028) is a real answer to a real
  situation -- N free-tier projects, M models, each cell independently rate-limited -- that
  most rate limiters (built for one API key against one limit) don't model at all.
- **Per-minute vs. per-day classification read off the provider's own payload** (ADR-0058) is
  the mistake almost everyone makes first (spoin included, twice, before getting it right) --
  treating every 429 as equally serious. Getting this right against a real provider, with the
  actual envelope shapes captured in tests, is the hard-won part.
- **The reserve-then-confirm RPM window, shared across processes via the database** (also
  ADR-0058) is a good general primitive for exactly the failure mode multi-process deployments
  hit: each process independently believing it's under the ceiling while the provider sees the
  sum. Most naive rate limiters miss this until it bites them in production, the way it very
  nearly did here.

## What to do

**1. Design the provider boundary first.** `_classify_rate_limit` is Gemini-specific --
`quotaId` in a JSON envelope is not how OpenAI or Anthropic signal rate limits (headers,
mostly, and differently shaped). The library needs a small `RateLimitClassifier` protocol
(or similar) with a Gemini implementation as the first of several, not the only one. This is
the actual design problem worth spending time on; everything else is closer to mechanical.

**2. Design the storage boundary second.** The current implementation hardcodes Postgres
(`session_scope`, raw SQLAlchemy models). A general library can't assume every user has a
database -- most single-process users shouldn't need one at all. Sketch a narrow store
interface (`reserve`, `confirm`, `count_in_window`, `get_cooldown`/`set_cooldown`, roughly)
with three implementations in mind: in-memory (the default, zero dependencies, what a
single-process user wants), a SQL implementation (what this extraction starts from), and
optionally Redis (only worth building if there's an actual multi-process-at-rate user asking
for it -- see the reasoning in this task's originating conversation, 2026-08-25, for why
Redis was correctly rejected as premature for spoin's own deployment).

**3. Extract `quota.py` behind those two boundaries.** It already has exactly two spoin
imports (`session_scope`, the two models) plus SQLAlchemy -- close to standalone as it is.
Once it takes a classifier and a store as constructor arguments instead of assuming Gemini
and Postgres, spoin's own usage becomes the SQL-store, Gemini-classifier configuration of a
general library, not a special case.

**4. Decide packaging and licensing**, and whether spoin keeps a thin wrapper importing the
library or the library gets vendored back in with a pin -- normal extraction questions, not
specific to this codebase.

## What NOT to carry over as general

- The hand-copied RPD/RPM figures in `Settings.gemini_thinking_ladder` /
  `gemini_generator_ladder` are spoin's own, read off Gemini's rate-limit page by hand
  (ADR-0028). A library needs these either discovered from the provider or explicitly
  configured -- never hardcoded the way spoin's `LadderRung` construction currently is.
- The "17 keys = 17 separate GCP projects" assumption (ADR-0028's key finding, that Gemini
  rate limits per project not per key) is provider-specific and belongs in the Gemini
  classifier/adapter, not the core grid logic.
- `_backend`'s `f"gemini:{key_index}:{model}"` naming convention is spoin's, not a library
  concern -- the store interface should take an opaque cell identifier.

## Prior art worth checking before starting

`limits` (Python), `django-ratelimit`, and most token-bucket libraries solve "one caller,
one limit." None of the ones checked in the originating conversation solve the specific
combination this does: multiple independent quota-bearing credentials, a model fallback
ladder as a first-class concept, and a payload-based (not header-based) 429 classifier.
Confirm this is still true before starting -- the space moves.

## Timebox

Not timeboxed -- explicitly deferred past spoin v1. When picked up, step 1 (the classifier
design) is the part to timebox first; the rest follows from it.
