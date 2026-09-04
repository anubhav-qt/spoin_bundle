# Architecture Decision Records

An ADR captures **one significant decision and the reasoning behind it**, at the moment
it was made. The value is not the decision -- it's the *why*, which is otherwise lost
within weeks.

## Why we bother

Two people, one codebase. Six months from now neither of us will remember why we
picked `procrastinate` over Celery, and we will waste an afternoon re-litigating it.
An ADR is how you disagree with a past decision *productively* -- you read the original
reasoning, check whether its assumptions still hold, and supersede it if they don't.

## When to write one

Write an ADR when a decision is **expensive to reverse** or **non-obvious to a newcomer**:

- Choosing between technologies (Postgres vs. a vector DB)
- Establishing a boundary (nothing imports LangChain directly)
- Accepting a tradeoff deliberately (batch worker instead of a persistent pool)

Do **not** write one for reversible, local choices (function naming, file layout within
a module). Those belong in code review.

## Format

Copy `TEMPLATE.md`. Number sequentially. Never renumber.

## Lifecycle

An ADR is immutable once **Accepted**. If a decision changes, write a *new* ADR that
supersedes the old one, and add a `Superseded by ADR-NNNN` line to the original.
Do not edit history -- the record of a decision we later reversed is often more
useful than the decision itself.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-python-fastapi-over-node.md) | Python + FastAPI over Node/NestJS | Accepted |
| [0002](0002-langchain-behind-an-interface.md) | LangChain, confined behind `ContentGenerator` | Accepted |
| [0003](0003-free-tier-first.md) | Free-tier-first infrastructure with a paid upgrade path | Accepted (amended by 0048, extended by 0049) |
| [0004](0004-topic-canonicalization.md) | Shared canonical topics with per-user display names | Accepted |
| [0005](0005-batch-llm-calls.md) | Batch every LLM call; never economize on tokens | Accepted |
| [0006](0006-demand-driven-pool-fill.md) | Demand-driven pool fill with degraded serving and hysteresis | Accepted (amended by 0007) |
| [0007](0007-curriculum-driven-generation.md) | Curriculum-driven generation with a bounded, completable corpus | Accepted |
| [0008](0008-local-gpu-generation.md) | Local GPU generation for seed content, cloud verification | Accepted |
| [0009](0009-quiz-gated-progression.md) | Quiz-gated difficulty progression | Accepted (amended by 0027) |
| [0010](0010-feed-serving.md) | Feed serving: stratified selection, linear ranking, slate pagination | Accepted (amended by 0050) |
| [0011](0011-engagement.md) | Engagement: append-only events, mutable state, derived aggregates | Accepted |
| [0012](0012-feed-visual-design.md) | Feed visual design: Thread layout, five committed palettes | Accepted |
| [0013](0013-topic-relationship-graph.md) | Topic-relationship graph: request-time embedding similarity, topics as nodes | Superseded by 0014 |
| [0014](0014-progress-insights-panel.md) | Right-rail insights: a progress-stats panel, not a relationship graph | Accepted |
| [0015](0015-topic-progress-and-discovery.md) | Per-topic progress box, engagement-stats modal, and topic discovery | Accepted |
| [0016](0016-theme-consolidation.md) | Replace Phosphor with a monochrome dark palette, Cyanotype with a light one | Accepted |
| [0017](0017-card-archetypes.md) | Archetype-based card rendering, color-only highlighting, motion | Accepted (amended by 0021; partially superseded by 0039) |
| [0018](0018-hero-mechanism-and-teaser-refinements.md) | Real hero mechanism, teaser refinements, block-expand modal | Accepted |
| [0019](0019-experimental-generated-fixture-content.md) | A second, honestly-tagged fixture for AI-generated content | Accepted |
| [0020](0020-rename-to-spoin.md) | Rename the product from Slocho to Spoin | Accepted |
| [0021](0021-ascii-scene-library.md) | ASCII art from a curated scene library, not from the generator | Superseded by 0042 |
| [0022](0022-dual-titles.md) | Every card carries a display title and a canonical title | Accepted |
| [0023](0023-reader-font-selection.md) | Five selectable reader fonts, with the monospace face locked | Accepted |
| [0024](0024-langgraph-for-card-generation-pipeline.md) | LangGraph for the card-generation pipeline, worker stays the scheduler | Accepted (amends 0002; amended by 0026, 0044) |
| [0025](0025-batched-llm-topic-matching.md) | Batched LLM topic matching, no thresholds | Accepted |
| [0026](0026-one-shot-generation-to-completion.md) | One-shot generation to completion, amends 0006 | Accepted (amends 0006; fixed by 0041) |
| [0027](0027-self-selected-entry-tier.md) | Self-selected entry tier; the placement quiz gate is dropped | Accepted (amends 0009; amended by 0032) |
| [0028](0028-key-model-quota-ladder.md) | Per-key-per-model quota grid, with a two-pool model fallback ladder | Accepted (resolves part of 0008; amended by 0029, 0030, 0040) |
| [0029](0029-questions-join-generator-pool.md) | Question generation moves to the generator (formerly "cards") pool | Accepted (amends 0009, 0028) |
| [0030](0030-two-pass-quality-gate.md) | Two-pass, self-correcting quality gate | Accepted (amends 0008, 0028) |
| [0031](0031-verification-feedback-and-per-tier-gate-durability.md) | Verification rejection feedback, and a per-tier durable gate | Accepted (amends 0030) |
| [0032](0032-entry-tier-quiz-still-earned.md) | The entry tier's own quiz is still earned, not free | Accepted (amends 0027) |
| [0033](0033-jwt-auth-and-guest-identity.md) | JWT auth, localStorage token storage, and guest identity via a nullable-email User row | Accepted |
| [0034](0034-per-topic-accent-color.md) | Per-topic accent color, composed with the active palette via relative color hue rotation | Accepted (amended by 0051) |
| [0035](0035-hero-card-tutorial-overlay.md) | First-time hero-card tutorial overlay; no new SEEN mechanism needed | Accepted |
| [0036](0036-topic-discovery-modal.md) | Topic discovery modal replaces the inline Discover list | Partially superseded by 0038 |
| [0037](0037-site-wide-font-picker.md) | Implement ADR-0023's font picker, site-wide, with live-preview/revert | Accepted |
| [0038](0038-restore-inline-discover-box.md) | Restore the inline Discover box below "Your topics" | Accepted (partially supersedes 0036) |
| [0039](0039-remove-swipe-to-dismiss.md) | Remove swipe-to-dismiss; cards are not draggable | Accepted (partially supersedes 0017) |
| [0040](0040-per-cell-call-serialization.md) | Serialize actual network calls per (key, model) cell | Accepted (amends 0028) |
| [0041](0041-per-group-gate-and-persist.md) | Gate+persist per subtopic group, not after a global fan-in | Accepted (fixes 0026) |
| [0042](0042-freeform-ascii-and-real-hero-mechanism.md) | Free-form generator-drawn ASCII art, and a real hero-card mechanism | Accepted (supersedes 0021) |
| [0043](0043-routers-are-transport-only.md) | Routers are transport; every domain gets a service module | Accepted |
| [0044](0044-generation-pipeline-as-a-package.md) | The generation pipeline becomes a package; `langgraph` confined to two files | Accepted (amends 0024) |
| [0045](0045-settings-surface-and-user-preferences.md) | A Settings surface, with preferences on the user row and no parallel system | Accepted |
| [0046](0046-one-collection-surface.md) | One collection surface shared by Saved, Liked, Profile and Settings | Accepted |
| [0047](0047-removal-of-legacy-concurrency-semaphore.md) | Remove legacy concurrency semaphore; QuotaGovernor manages full cluster concurrency | Accepted (amends 0024, 0026, 0028) |
| [0048](0048-cockroachdb-over-neon.md) | CockroachDB Basic over Neon, for corpus storage headroom | Accepted (amends 0003) |
| [0049](0049-no-message-broker-in-v1.md) | No message broker in v1; Kafka rejected, not deferred-by-accident | Accepted (extends 0003 §4) |
| [0050](0050-shown-consumes-a-card.md) | Being shown a card consumes it; a difficulty turns over instead of running dry | Accepted (amends 0010) |
| [0051](0051-topic-color-opt-out.md) | A "no color" opt-out for per-topic accent, via a sentinel hue | Accepted (amends 0034) |
| [0052](0052-undo-toast-for-collection-removal.md) | A single-slot undo toast for removal in Notes/Liked/Saved | Accepted |
| [0053](0053-topic-live-coverage-threshold.md) | Topic live coverage threshold for partial feed serving | Accepted (amends 0026) |
| [0054](0054-sequential-subtopic-ordering-and-infinite-filtered-feed.md) | Sequential subtopic curriculum ordering and true infinite filtered feed | Accepted (amends 0010, 0050) |
| [0055](0055-session-scoped-topic-shares.md) | The interleave plan is weighted by the current session, not long-run affinity | Accepted (amends 0010, 0011) |
| [0056](0056-generation-call-timeout-and-recovery-probe.md) | Client-side request timeout, and a background recovery probe for a stalled model | Accepted (amends 0028) |
| [0057](0057-redraft-loop-for-gate-attrition.md) | A per-tier redraft loop closes the gate-rejection gap left by a single draft-and-gate pass | Accepted (amends 0026) |
| [0058](0058-per-minute-vs-per-day-429.md) | A per-minute 429 and a per-day 429 are different facts, read off the payload | Accepted (amends 0028) |
| [0059](0059-card-planning-pass-and-prompt-versioning.md) | A planning pass before card writing, and a prompt version stamped on everything it produces | Accepted (amends 0026, 0030, 0057) |
| [0060](0060-unknown-429-scope-defaults-to-per-minute.md) | An unidentifiable 429 is a throttle, not an exhaustion | Accepted, superseded in part by 0084 (amends 0058) |
| [0061](0061-refund-grants-that-never-became-requests.md) | The prune refunds a grant that never became a request -- and only that | Superseded by 0084 (the `quota_request` table is dropped) |
| [0062](0062-daily-goal-ring-and-local-day-semantics.md) | Daily goal ring in the right rail; "today" is the reader's local day | Accepted |
| [0063](0063-mobile-shell.md) | A mobile shell -- a floating pill nav, and the right rail becomes a topics sheet | Superseded by 0064 |
| [0064](0064-mobile-shell-tab-bar.md) | Mobile shell, take two -- an edge-to-edge tab bar and a Browse sheet | Accepted (supersedes 0063; amends 0013, 0015) |
| [0065](0065-quota-governor-fairness-accounting-and-terminal-states.md) | Quota governor spreads load least-spent-first, refunds refused calls, learns its own rpm, and names why it stopped | Superseded in part by 0084 (least-spent-first + terminal states kept; AIMD replaced by a measured floor) |
| [0066](0066-redraw-over-budget-ascii-art.md) | Over-budget ASCII art is redrawn, then rejected with its card -- never silently dropped | Accepted (amends 0042, 0059) |
| [0067](0067-mermaid-diagrams-and-form-free-ascii.md) | Diagrams are written as mermaid and rendered client-side; ASCII scenes lose the stickman requirement | Accepted (amends 0042, 0017) |
| [0068](0068-curated-ascii-art-library-and-worked-few-shot-generator.md) | Curated ASCII art reference library and worked few-shot generator standards | Accepted (amended by 0079; amends 0042, 0067) |
| [0069](0069-mermaid-rendering-and-card-focus-guards.md) | Client-side Mermaid rendering resilience, and card focus/dwell guards | Accepted (amends 0067, 0017) |
| [0070](0070-server-side-appearance-preferences.md) | Palette + font move to the server; `localStorage` demoted to a pre-paint cache; saved themes and imported fonts | Accepted (amends 0045; builds on 0012, 0023, 0037, 0033) |
| [0071](0071-drop-font-keep-revert.md) | Font picker drops Keep/Revert -- selecting a font saves it, like the theme picker | Accepted (amends 0037) |
| [0072](0072-revisit-drops-its-bespoke-grid.md) | "Revisit" (formerly Saved) drops its tile grid + overlay and renders the same vertical Card list as Liked and Notes | Accepted (amends 0046) |
| [0073](0073-worker-runs-generation-jobs-sequentially.md) | The worker runs claimed generation jobs one at a time, in request order, instead of `asyncio.gather` | Superseded by 0082, then 0084 (amends 0026's implied concurrency) |
| [0074](0074-key-per-subtopic-scheduling.md) | One key per subtopic group for its whole card run (parallelism = key count, own-key-first ladder, weakest rung held as a reserve); questions move to a topic-wide phase | Accepted, amended by 0082/0083/0084 (amends 0028, 0065; reframes 0040, 0047) |
| [0075](0075-embedding-derived-topic-accent-color.md) | The default topic accent hue is embedding-derived from a colour vocabulary, distance-filtered against the user's other topics, and materialized at subscribe time | Accepted (amends 0034) |
| [0076](0076-report-a-card-and-operator-repair-lane.md) | Readers report a structurally-broken card; the owner triages each on an admin page (delete / fix / remake); fix & remake run as `kind='repair'` generation jobs that mint a new family version | Accepted |
| [0077](0077-askai-deterministic-single-call-retrieval.md) | AskAI is a topic-scoped, persistent, streamed conversation over deterministic retrieval; one flash-lite call per turn, off-topic held out by a free embedding gate + an `OFF_TOPIC` sentinel; 200 turns/user/day, no quota reservation | Accepted (revised same-session) |
| [0078](0078-topic-parallel-key-leases.md) | Many topics generate at once; each takes a key lease of `N` = its widest difficulty tier; the worker packs the queue so `sum(N) <= pool_size`; a spent group borrows a shared-reserve key per call | Reverted (see header) — never ran walk-away-safe; back to 0073/0074 sequential |
| [0079](0079-ascii-library-is-gags-only.md) | The ASCII art library is gags-only; every ASCII card is a joke, and the informative-visualisation file is no longer loaded | Accepted (amends 0068) |
| [0080](0080-ascii-fetcher-node.md) | A dedicated ASCII fetcher node picks one curated scene per ascii card and captions it; each scene is single-use within a topic; the writer no longer draws matched cards | Accepted (amends 0059, 0042, 0067, 0079) |
| [0081](0081-curriculum-as-a-worker-phase.md) | Curriculum generation as a pre-admission worker phase so `topic_tier_width` is real at lease time | Reverted (see header) — patched 0078's over-admission; reverted with 0078 |
| [0082](0082-fixed-key-boxes-per-topic.md) | A topic owns a FIXED box of keys (34) for its whole run and nothing outside it; the worker runs `pool // box_size` topics at once (2 at the 75-key pool), ADR-0074's ladder unchanged inside each box | Accepted (supersedes 0073; amends 0074; reworks 0078; refined by 0083; the mechanism is now 0084's balancer) |
| [0083](0083-least-spent-load-balancing-within-a-box.md) | Inside a box, spread least-spent-first per call instead of pinning a subtopic group to one key (the burst was tripping one cell's rpm); the gate spreads pool-wide; stop halving a cell's learned rpm on a scopeless 429 | Accepted; the mechanism is now 0084's balancer (amends 0074, 0060, 0065; builds on 0082) |
| [0084](0084-per-box-load-balancer.md) | A per-box in-memory load balancer replaces the DB-backed quota governor: RPD seeded once from `quota_ledger` then counted in memory, a trailing-60s window, a learned ceiling set to the measured send count on a 429, a 60s warm-up; `quota_request` + `model_unavailable` dropped | Accepted (supersedes 0058, 0061, the AIMD half of 0065; amends 0028, 0074, 0082, 0083) |
| [0085](0085-tokens-are-metered-too.md) | Meter tokens per minute, not just requests; token window per cell, prompt token budgeting, and batch cuts on heavy prompt consumers | Accepted (amends 0005, 0084) |
| [0086](0086-concurrency-staggering-and-initial-dispatch-jitter.md) | Concurrency staggering and initial dispatch jitter to stop edge gateway shedding under parallel fanout | Accepted (amends 0084, 0085) |
| [0087](0087-frog-is-a-sibling-package.md) | `frog` is a sibling Python package at `apps/frog/` that owns the embedder classes; `spoin` keeps the settings-reading factory and depends on frog, never the reverse; boundary enforced by `ruff` + an AST test | Accepted |
| [0088](0088-the-spoin-universe.md) | `the_spoin_universe` is a separate database with its own frog-owned alembic environment reading `SPOIN_UNIVERSE_DATABASE_URL`; `document`/`chunk` schema, content-hash idempotency, slug topic tags, retrieval cross-topic by default | Accepted (builds on 0087; amended by 0091) |
| [0089](0089-retrieval-grounded-generation.md) | Generation is grounded in retrieved corpus context for BOTH drafters and thinkers, packed against a token budget in `pack_by_tokens`' posture, and each card records the chunk IDs that grounded it | Accepted (amends 0030; builds on 0085, 0087, 0088) |
| [0090](0090-hybrid-gemini-mistral-generation.md) | One `HybridContentGenerator` splits by what a call produces — verdicts on Gemini's thinking cells, prose (incl. `correct_cards` and AskAI) on Mistral over raw `httpx`; none of 0082/0083/0084/0086's concurrency machinery is ported | Accepted, revised same-session (amends 0028, 0029, 0030, 0002; scopes 0084, 0086) |
| [0091](0091-corpus-category-hierarchy.md) | Categories and sub-categories become real columns on `document` (plus `scope`), nullable with a CHECK that makes them mandatory for `topic_source` and optional for `spoin_canon`; the hierarchy stays corpus-side, not in `spoin_db_2` | Accepted (amends 0088) |
| [0092](0092-qwen3-embedder-and-the-device-split.md) | The embedder becomes `Qwen/Qwen3-Embedding-0.6B` at 1024-d, `Embedder` gains `embed_query`/`embed_passage`, GPU for bulk and CPU for the request path — one model on both devices, because dimension parity is not space parity | Accepted (amends 0087, 0077) |
| [0093](0093-normalize-topic-text-moves-into-frog.md) | `normalize_topic_text` moves from `spoin.embeddings` into `frog.embeddings` and `spoin` imports it — it is a pure function with no settings dependency, and the ingester needs it on frog's side of the boundary | Accepted (amends 0087) |
