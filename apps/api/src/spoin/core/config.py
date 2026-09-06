"""Settings.

Everything that changes between free tier and paid tier lives here, because
ADR-0003 §2 commits us to that being a config change and never a code change.
Same for the ranking weights (ADR-0010) and the difficulty mix
(content-model.md) — both will be tuned against real engagement data, and
tuning must not require a deploy.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from spoin.domain.enums import Difficulty, EngagementKind

GeneratorBackend = Literal["fake", "gemini", "hybrid", "local"]
#: `frog`'s ingester takes exactly these two (`frog/ingest/__main__.py --embedder`).
#: Spelled the same on purpose: the corpus is queried by whatever ingested it, and a
#: third name here would be a way for the two to disagree. There was a separate
#: `CorpusEmbedderBackend` alias until ADR-0097 collapsed the two vector spaces into
#: one; it said the same words and existed only to keep the split visible.
EmbedderBackend = Literal["hash", "qwen3"]

#: Ships as the field default so `local`/`ci` never need a `.env` entry to boot.
#: A `production` process still carrying this value means the real secret was
#: never set, which `Settings._require_real_jwt_secret_in_production` below
#: turns into a startup failure rather than a silently-forgeable token.
_INSECURE_DEFAULT_JWT_SECRET = "CHANGE-ME-IN-PRODUCTION-KEY-MUST-BE-32-BYTES"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPOIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["local", "ci", "production"] = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://spoin:spoin@localhost:5432/spoin"
    #: `the_spoin_universe`, the corpus (ADR-0088), read-only from this process.
    #: **Empty by default and never falling back to `database_url`** — the same rule
    #: frog's alembic environment is held to, and for a sharper reason here: a
    #: fallback would point retrieval at `spoin_db_2`, which has no `document` table,
    #: and the failure would arrive as a confusing SQL error rather than as
    #: "no corpus configured". Empty means generation runs ungrounded (ADR-0089).
    universe_database_url: str = ""
    #: Cosine similarity floor for catalog image assignment (ADR-0095, ADR-0102).
    #: Image cards scoring below this floor are not assigned an image and fall back.
    #: Initial calibration run sets this to 0.0 so all candidate similarity scores
    #: are recorded without rejecting drafts.
    image_similarity_floor: float = 0.0
    #: Comma-separated. Deliberately a plain string rather than a list: a list-typed
    #: setting makes pydantic-settings JSON-parse the env var, so a perfectly
    #: ordinary `SPOIN_CORS_ORIGINS=http://localhost:3000` fails to start the app.
    #: Read it through `cors_origin_list`.
    cors_origins: str = "http://localhost:3000"

    # -- auth ---------------------------------------------------------------
    jwt_secret_key: str = _INSECURE_DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    google_client_id: str = ""

    @model_validator(mode="after")
    def _require_real_jwt_secret_in_production(self) -> Settings:
        """The default signing key is checked into git and public. A `production`
        process still carrying it would sign every token with a guessable secret,
        so this fails startup loudly instead of falling back silently."""
        if self.env == "production" and self.jwt_secret_key == _INSECURE_DEFAULT_JWT_SECRET:
            raise ValueError(
                "SPOIN_JWT_SECRET_KEY must be set to a real secret when SPOIN_ENV=production"
            )
        return self

    # -- generation (ADR-0002, ADR-0008, ADR-0028) -----------------------------
    # `fake` everywhere except production: tests and local dev must never call a
    # real model, never burn quota, and run in milliseconds.
    generator: GeneratorBackend = "fake"
    #: Comma-separated. Each entry is assumed to be its OWN Google Cloud project
    #: (a key does NOT get its own quota pool otherwise — Gemini rate limits are
    #: per-project, not per-key; see ADR-0028). The quota governor
    #: (generation/quota.py) treats each entry as one row in its key x model grid.
    gemini_api_keys: str = ""
    #: "model:rpd:rpm,model:rpd:rpm,..." — an ORDERED fallback ladder, strongest
    #: model first. Used for curriculum, topic matching, difficulty/factual
    #: judging, and quiz grading — the calls with a real consequence if the
    #: model is weak (ADR-0008's "trusted for taste, never for constraints"
    #: rule). A model is only skipped once every configured key is exhausted
    #: for it (ADR-0028). Live-verified 2026-08-17 against 9 real keys —
    #: `gemini-2.5-flash` is retired for new accounts (404) and dropped;
    #: `gemini-3.0-flash` never existed as a stable name (only the `-preview`
    #: suffixed one does). `gemini-3.8-flash` prepended 2026-09-03 as the new
    #: strongest rung (owner request) -- live-verified 200 the same day.
    gemini_thinking_ladder: str = (
        "gemini-3.8-flash:20:5,gemini-3.7-flash:20:5,gemini-3.6-flash:20:5,"
        "gemini-3.5-flash:20:5,gemini-3-flash-preview:20:5"
    )
    #: How many rungs at the END of `gemini_thinking_ladder` are held back as a
    #: RESERVE (ADR-0074). A reserve rung is never used to work around keys being
    #: BUSY -- a subtopic group that finds every key claimed waits for one to free
    #: instead. It is reached only when no key anywhere has daily room on any
    #: ordinary rung, i.e. when the day's real thinking budget is gone.
    #:
    #: The two waits are nothing alike and must not collapse into one: waiting out
    #: a claim or an rpm window resolves in seconds, waiting out RPD resolves at
    #: midnight UTC. Spending the weakest model on ordinary contention wastes the
    #: reserve; refusing to spend it on genuine exhaustion stalls a run for hours.
    #:
    #: These calls are the ones with a real consequence if the model is weak
    #: (curriculum, judging, grading -- ADR-0008), which is why the weakest rung is
    #: a last resort rather than an ordinary fallback. 0 disables the reserve.
    gemini_thinking_reserve_rungs: int = 1
    #: Same shape, for `generate_cards` AND `generate_questions` (ADR-0029) —
    #: both are high-VOLUME, taste-shaped calls (one per card/question), so
    #: they share the cheap high-volume "lite" ladder instead of competing
    #: with the thinking pool's much smaller daily budget. Live-verified
    #: 2026-08-17 — `gemini-2.5-flash-lite` is retired for new accounts (404,
    #: same as `gemini-2.5-flash` above) and dropped.
    gemini_generator_ladder: str = "gemini-3.5-flash-lite:500:15,gemini-3.1-flash-lite:500:15"
    #: `ChatGoogleGenerativeAI`'s own `timeout` — without it, a stalled call (the
    #: TCP stream stays open but the provider never responds) blocks forever:
    #: nothing raises, so `_invoke_with_retry` never gets a chance to rotate to
    #: the next (key, model) cell, and the request never resolves. Bounds a
    #: single attempt so a stall degrades the same way a 429/503 already does.
    gemini_request_timeout_seconds: float = 180.0

    # -- Mistral (ADR-0090, generation-pipeline-v2.md) -------------------------
    # Prose on the generator ladder runs here; verdicts stay on Gemini. Read by
    # `generation/mistral.py` and reached only through `SPOIN_GENERATOR=hybrid`.
    #
    # Comma-separated, same variable the committed probe already uses
    # (`spoin/probes/mistral_probe.py`). One key is the current reality; the client
    # takes a list and round-robins, so adding a second is a config change.
    mistral_api_keys: str = ""
    mistral_base_url: str = "https://api.mistral.ai/v1"
    #: The dated snapshot, not the `ministral-8b` alias: the mistral-saga's findings
    #: table only vouches for model ids a direct call returned 200 with real
    #: `x-ratelimit-limit-*` headers for, and this is that id. Measured post-RAG
    #: prompts are p50 ~3.1k tokens / max ~5.9k, and 8b only drops below target rate
    #: above ~18k -- real headroom, including for ADR-0099's taller scenes.
    mistral_model: str = "ministral-8b-2512"
    #: The thinking ladder's model (ADR-0103). Bigger than `mistral_model` above on
    #: purpose: the gate is the one place a weak judge is silently expensive, since it
    #: re-rates difficulty and verifies factual claims, and a bad verdict there ships
    #: as a good card (ADR-0030).
    mistral_thinker_model: str = "ministral-14b-2512"
    #: Route the thinking ladder to Mistral as well, not just the generator ladder.
    #:
    #: **This reverses ADR-0090's routing table**, whose split existed because this
    #: account had no reasoning-capable Mistral model at all -- everything
    #: Small/Medium/Magistral returned a permanent `x-ratelimit-limit-req-minute: 0`.
    #: `ministral-14b` is on the ladder this account CAN call and judges well enough,
    #: which is the weaker claim that survived (ADR-0103).
    #:
    #: The win is not throughput for its own sake: it takes the two gate passes off
    #: Gemini's thinking rungs (`rpd 20 / rpm 5`), which were the scarcest resource in
    #: a run and the usual reason a tier stalled. A prompt carrying an image still goes
    #: to Gemini regardless of this flag -- image input is not on this Mistral tier.
    mistral_as_thinker: bool = True
    #: Matches the probe's `REQUEST_TIMEOUT_S`. Generous on purpose: a slow response
    #: is data, a hung one is not.
    mistral_timeout_seconds: float = 180.0
    #: Attempts per call, not retries after the first. Three because we are going in
    #: blind: enough to ride out a throttle or one malformed structured response,
    #: few enough that a real outage surfaces as an outage in minutes rather than
    #: being absorbed into latency. Revisit from the task-10 JSONL, not from taste.
    mistral_max_attempts: int = 3
    #: Doubles per attempt with jitter (2s, 4s), unless the response carries its own
    #: `Retry-After`, which always wins.
    mistral_backoff_base_seconds: float = 2.0
    mistral_max_output_tokens: int = 8192
    mistral_temperature: float = 0.7
    #: Where the per-run JSONL lands. A file rather than stdout: full response bodies
    #: on every call would drown the pipeline log a human is actually watching.
    mistral_log_dir: str = "logs/mistral"

    local_generator_base_url: str = "http://localhost:11434/v1"
    local_generator_model: str = "qwen3:14b"
    #: How many keys one topic gets for its whole generation run (ADR-0082).
    #: `max_concurrent_topics` below derives from it (`pool // box_size`).
    #:
    #: The whole pool in ONE box -> `109 // 109` = **one** topic at a time. The
    #: boxing machinery is deliberately kept (BoxPool still leases, releases and
    #: keeps slices disjoint) so raising concurrency later is a one-line change;
    #: we just never lease a second box today.
    #:
    #: `GeminiContentGenerator` clamps the unboxed remainder to at least one key
    #: (a box and the remainder balancer must never share one), so the box gets
    #: 108 and the claim-less path -- topic matching, curriculum, grading --
    #: keeps key 108 to itself.
    #:
    #: Benchmark 10 tried 34 keys x 3 concurrent topics and produced 0 cards in
    #: 3 minutes. Measured 2026-09-04 with direct single-key probes that bypass
    #: this whole module: Google throttles on the **source IP**, not the key or
    #: the project. 12 keys from 12 separate projects, fired concurrently, all
    #: came back with an IDENTICAL `retryDelay` (32s) -- and firing them is what
    #: re-armed a window that had just decayed to 0s. The envelope labels it
    #: `GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 500`, which is
    #: boilerplate: those keys were nowhere near 500 requests.
    #:
    #: So pool size cannot buy concurrency -- 109 keys and 1 key hit the same
    #: wall -- and topic-level parallelism multiplies arrival rate against a
    #: ceiling that is already the binding constraint. One box is the known-good
    #: shape (Benchmark 9: ~5-6 calls in flight, 426 cards in 38 minutes).
    topic_key_box_size: int = 109
    #: How many of a box's keys are DISPATCHABLE at any one moment. The box still
    #: owns all of them; this is a sliding window over it that rotates to the next
    #: slice when the current one degrades or runs out of top-rung budget.
    #:
    #: Measured 2026-09-04 (`keycount_probe.py`) at a CONSTANT 30 req/min and
    #: ~16k tokens, varying only how many distinct keys the calls spread across:
    #:
    #:     5 keys ->  20.0% failure, flat        20 keys -> 18.9%, flat
    #:    30 keys ->  32.2% failure, flat        60 keys -> 27.8%
    #:   108 keys ->  42.2%, and the ONLY arm that climbed (17% -> 40% -> 70%)
    #:
    #: 20-vs-108 reproduced across two independent runs with different cooldown
    #: schemes (17.8/41.1, then 18.9/42.2). Spreading one IP's traffic across 100+
    #: distinct keys measurably degrades it; a small rotating window does not. The
    #: relationship is NOT clean-monotonic in the middle of the range (20 beat 5,
    #: 60 beat 30) and one 10-key arm returned 100% failure and stayed there, so
    #: treat 25 as "inside the good band", not as a tuned optimum.
    #:
    #: The window rotates on FACTS local to it -- its top rung spent, or no budget
    #: left anywhere in it -- and deliberately NOT on the failure rate. A
    #: rate-triggered rotation shipped and was measured live on 2026-09-04: it
    #: fired 14 times in 4 minutes on spikes of 60-100%, because every window it
    #: moved to spiked too. The throttle is keyed to the source IP, so a high
    #: failure rate is a global fact rotation cannot escape -- and chasing it
    #: cycled the whole 108-key box every ~2 minutes, recreating the many-keys
    #: regime this window exists to avoid.
    #:
    #: 2026-09-04, AFTER the 07:00 UTC provider-day reset: re-measured 20/30/50
    #: keys at the same 30 req/min, 16k tokens -- 5.6% / 3.3% / 3.3% failure, flat
    #: thirds, identical ~0.48 good calls/s. The morning's steep gradient (18.9%
    #: at 20, 42.2% at 108) was a TRANSIENT IP penalty from ~10h of prior
    #: hammering; it cleared at the reset. On a healthy IP 50 is as clean as 20,
    #: so the window is 50: same failure rate, double the cell pool, far more
    #: headroom before a fact-based rotation is needed.
    gemini_active_key_window: int = 50
    #: Minimum seconds between two sends to the SAME `(key, model)` cell,
    #: enforced by every `LoadBalancer` (ADR-0084). This IS the rate limiter
    #: while it is > 0 (the trailing window + learned rpm go dormant): `60/gap`
    #: requests per minute per cell, round-robined evenly across the pool.
    #:
    #: 2026-09-03: 4s (15/min) still drew an 85% 429 rate on a single-topic,
    #: single-box run -- and the owner then verified against 8 separate Google
    #: accounts that the daily budget was barely touched, so it is per-MINUTE
    #: throttling, not exhaustion. 10s (6/min per cell) is the next probe: if it
    #: flows the real ceiling is between 6 and 15/min; if it still storms the
    #: keys share projects (finish the audit's Phase B). Tune with a benchmark,
    #: never by feel.
    gemini_send_gap_seconds: float = 10.0
    #: Minimum seconds between any two consecutive reservations across the ENTIRE
    #: balancer -- paces dispatch RATE across different cells (ADR-0086).
    #:
    #: 0.0 as of 2026-09-04. `gemini_max_inflight_calls` (below) is now the
    #: concurrency control, and the source-IP throttle sheds on concurrency, not
    #: rate -- so a rate stagger on top just caps throughput without adding
    #: protection, and it masks the difference between in-flight settings when
    #: they are being tuned. A single-stream probe held 2.2% failure at 0.49
    #: calls/s indefinitely; the lever that matters is how many run at once.
    #: > 0.0 re-enables the stagger (e.g. to smooth arrivals into the semaphore
    #: queue), but the semaphore is the real limit.
    gemini_dispatch_stagger_seconds: float = 0.0
    #: Hard cap on Gemini HTTP calls IN FLIGHT at once, process-wide -- the size
    #: of one WAVE. `_WaveGate` sits at the single outbound send site
    #: (`_invoke_with_backoff`); every generation call -- card drafts and thinking
    #: calls, box balancer and remainder balancer alike -- takes a slot before its
    #: request leaves and returns it when the response lands. Once a wave is full
    #: nothing else is dispatched until it has fully drained (see
    #: `gemini_wave_cooldown_seconds`).
    #:
    #: 2026-09-04: the source-IP throttle sheds on CONCURRENCY, not request rate.
    #: A single-stream probe (1 in flight) held 2.2% failure indefinitely; the
    #: pipeline fanning out to ~4-10 in flight -- at the SAME 2s dispatch spacing
    #: and SMALLER prompts -- hit 73%. `gemini_dispatch_stagger_seconds` paces
    #: when reservations are handed out but does nothing about how many calls are
    #: open at once; this does.
    #:
    #: 3. `inflight_sweep.py` found a hard boundary here, not a gradient: holding
    #: N calls in flight for 150s each against ~8k-token prompts --
    #:
    #:     N=2 -> 1.5% fail (flat), 0.85 good calls/s, 0 bare 429s
    #:     N=3 -> 1.2% fail (flat), 1.11 good calls/s, 0 bare 429s
    #:     N=4 -> 53.6% fail,       1.31 good calls/s, 220 bare 429s
    #:     N=5 -> 48.4% fail,       1.49 good calls/s, 200 bare 429s
    #:
    #: Zero perimeter shedding at N<=3, a wall at N=4. This is THE constraint the
    #: whole load balancer exists to respect -- do not raise it without re-running
    #: that sweep and seeing the boundary has actually moved.
    #:
    #: The sweep measured a ROLLING semaphore, and the pipeline shed at N=3
    #: anyway after ~5 clean minutes -- so 3 is the ceiling on a *steady* stream
    #: of ~2.5s probe calls, not a licence to keep 3 of the pipeline's 7-17s
    #: batches perpetually open. Hence the wave shape below.
    gemini_max_inflight_calls: int = 3
    #: Seconds to pause after a FULL wave drains, before the next one may open.
    #:
    #: A rolling semaphore refills a permit the instant any one call lands, so the
    #: provider never sees a moment with none of our sockets open. Batch-and-pause
    #: does: a wave fills, drains to zero, and then this pause runs before anything
    #: else is dispatched. A wave that drains without ever filling costs no pause
    #: at all, so a sequential trickle is not penalised.
    #:
    #: 2.0 is UNMEASURED -- a starting value, not a tuned one. The probe that would
    #: justify a number (a wave-mode sweep over size x cooldown, the way
    #: `inflight_sweep.py` swept N) has not been run. Treat a change here as
    #: needing evidence, same as `gemini_max_inflight_calls`.
    gemini_wave_cooldown_seconds: float = 2.0

    # Batch sizes (ADR-0005). Batching is still right -- one 15-card call beats
    # 15 single-card calls on every axis -- but the reason once stated here, "the
    # free tier meters requests, not tokens", is FALSE. Tokens are metered too
    # (ADR-0085), so a batch size trades requests against tokens-per-minute
    # rather than buying throughput for free.
    generation_batch_size: int = 15
    #: A drafting round is packed to fit BOTH budgets, with the overflow becoming the
    #: next round -- `generation_batch_size` above stays the ceiling, exactly as
    #: ADR-0085 already has `pack_by_tokens` do for the two gate passes.
    #:
    #: Two budgets because a drafting call is the one place where the binding
    #: constraint is usually OUTPUT, not input: the response carries N whole card
    #: bodies, and a response truncated at the model's output cap fails to parse, which
    #: loses **every card in the batch** rather than the overflow. Packing on input
    #: alone would happily put thirty cards into one comfortable prompt and lose all
    #: thirty.
    #:
    #: Per-card output estimate: title, canonical_title, summary and a Markdown body,
    #: plus JSON structure. Deliberately generous -- the cost of overestimating is one
    #: extra request, and the cost of underestimating is a whole batch.
    card_output_tokens_estimate: int = 900
    #: Gate pass 1 (`correct_cards`, ADR-0030). Kept moderate because correction
    #: rewrites whole card BODIES -- its output scales with the batch, so a large
    #: chunk risks the model's output-token cap (truncation fails the whole call)
    #: and dilutes edit quality. This is the pass that most needs "small task".
    judge_batch_size: int = 20
    #: Gate pass 2 (`verify_cards`, ADR-0030). Larger than `judge_batch_size`
    #: because verification returns only `{index, accepted, confirmed_difficulty,
    #: reason}` per card -- tiny output, so the only real limit is index-drift,
    #: not truncation. Bigger chunks here mean fewer thinking-pool calls per tier
    #: (the scarce rung: rpd 20 / rpm 5), which is where gate rate-limiting bites.
    #: ~40 is the ceiling before the model stops genuinely re-rating difficulty.
    #:
    #: Cut 40 -> 20 (ADR-0085): each verified card carries its BODY and its ascii
    #: art into the prompt, so this batch is one of the two biggest token
    #: consumers in the pipeline. The rate pressure it was sized against is real,
    #: but it was sized on the false premise that only requests are metered.
    verification_batch_size: int = 20
    question_batch_size: int = 35
    #: The most estimated PROMPT tokens one call may carry (ADR-0085). Derived,
    #: not picked: a cell's ceiling is `tpm / rpm` -- 250,000 / 15 ~= 16,600 --
    #: which is the largest a call can be while a cell can still spend its full
    #: requests-per-minute without blowing its tokens-per-minute. Rounded down.
    #:
    #: The `*_batch_size` settings above stay the CEILING on item COUNT; this is
    #: the ceiling on item WEIGHT, and whichever binds first ends the chunk
    #: (`pack_by_tokens`). What does not fit becomes the next request, and so
    #: gets its own `(key, model)` from the balancer.
    gemini_prompt_token_budget: int = 16_000

    #: Local-dev-only persistent loop (`python -m spoin.worker --watch`,
    #: wired into docker-compose.yml's `worker` service). Production still
    #: runs `run_once()` once per cron invocation (worker/README.md, ADR-0003
    #: §3) — this setting only paces the LOOP that calls the same function
    #: repeatedly, so a topic typed into the app during local dev actually
    #: gets generated without a developer manually re-running the worker.
    worker_poll_seconds: float = 4.0

    # Coverage threshold as a fraction of target_cards (content-model.md, open
    # questions: "somewhere around 50-60% is the intuition, check against real
    # rejection rates"). Config so it can be retuned without a deploy once real
    # quality-gate rejection rates exist.
    min_cards_fraction: float = 0.6

    #: Fraction of a topic's subtopics that must individually reach their own
    #: `min_cards` coverage before the topic is "live" — shown to users who
    #: didn't request it (ADR-0053, resolving the open question ADR-0026 left
    #: about read-path discoverability). The requester follows immediately
    #: regardless and watches real progress the whole time; this only gates
    #: what everyone else sees in Topics/Discover.
    topic_live_coverage_fraction: float = 0.5

    # -- embeddings (hard rule 5) ----------------------------------------------
    #: ONE embedder, for cards, topics, questions, ASCII scenes and corpus retrieval
    #: alike (ADR-0097). There were two until 2026-09-05, at two dimensions, and the
    #: split is what made task 0039 possible: `.env` set an embedder nothing read, so
    #: every vector in `spoin_db_2` was `HashEmbedder` output -- semantically
    #: meaningless by its own docstring, and nothing raised.
    #:
    #: `hash` remains, and remains dimension-correct, for one purpose: a stack that
    #: boots with no model weights on disk. It is not a fallback anything should
    #: select in anger -- a run grounded on it is grounded on nothing.
    #:
    #: There is deliberately no `embedding_dim` setting. The dimension is
    #: `frog.universe.models.EMBEDDING_DIM`, which is what the vector columns were
    #: created with; a configurable that disagreed with it could only ever produce
    #: vectors the database refuses.
    embedder: EmbedderBackend = "hash"
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"

    #: How many existing-topic candidates the embedding pre-filter offers the
    #: batched matching call per incoming topic (ADR-0025). Not a threshold — the
    #: LLM decides; this just bounds recall-filter/prompt size.
    topic_match_candidates: int = 5

    # Card near-duplicate threshold. Different vectors, different numbers — the
    # topic threshold does not transfer (content-model.md, open questions).
    # PROVISIONAL: never calibrated against real embeddings (only the
    # deterministic HashEmbedder is exercised in tests, and content-model.md
    # already calls that "not semantically meaningful"). Shipped deliberately
    # more conservative than the original 0.93 guess until real fastembed
    # data justifies a specific number (ADR-0030).
    card_duplicate_threshold: float = 0.9
    #: How many of a subtopic's most-recent near-duplicate `rejected_card` rows
    #: get fed back into the NEXT `generate_cards` call for that subtopic as
    #: "don't write anything like this again" context (ADR-0030 addendum).
    #: Bounded for the same reason `existing_titles` is bounded -- prevention
    #: context must stay small enough that the attention argument holds.
    max_duplicate_feedback_bodies: int = 10
    #: Same shape as `max_duplicate_feedback_bodies`, for a subtopic's most
    #: recent PASS-2 VERIFICATION `rejected_card` rows instead of near-dup
    #: ones -- these carry a real reason the judge model gave (not just a
    #: similarity score), fed back into the next `generate_cards` call so the
    #: writer fixes the actual problem instead of rewording into it again.
    max_verification_feedback_bodies: int = 10
    #: How many of a subtopic-tier's already-active question stems get shown to
    #: `generate_questions` as "don't repeat any of these" context -- unlike the
    #: two settings above (rejected content), this is ACCEPTED content, so the
    #: cap can be looser: stems are short one-liners, not full card bodies, and
    #: a subtopic-tier's whole question set (target_cards-bounded, ADR-0026) is
    #: already a naturally small number.
    max_existing_question_stems: int = 30
    #: A subtopic-tier with no cards before a run started (its first-ever
    #: pass) only has to clear this fraction of `target_cards` before
    #: `generate_subtopic_cards`'s redraft loop (nodes.py's
    #: `_redraft_until_bar`) hands it off. A tier that already had cards
    #: before the run started (a LATER pass -- e.g. a `scan_and_generate`
    #: backfill) is not capped by this fraction at all -- it keeps
    #: redrafting until it hits 100%, with no round limit either way; the
    #: only stop condition is the redraft loop's own per-tier stuck guard.
    #: See that loop's docstring for the full reasoning (docs/tasks/0023).
    first_pass_completion_fraction: float = 0.9
    #: How many times `generate_cards` will hand a too-wide ASCII drawing back
    #: to the generator to redraw within the 40-column budget before giving up
    #: on it (ADR-0066). Each attempt is ONE batched call covering every
    #: over-budget drawing in the batch (ADR-0005), the second attempt carrying
    #: escalated feedback. Art still over budget after the last attempt rejects
    #: the whole card -- the per-tier redraft loop then refills the deficit.
    #: 0 disables redrawing entirely (straight to reject), matching the old
    #: drop-the-visual posture only in that it stops here -- it rejects the card
    #: rather than shipping it without art.
    ascii_redraw_attempts: int = 2

    # -- grounding (ADR-0089) ---------------------------------------------------
    #: How many corpus passages ground one call. **Two, always** — asked of the
    #: database as `k=2` rather than retrieved wide and trimmed down.
    #:
    #: There is deliberately no token budget beside this and no `min_score` floor
    #: under it. A budget could not bind: the ingestion contract caps a section at
    #: `MAX_SECTION_CHARS` (2200), so two passages plus their labels cannot exceed
    #: roughly 1200 prompt tokens whatever the corpus does, and a limit that cannot
    #: bind is the dead code `8a8e64c` already removed once. A floor would guard
    #: against a passage from an unrelated area winning by default, which is a real
    #: retrieval risk (ADR-0088) and not a real risk *here*: the owner's commitment is
    #: that the curated corpus covers a topic before that topic exists in production,
    #: so there is no uncovered topic for a stray passage to be the best answer to.
    #:
    #: Owner's number and owner's reasoning, 2026-09-05. It replaced a 3000-token
    #: budget over a cap of 8 that was never measured against a real retrieval run.
    #:
    #: **This is per CARD now, not per subtopic** (ADR-0101), so the "roughly 1200
    #: prompt tokens" above is no longer what a drafting call carries: the prompt gets
    #: the deduplicated UNION of a round's cards' passages, which for astronomy's
    #: 6-9-section tier scopes measures ~2800 tokens on average and ~4000 at worst.
    #: The no-budget argument survives the change — the union is bounded by the
    #: declared scope rather than by the corpus — but the number it was quoting does
    #: not. Left at 2 because a round of nine cards already unions most of a scope;
    #: raising it buys breadth the union is delivering anyway.
    grounding_chunks: int = 2

    # -- feed (ADR-0010) --------------------------------------------------------
    rank_w_quality: float = 1.0
    rank_w_affinity: float = 0.8
    rank_w_coverage: float = 0.6
    rank_w_freshness: float = 0.3
    rank_epsilon: float = 0.10

    slate_size: int = 25
    plan_size: int = 50
    slate_ttl_seconds: int = 1800
    page_size: int = 10

    #: Consecutive slots one topic wins in the interleave plan.
    #:
    #: ADR-0010 specifies slots "spread evenly rather than clumped", which is `1`.
    #: This was briefly `3` so the client's per-topic headings did not appear
    #: before every single card; ADR-0055 put it back, because a run of 3 out of
    #: `plan_size` 50 makes the smallest allocation a topic can win 3/50 = 6% —
    #: which means the 5% share floor is not representable in the emitted plan at
    #: all. At 1 the granularity is 2% and the floor is honoured. The per-card
    #: heading repetition is the accepted cost; do not raise this without also
    #: raising `plan_size` enough to keep one run under `session_share_floor`.
    feed_topic_run: int = 1

    # Degraded-mode hysteresis (ADR-0006 §3). Two thresholds, deliberately: a
    # single one flaps as the pool sits on the line.
    pool_low: int = 5
    pool_high: int = 15

    # Dynamic difficulty mix ramp (extends ADR-0010's DIFFICULTY_MIX below).
    # A topic+tier starts at 100% the current difficulty; between
    # `mix_ramp_start` and `mix_ramp_end` fraction of that difficulty's cards
    # read, the mix eases toward DIFFICULTY_MIX[tier], which is the ceiling
    # this ramps TOWARD, not a fixed value from card one. Below start, a user
    # who just began a difficulty sees only that difficulty -- no diluting a
    # brand-new tier with promotion-signal cards before there is any signal to
    # collect. At/above end, DIFFICULTY_MIX[tier] applies exactly, unchanged.
    mix_ramp_start: float = 0.20
    mix_ramp_end: float = 0.60

    # -- session taste profile (ADR-0055) ---------------------------------------
    #
    # Drives each topic's SHARE of the interleave plan from what the user has done
    # in the current session. Every number here is a guess until there is real
    # engagement data to tune against, which is exactly why they are config.

    #: A session is a run of activity with no gap this long. Deliberately NOT
    #: sharing `slate_ttl_seconds` despite both being 1800: how long a ranked slate
    #: stays fresh and how long a taste profile survives are unrelated facts that
    #: happen to agree today, and tuning one must not silently move the other.
    session_window_seconds: int = 1800

    #: Share bounds, as a fraction of the topics the feed is currently drawing
    #: from. Both degrade to `1/n` when arithmetically impossible — a 5% floor
    #: cannot hold for 21+ topics, and a 50% ceiling is meaningless for one.
    session_share_floor: float = 0.05
    session_share_ceiling: float = 0.50
    #: Share-fingerprint quantization. Below this, drift does not rebuild the plan.
    session_share_bucket: float = 0.05

    #: Signal score at which a topic reaches half its maximum boost. Sets how much
    #: reading it takes to visibly move the feed.
    session_signal_k: float = 10.0
    #: Ceiling on the multiplier a topic's weight can reach above the uniform
    #: baseline of 1.0, so a saturated topic peaks at `1 + boost`.
    session_signal_boost: float = 2.0

    #: Per-event contribution to the session score. `explicit_complete` outweighs
    #: `dwell_complete` deliberately — engagement/service.py's module docstring
    #: makes the point that the two are separate events precisely because a
    #: deliberate "Got it" and a card left open are different evidence.
    session_w_dwell_per_second: float = 0.05
    session_w_expand: float = 0.5
    session_w_explicit_complete: float = 4.0
    session_w_dwell_complete: float = 2.0
    session_w_like: float = 3.0
    session_w_bookmark: float = 3.0
    session_w_note: float = 4.0
    session_w_share: float = 4.0
    session_w_ask_ai: float = 3.0
    #: Negative. A skip is evidence, not the absence of it — without this a topic
    #: the user is actively scrolling past only ever fails to rise.
    session_w_skip: float = -1.5

    # -- engagement (ADR-0011) --------------------------------------------------
    dwell_complete_ms: int = 10000
    dwell_max_ms: int = 300_000  # a tab open overnight is not a nine-hour read

    # -- topics (moved out of routers/topics.py) --------------------------------
    #
    # These are product knobs, not implementation details, and they lived as
    # module constants inside a router. That put them out of reach of anything
    # that is not an HTTP handler and made them the one class of tunable a
    # deploy was required to change — the exact thing
    # `test_difficulty_mix_is_config_not_code` exists to prevent for the
    # difficulty mix.

    #: The coverage gate (ADR-0009). Relative rather than absolute so it
    #: self-adjusts to whatever the corpus actually holds — a thin subtopic
    #: cannot strand a user at an unreachable bar.
    coverage_gate: float = 0.80

    #: A constraint, not taste -- enforced in code rather than asked of the
    #: model, per the "generator is trusted for taste, never for constraints"
    #: rule. Keeps the box a topic name, not a sentence describing one.
    #:
    #: Mirrored by CUSTOM_TOPIC_MAX_WORDS in apps/web's onboarding form, which
    #: is a client-side courtesy only — this value is the authority.
    custom_topic_max_words: int = 5

    # -- quiz (ADR-0009, entry tier amended by ADR-0027) -------------------------
    quiz_mcq_count: int = 9
    quiz_free_text_count: int = 1
    quiz_pass_threshold: float = 0.80
    #: 70/30 (ADR-0009) split across quiz_mcq_count/quiz_free_text_count items.
    quiz_mcq_weight: float = 0.70
    quiz_free_text_weight: float = 0.30
    #: content-model.md's rubric: "0 none / 1 surface / 2 solid / 3 deep" — this
    #: level or above counts the free-text answer as correct.
    quiz_free_text_pass_level: int = 2
    #: Per-USER daily cap on LLM-graded free-text submissions. Unlike every other
    #: quota in this system, this one scales with user behavior, not corpus size
    #: (overview.md, Quiz Grading's cost profile) — a separate axis from the
    #: generation quota governor's per-(key, model) ladder, so it is its own
    #: setting rather than borrowing from `gemini_thinking_ladder`.
    quiz_free_text_grades_per_user_per_day: int = 20
    #: Server-side length cap (ADR-0009): nominally unlimited, capped generously
    #: so a pasted answer cannot blow the grading call's context window.
    quiz_free_text_answer_max_chars: int = 12_000

    #: ADR-0077 (AskAI). Per-user daily question cap, on the `ask_usage` counter
    #: -- the only limit; there is no quota reservation between AskAI and
    #: generation (they share the flash-lite ladder, which is ample). Generous
    #: enough to be invisible in normal use, low enough that one account cannot
    #: walk off with the day.
    ask_ai_daily_limit: int = 200
    #: Below this max cosine similarity between the question and the
    #: card/topic embeddings, AskAI refuses without spending an LLM call. An
    #: UNCALIBRATED guess -- there is no real question data yet (a calibration
    #: task, same shape as ADR-0001). Deliberately low so it only catches
    #: plainly-off-topic questions; the system prompt + the `OFF_TOPIC` sentinel
    #: are the finer gate. Ignored entirely under the `HashEmbedder` stand-in.
    ask_ai_topic_similarity_floor: float = 0.18
    #: How many nearest sibling cards (by `content_embedding`, within the topic)
    #: to fold into the AskAI retrieval context.
    ask_ai_context_neighbours: int = 4

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def gemini_api_key_list(self) -> list[str]:
        return [key.strip() for key in self.gemini_api_keys.split(",") if key.strip()]

    @property
    def mistral_api_key_list(self) -> list[str]:
        return [key.strip() for key in self.mistral_api_keys.split(",") if key.strip()]

    @property
    def gemini_pool_size(self) -> int:
        """How many keys the box arithmetic has to divide. For `fake` / `local`
        this is however many keys are configured (usually zero), which
        `max_concurrent_topics` reads as "no boxing"."""

        return len(self.gemini_api_key_list)

    @property
    def max_concurrent_topics(self) -> int:
        """How many generation jobs a worker pass runs at once (ADR-0082):
        as many whole boxes as the pool holds.

        Derived, never configured -- a second knob could disagree with the box
        size, and the pair "4 topics of 35 keys from a pool of 119" is a state
        no arithmetic can make safe.

        With no key pool to divide (`fake`, local -- every test) there is
        nothing to box and nothing to protect, so the only bound is
        `generation_batch_size`. A topic-per-key-box ceiling is about the
        provider's per-minute ceilings; a backend that never calls the provider
        should not inherit a limit that exists only because of them.
        """

        if self.gemini_pool_size < 1 or self.topic_key_box_size < 1:
            return self.generation_batch_size
        return max(1, self.gemini_pool_size // self.topic_key_box_size)

    @property
    def pool_thresholds_are_sane(self) -> bool:
        return self.pool_low < self.pool_high

    def rank_weights(self) -> dict[str, float]:
        return {
            "quality": self.rank_w_quality,
            "affinity": self.rank_w_affinity,
            "coverage": self.rank_w_coverage,
            "freshness": self.rank_w_freshness,
        }

    def session_signal_weights(self) -> dict[EngagementKind, float]:
        """Per-kind session-score contribution (ADR-0055).

        Kinds absent from this map contribute nothing. That is the right default
        for `impression` and `collapse` in particular: being shown a card, or
        closing one, is not evidence of interest in its topic. Undoing an action
        subtracts exactly what taking it added, so a mis-tap leaves no residue.
        """

        return {
            EngagementKind.EXPAND: self.session_w_expand,
            EngagementKind.EXPLICIT_COMPLETE: self.session_w_explicit_complete,
            EngagementKind.DWELL_COMPLETE: self.session_w_dwell_complete,
            EngagementKind.LIKE: self.session_w_like,
            EngagementKind.UNLIKE: -self.session_w_like,
            EngagementKind.BOOKMARK: self.session_w_bookmark,
            EngagementKind.UNBOOKMARK: -self.session_w_bookmark,
            EngagementKind.NOTE: self.session_w_note,
            EngagementKind.SHARE: self.session_w_share,
            EngagementKind.ASK_AI: self.session_w_ask_ai,
            EngagementKind.SKIP: self.session_w_skip,
        }


# The difficulty mix, per user tier (content-model.md). Config, not code: these
# will be tuned against engagement data.
#
# The upward slice is load-bearing beyond variety — it is the promotion signal.
# A beginner who consistently engages with their 20% intermediate cards is telling
# us they are ready to move up, so do not "simplify" it away.
DIFFICULTY_MIX: dict[Difficulty, dict[Difficulty, float]] = {
    Difficulty.BEGINNER: {
        Difficulty.BEGINNER: 0.80,
        Difficulty.INTERMEDIATE: 0.20,
    },
    Difficulty.INTERMEDIATE: {
        Difficulty.BEGINNER: 0.20,
        Difficulty.INTERMEDIATE: 0.70,
        Difficulty.ADVANCED: 0.10,
    },
    Difficulty.ADVANCED: {
        Difficulty.BEGINNER: 0.02,
        Difficulty.INTERMEDIATE: 0.08,
        Difficulty.ADVANCED: 0.90,
    },
}


@lru_cache
def get_settings() -> Settings:
    return Settings()
