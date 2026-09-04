# Task 0038: `frog` (our own RAG), `the_spoin_universe`, and hybrid Mistral/Gemini generation

> **Status:** Phases 0 and 1 done (2026-09-04). ADRs 0087-0090 accepted;
> `apps/frog` exists, passes `make check`, and carries the `document`/`chunk`
> schema and its own alembic chain. **The corpus database itself has not been
> created yet** — the owner runs `make universe-migrate`. Phase 2 next.
> Written 2026-09-04.
> **Depends on:** [`docs/mistral-saga/`](../mistral-saga/README.md) — provider
> validation. Experiments 1, 2 and 3 have passed; 3b (drafting quality) is
> deliberately folded into Phase 6 below rather than run standalone, because this
> plan changes what it should test.

## The problem

Three things arrived at once and they are the same problem:

1. **We are becoming model-independent.** The Gemini free tier's undocumented
   IP-keyed concurrency wall ([gemini-saga](../gemini-saga/README.md)) proved that
   building on one provider's quirks is a four-week tax. Mistral passed its
   concurrency sweep with no wall through N=5, but its usable models are all small
   (`ministral-3b/8b/14b`) and its account tier serves **no reasoning-capable
   model at all** ([mistral-saga doc 3](../mistral-saga/03-findings.md)).
2. **Small drafting models need external grounding.** A 3B–8B model has weaker
   parametric recall than `gemini-3.x-flash`. If Mistral is going to draft, the
   facts have to come from somewhere other than the model's own memory.
3. **We have never had retrieval-grounded generation.** Today the writer drafts
   from parametric knowledge and the gate checks it *after the fact*
   ([ADR-0030](../adr/0030-two-pass-quality-gate.md)). There is no
   source-of-truth corpus and no retrieval over one. Verified: nothing in
   `generation/` or `content/` does topic-level factual grounding.

## Why it matters

The corpus is the product. Quiz-gated mastery of *true things* is the claim
(CLAUDE.md), and right now the truth guarantee is entirely a post-hoc gate. Adding
retrieval grounding moves it upstream, makes it auditable ("this card is backed by
this source"), and is the precondition for using cheaper, smaller, faster models
without quality collapse.

## Ownership

| Track | Owner |
|---|---|
| Corpus authoring (`the_spoin_universe` content) | **Antigravity, supervised by the project owner** |
| Everything else (frog, ingestion, retrieval, hybrid generator, measurement) | implementing session |

Corpus content is **not** the implementing session's job. What the implementing
session owes that track is a **stable ingestion contract** — see Phase 2.

---

## Build order

**frog first, then measure, then test Mistral.** Real post-RAG prompt sizes are
discovered by building the thing and looking, not by picking a budget up front and
hoping. So: build frog (Phases 1–3) → measure what prompts actually grew to
(Phase 4, step 1) → only then sweep Mistral concurrency at those real sizes
(Phase 4, step 2).

Corpus authoring runs in parallel from the start — it is externally owned and
gates Phase 3, not Phase 1.

### The constraint frog must respect while being built

Measurement comes after, but the arithmetic still binds *during* design: if frog's
context assembly is built to return 40k tokens, `ministral-8b` is already dead
before anything is measured.

Sustainable calls/min = `min(TPM / prompt_tokens, RPM)`, against the ~34 calls/min
that 600 cards/hr needs:

| prompt size | `ministral-3b` (1.3M TPM, 750 RPM) | `ministral-8b` (625k, 188) | `ministral-14b` (937.5k, **30 RPM**) |
|---|---:|---:|---:|
| 12k (today) | 108 | 52 | 30 |
| 20k | 65 | 31 | 30 |
| 30k | 43 | 21 | 30 |
| 40k | 33 | 16 | 23 |

- **`ministral-8b` drops below 34/min above ~18k tokens.**
- **`ministral-3b` holds 34/min to ~38k** — the only usable model with real RAG room.
- **`ministral-14b` is RPM-capped at 30/min and can never reach 34**, at any size.
- At the currently realistic ~220–340 cards/hr (≈12–19 calls/min), 8b is fine to
  ~33k. The *target* rate is what tightens this.

**Treat this as a design budget to aim at, not a prediction.** Phase 4 measures
what actually happened and picks the model from real numbers.

---

## Phase 0 — Decisions, no code

Four ADRs. CLAUDE.md's rule: a decision with real reasoning gets an ADR, and a
rule that must hold gets enforced twice, never documented once.

| ADR | Decision |
|---|---|
| **0087** | `frog` is a separate importable package at `apps/frog/`, not a service and not a package inside `spoin`. Owns the embedder. |
| **0088** | `the_spoin_universe` is a separate database holding all source-of-truth material; retrieval is **cross-topic by default**. |
| **0089** | Retrieval-grounded generation: what gets retrieved, how context is assembled and capped, how provenance is recorded on a card. |
| **0090** | Hybrid provider: Gemini thinking rungs + Mistral generator rungs behind one `ContentGenerator`. |

### ADR-0087 decisions to make

- **Library, not service.** Retrieval happens several times per generation call;
  an HTTP hop per retrieval adds latency and a failure mode for no benefit.
  `apps/api` takes a path dependency on `apps/frog`. (`apps/helpers/` is precedent
  for a non-service sibling, though it has no `pyproject.toml` — frog needs one.)
- **frog owns the embedder.** `spoin.embeddings` currently provides
  `get_embedder()` (local, never-quota'd, `BAAI/bge-small-en-v1.5`, **384-dim**,
  with a deterministic `HashEmbedder` stand-in for tests). A sibling app cannot
  import from `spoin` without inverting the dependency — so **move the embedder
  into frog** and have `spoin` import it from there. One direction: `api → frog`.
  This also lets `content/ascii_library.py`'s hand-rolled cosine search sit on
  frog later.
- **Vectors stay 384-dim**, same model, or corpus vectors and existing
  `card.content_embedding` vectors are not comparable.
- **Enforce the boundary twice** (CLAUDE.md): frog must not import `spoin`. A
  `ruff` `banned-api` entry plus an AST check in `tests/test_architecture.py`,
  same pattern as ADR-0002's langchain confinement.
- `make check` must cover `apps/frog` — `mypy --strict` and `ruff` there too.
- `apps/api/Dockerfile` only `COPY`s `src`. A sibling path dependency needs
  Dockerfile and compose changes. **Budget real time for this**; it is the main
  friction of the sibling-package choice. If it proves disproportionate, the
  fallback is `apps/api/src/spoin/frog/` — worse layering, far less packaging work.

### ADR-0088 decisions to make

- **A separate database, `the_spoin_universe`**, in the same Postgres instance.
- ⚠️ **It shares the `db-data` volume with `spoin_db_2` and `spoin_db_test`.** The
  standing prohibition on `docker compose down -v` / `make clean` / `docker volume
  rm` now protects **three** databases. Creating a new database is non-destructive
  and fine; nothing here relaxes CLAUDE.md's DB rules.
- **Migrations:** `alembic.ini` points at `SPOIN_DATABASE_URL`. A second database
  needs either a second alembic environment or frog managing its own schema.
  Decide and write it down — a half-answer here is how a migration lands on the
  wrong database.
- **Cross-topic retrieval by default.** A PostgreSQL card may ground itself in
  distributed-systems material. Risk: retrieval drags a card off its subtopic.
  Mitigation already exists — the gate's topic-conformance check — but inspect the
  retrieval scores in Phase 3, don't assume.

---

## Phase 1 — frog skeleton — *"tadpole emerges"*

- `apps/frog/` with `pyproject.toml`, `mypy --strict` + `ruff` wired into `make check`.
- Embedder moved in from `spoin.embeddings`; `spoin` updated to import from frog.
- `the_spoin_universe` schema: `document` (provenance — source, title,
  ingested_at, source_date; `author`/`licence` were dropped, see
  [ADR-0088](../adr/0088-the-spoin-universe.md)) and `chunk` (text, `Vector(384)`,
  topic tags, ordinal, FK to document). Provenance is not optional: "we can back with grounding why our
  material is high quality" is a **claim about citability**, so the citation has to
  be storable.
- The architecture test that frog never imports `spoin`.
- No ingestion, no retrieval yet. Ends with an empty, migrated, type-checked store.

### What Phase 1 actually landed (2026-09-04)

Everything above, plus three things worth knowing before Phase 2:

- **The Docker friction was real but bounded.** The build context moved to the repo
  root for the `api`, `seed`, `worker`, `test` and new `universe-seed` services. Each
  of those services builds its **own** image — rebuilding only `api` leaves the test
  image stale, which fails as `ModuleNotFoundError: No module named 'frog'`.
- **`downgrade()` on the initial universe migration raises.** Dropping those tables
  drops the whole corpus; the recovery path is recreate-and-re-ingest, which is
  explicit, rather than an `alembic downgrade` that reads as routine.
- **Pre-existing `ruff` format drift surfaced** in three unrelated files. `ruff>=0.8`
  is unpinned, so the rebuild pulled 0.16.6 and its formatter disagreed with whatever
  last touched them. Fixed in its own commit (`3385f43`). Worth pinning ruff at some
  point so a rebuild is not a formatting event.

---

## Phase 2 — Ingestion and the corpus — *"tadpole grows legs"*

**Corpus authoring is Antigravity's, supervised by the owner.** This phase builds
the machinery that consumes it.

> **The ingestion contract v1 is written and delivered:**
> [`docs/handoff/antigravity-corpus-authoring.md`](../handoff/antigravity-corpus-authoring.md)
> (2026-09-04). Phase 2 builds the ingester **against that document**, not the other
> way round. Front matter may gain fields as the ingester is written; nothing in it
> should be removed without telling the authoring track.

### The ingestion contract (the implementing session's real deliverable here)

Define and document the format Antigravity delivers into — file layout, front
matter, required provenance fields, topic tagging, how a document declares which
of the two content kinds it is. **Write this before the corpus is authored**, or
ingestion gets retrofitted around whatever shape arrives.

**Ingestion must be idempotent** — re-ingesting an unchanged document must not
duplicate chunks. Assume the corpus will be re-delivered many times as it is
supervised and revised.

### The two content kinds (not interchangeable)

1. **Spoin canon** — how the product itself works: what a card is, dual titles
   ([ADR-0022](../adr/0022-dual-titles.md)), archetypes
   ([ADR-0017](../adr/0017-card-archetypes.md)), quiz-gated progression
   ([ADR-0009](../adr/0009-quiz-gated-progression.md)), how the feed scrolls, what
   makes a hook land, the ASCII box rule, and CLAUDE.md's
   silliness-in-the-hook-layer rule. **Purpose:** a small model does not know our
   conventions; this is how it writes on-spec instead of generically. Largely
   distillable from CLAUDE.md, `content-model.md` and the ADRs.
2. **Topic source-of-truth** — curated, short, dense authoritative material per
   topic.

⚠️ **The corpus is the ceiling on card quality.** A thin or wrong corpus produces
confidently-grounded wrong cards — worse than parametric guessing, because it
*looks* sourced. Worth saying plainly to the track that owns it.

---

## Phase 3 — Retrieval and prompt integration — *"frog achieved"*

- Query → embed → pgvector search → top-k, cross-topic, filters available but not
  applied by default.
- **Context assembly against a token cap.** ADR-0085's `pack_by_tokens` is the
  existing precedent for packing to a budget; reuse the posture, don't reinvent.
  Aim at the design budget in "Build order" above.
- Wire into the generator prompts. **Both thinkers and generators use frog** — the
  verification pass grounding its factual check in the same corpus the drafter used
  is the point, not a nicety.
- **Return chunk IDs and record them on the card** so a card can cite what grounded
  it.
- Inspect retrieval scores on cross-topic hits (the ADR-0088 risk above).

---

## Phase 4 — Measure real sizes, then sweep Mistral

Strictly in this order.

### Step 1 — What did prompts actually grow to?

Measure the real post-RAG distribution per call type from run logs (`chars=` on
`lbprobe call` lines), not estimates. Identify the **largest** generator call —
candidates are `generate_cards` with a full brief, and `fetch_ascii_scenes`
(ADR-0085 notes it packs against the prompt-token budget because each candidate
carries a whole artwork).

### Step 2 — Sweep concurrency at those sizes

Only now. The probe already supports it — no new code:

```bash
docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe \
  concurrency --min 2 --max 8 --model ministral-3b-2512 --prompt-tokens <measured>
```

Also run **`soak`** (30 min at the chosen N) — still outstanding from the
validation plan, and the failure mode it catches (a slow-accruing penalty, as
Gemini had) is invisible to a 6-minute arm.

**Known gap:** the probe's synthetic prompt is inert filler; a real RAG prompt has
different structure. Fine for transport limits. If fidelity matters, extend the
probe to accept a captured real prompt from a file.

**Output:** measured max prompt size, the model that choice implies, a sweep table
at the real size, appended to [mistral-saga doc 3](../mistral-saga/03-findings.md).

---

## Phase 5 — `MistralContentGenerator` + `HybridContentGenerator`

**Recommendation: raw `httpx`, not `langchain-mistralai`.** The probe already
proved the exact request shape (OpenAI-compatible `POST /v1/chat/completions`,
`response_format: {type: json_schema, strict: true}`) works at 12k tokens across
646 calls. Raw httpx avoids a new LangChain dependency and a new ADR-0002
`banned-api` entry. Parse into the existing `_LenientWireModel` Pydantic models.

**Most of the Gemini machinery is not needed.** No key pool, no box leasing, no
quota ledger, no load balancer — Mistral needs one key, a send path,
structured-output parsing, a modest in-flight cap, and retry on 429/503. Resist
porting ADR-0082/0084 wholesale; it solves a problem Mistral does not have.

`HybridContentGenerator` implements the `ContentGenerator` ABC and routes:

| Role | Methods | Provider |
|---|---|---|
| Generator (prose) | `plan_cards`, `fetch_ascii_scenes`, `generate_cards`, `correct_cards`, `generate_questions`, `repair_card_structure`, `stream_topic_answer` | **Mistral** |
| Thinking (verdicts) | `generate_curriculum`, `match_topics`, `validate_topic_names`, `verify_cards`, `grade_free_text` | **Gemini** |
| Key/scope | `claimed_key_scope`, `lease_key_box`, `release_key_box` | **Gemini** (box leasing is Gemini-pool-specific) |

**The table above has been corrected and then extended by an owner decision.**
Checked against `langchain_impl.py`'s `_invoke_with_retry` call sites as this line
originally instructed: `stream_topic_answer` (AskAI, ADR-0077) and `match_topics`
were missing from the draft entirely. The owner then settled the split as
**verdict on the thinker, prose on the generator** — which keeps `correct_cards`
on Mistral (the draft's placement) but for a stated reason, and pins `verify_cards`
to Gemini permanently. `correct_cards` runs on the generator ladder from the first
pass, not only after a redraft round: correction happens against retrieved source,
so it is restatement rather than recall. See
[ADR-0090](../adr/0090-hybrid-gemini-mistral-generation.md).

---

## Phase 6 — Do Mistral generators pass Gemini thinkers?

*The load-bearing experiment; replaces the standalone experiment 3b in the
validation plan.*

- Draft a subtopic's cards with Mistral **on frog**, gate with Gemini **on frog**.
- Compare accept rate against a Gemini-drafted baseline on the same subtopic.
- **Thresholds, fixed now, before the data exists** (the validation plan's own
  discipline — Benchmark 9 was called a breakthrough and superseded within a day):
  - **Pass:** within ~10 points of the Gemini baseline.
  - **Marginal:** 10–25 points below → try `ministral-14b`, or restrict Mistral to
    the ASCII-fetch sub-task.
  - **Fail:** >25 points below.
- **Report `bad_schema`, gate-rejection and call-failure as three separate
  counts.** CLAUDE.md's rule: a call that never returned a verdict is not the same
  fact as content judged and found bad.

### ⚠️ Decision point — ASK THE OWNER before implementing: how to enforce the ASCII box rule

**Do not pick a mechanism unilaterally. Ask.** This likely warrants its own ADR
(next free number, ADR-0091).

**The gap.** `ASCII_INSTRUCTIONS` rule 3 (BOX INTEGRITY, STRICT) says the art is a
rigid box: nothing edited inside it, nothing inserted to its **left** (which
misaligns monospace columns), captions only **top / bottom / appended right**,
total width ≤ 40. It is enforced **by prompt instruction only.** The 40-column
width rule, by contrast, has a real server-side check and redraw loop
(`_ascii_over_budget_lines`, ADR-0066). So a box-rule violation ships undetected —
and a smaller drafting model is exactly the condition under which instruction-only
rules start failing. This is CLAUDE.md's "trusted for taste, never for
constraints" pointing at a live gap.

**The asymmetry that shapes the options.** For a **fetched** scene (ADR-0080) we
have the original library art, so a violation is *precisely* checkable. For a
**free-drawn** fallback scene there is no source to compare against.

Options to put to the owner:

| # | Mechanism | Notes |
|---|---|---|
| a | **Diff against the source library entry** — every original line must survive unmodified with its leading whitespace intact; additions allowed only as whole new lines above/below or as suffixes | Precise, deterministic. **Fetched path only.** |
| b | **Bounding-box heuristic** — compute the art's left edge, reject anything that shifts it | Covers free-draw too, but must guess what is art vs caption |
| c | **Redraw loop**, mirroring ADR-0066's width fix — detect, hand back, reject after N attempts | Composes with (a) or (b); costs calls |
| d | **Drop the visual, keep the card** — ADR-0042's original degrade posture | Cheapest; ADR-0066 already moved away from it for width |
| e | **Measure first, enforce later** — use Phase 6's data to size the problem before building anything | Phase 6 gives this for free |

Phase 6's run should **record box-rule violation counts regardless of which
mechanism is chosen**, so the decision has data behind it.

---

## Phase 7 — Single topic end-to-end + manual review

- Generate **one new topic** (not one of the existing 41) so the comparison is
  clean and nothing existing is disturbed.
- Generating into `spoin_db_2` is sanctioned — CLAUDE.md: testing the pipeline
  populates the live corpus with authentic content. **Do not delete it afterwards
  without explicit approval.**
- Review in the real feed UI, not a terminal: hooks, ASCII rendering at 40 columns
  on a phone width, quiz quality, and whether grounding actually improved factual
  density or just made cards drier.
- Write it up as a benchmark doc alongside the existing run benchmarks.

---

## Commit message theme

`tadpole emerges` (Phase 1) → `tadpole grows legs` (Phase 2) → `frog achieved`
(Phase 3).

## Timebox

Phases 0–1 are a session. Phase 2's machinery is a session; its corpus content is
externally owned and open-ended, and gates Phase 3. Phases 3–7 are a session each.

## Hand back

- ADRs 0087–0090 (plus 0091 if the box rule gets one).
- The ingestion contract, written before the corpus arrives.
- `apps/frog/` passing `make check`.
- Measured real prompt sizes + a concurrency table at those sizes, in
  [mistral-saga doc 3](../mistral-saga/03-findings.md).
- Phase 6's three-way count table, box-rule violation counts, and a verdict against
  the fixed thresholds.
- A Phase 7 benchmark doc.
