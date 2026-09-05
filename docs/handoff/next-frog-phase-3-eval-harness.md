# Handoff: task 0038, finishing Phase 3 — the eval harness, and the embedder that gates everything

> **Historical as of 2026-09-05.** Read it for reasoning, not for state. Three things
> it describes are gone: the embedder it calls a blocker is packaged and shipped
> (ADR-0097 — one embedder, `qwen3` at 1024 dims, everywhere); `grounding_token_budget`
> and `grounding_max_chunks` no longer exist, replaced by a flat
> `grounding_chunks = 2`; and `spoin_db_2` was dropped and rebuilt empty, so every row
> count in here describes a database that no longer holds them.
>
> Written 2026-09-05 at the end of the session that landed retrieval, grounding, prompt
> wiring and card provenance (`38f49ee` → `8a8e64c`, pushed). Supersedes
> [`next-frog-phase-3-retrieval.md`](next-frog-phase-3-retrieval.md), which is now
> history — read it only for the reasoning behind decisions this one assumes.

---

## What you're picking up

**Retrieval is built, wired, and running against nothing.**

Every content prompt now carries retrieved corpus passages. The plumbing is complete and
tested end to end. But `corpus_embedder` defaults to `hash`, so what it retrieves is
noise — and **that is the first thing you have to fix, because nothing downstream can be
measured until it is.**

Your job is what Phase 3 still owes: a real embedder on the generation path, the eval
harness, and the cross-topic score inspection ADR-0088 asked for. Then Phase 4 measures
prompt sizes and sweeps Mistral. Not yours until the eval has run.

## Read in this order

| | |
|---|---|
| `CLAUDE.md` | the bootstrap. Four databases; the prohibitions are unchanged |
| [`docs/tasks/0038-...`](../tasks/0038-frog-rag-and-hybrid-generation.md) | Phase 3's "what landed" and "what it still owes" — start there |
| ADR [0089](../adr/0089-retrieval-grounded-generation.md) | what you are finishing |
| ADR [0096](../adr/0096-canon-is-pinned-not-retrieved.md) | new: canon is pinned per call type, not retrieved. Amends 0088 |
| ADR [0094](../adr/0094-local-generation-lightweight-production.md) | why torch is not in the api image — the constraint behind blocker 1 |
| [`rag-design-space.md`](../architecture/rag-design-space.md) | §3.2 is your eval harness. §3.3, §3.4, §3.10, §3.11 are deliberately deferred |
| [`docs/tasks/0039-...`](../tasks/0039-embedder-never-reached-the-containers.md) | why `card.content_embedding` is still 384-d |

## Already true — don't rebuild it

- **`frog.retrieval`** — `search` / `search_many`. Cross-topic by default; `kinds`,
  `topic_tags`, `min_score`, `exclude_document_ids`, `exclude_chunk_ids` all exist and
  are all off. Returns chunk ids, cosine **similarity** (not pgvector's distance) and
  document provenance. `corpus_version()` for cache keys.
- **`spoin.generation.grounding`** — searches, packs to a token budget, renders the
  prompt block, caches per subtopic **group** keyed on the corpus version. Three
  outcomes: `GROUNDED` / `NO_MATCH` / `UNAVAILABLE`. It never raises; an unreachable
  corpus degrades to ungrounded generation.
- **Prompt wiring** — `plan_cards`, `generate_cards`, `correct_cards`, `verify_cards`,
  `generate_questions`, and the `remake` repair path. All five get the **same** block
  for a subtopic group, asserted end to end in
  `test_every_content_call_in_a_run_sees_the_same_passages`.
- **`prompts/sources.py`** — what the model is told to do with the passages, including
  the tier-language instruction Phase 3 owed.
- **`card.grounded_chunk_ids`** — ARRAY(UUID) + GIN. **Migration `a1b2c3d4e5f6` is
  APPLIED to `spoin_db_2`** (owner-approved, 2026-09-05). 5,491 existing cards are NULL,
  which is correct for them.
- **The corpus engine is opened READ ONLY** at the Postgres level (`core/db.py`).
- `make check` green: 571 api + 56 frog.

## The three blockers, in order

### 1. A real embedder on the generation path — *everything waits on this*

`SPOIN_CORPUS_EMBEDDER` defaults to `hash`. `HashEmbedder` is dimension-correct and
semantically meaningless, so **a run grounded on it is grounded on nothing** — and
nothing raises. Setting it to `qwen3` needs `sentence-transformers` + torch, which
[ADR-0094](../adr/0094-local-generation-lightweight-production.md) deliberately keeps out
of the image `api`/`worker`/`seed`/`test` all build from.

This is an owner decision, not yours to pick:

- put the `embeddings-gpu` extra in the worker image only (generation is local anyway,
  ADR-0094 — but `api`/`worker` currently share one Dockerfile), **or**
- give the worker its own image the way `frog` has one, **or**
- something else. AskAI's off-topic gate needs a CPU embedder on the *server* too
  (ADR-0077/0092), so the same question is waiting on the deployed side.

**Ask before building any of it.** Until it is settled, every number you can produce
about grounded output is meaningless.

### 2. The eval harness — §3.2, and the gate on every tuning decision

**No ANN index, no reranker, no hybrid retrieval, and no `min_score` floor until this has
run.** The whole reason there is deliberately no HNSW index today is that an approximate
index would make retrieval numbers reflect index recall rather than embedding quality,
and a bad number would be unattributable.

Owner's decisions, already made — don't re-ask:

- **Ground truth is a hand-labelled golden set.** 30–50 real subtopic queries.
- **Reviewed as an HTML artifact with checkboxes that saves labels back.** Load the
  `artifact-capabilities` skill before writing it — it needs a capability that persists
  state, not `localStorage`.
- Output: recall@k and precision@k.

Shape: pull real subtopics out of `spoin_db_2` (read-only), build each one's query with
`grounding.build_query`, retrieve a candidate pool wider than any prompt would use, and
put the pool in front of the owner to mark relevant / not.

`min_score` stays unset until this produces a number. A floor chosen before the harness
is an invented constant, and this session already shipped one of those (see below).

### 3. Cross-topic score inspection — ADR-0088's named risk

Retrieval is cross-topic by default, on the argument that a PostgreSQL card may
legitimately ground itself in distributed-systems material. Nobody has checked what that
does at scale. All that exists is a **5-query smoke** from the previous session:
off-subtopic hits landed at 0.435–0.440 against 0.653 for the correct one, so a k≈3 cut
excluded them. **That is five queries, not a finding.**

Needs the real embedder, so it runs in the `frog` image. Read-only against
`the_spoin_universe`.

## Things that will waste your time if you don't know them

**The ingested corpus is stale again.** The authoring track committed a Rust survey suite
(`d9c72fe`) mid-session, and more will land. `make corpus-ingest` is idempotent by
content hash, so re-running is cheap — but it needs the GPU, so it is the owner's to run.
Check `corpus_version()` against the files on disk before drawing conclusions from a
retrieval result.

**The working tree is CRLF (`core.autocrlf=true`).** Scripted `str.replace` over these
files silently no-ops against `\n` patterns. Use the Edit tool, or normalise line endings
in the script and restore them on write. A prior session lost work to exactly this.

**Two embedders, deliberately.** `get_embedder()` writes `card.content_embedding`
(384-d); `get_corpus_embedder()` queries the corpus (1024-d, ADR-0092). They are not
interchangeable and sharing one is a dimension error, not a quality loss. Task 0039 is
where they converge.

**The canon drift guard needs `docs/` mounted.** The `api` image carries no corpus; the
`test` service mounts `docs/the_spoin_universe` read-only. The guard raises rather than
passing when it cannot find the corpus — keep that.

**Any call that edits existing artwork needs the box rule.** `fetch_ascii_scenes` adapts
a library scene and `correct_cards` rewrites art. Both were missed on the first pass of
`canon.py`'s map, and the failure is silent: art renders broken, nothing raises. Check it
whenever a call type is added (ADR-0096's "revisit when").

## What was decided this session, and what is still the owner's

**Settled — don't re-ask:**

| | |
|---|---|
| Canon | pinned per call type, condensed, sha256-guarded ([ADR-0096](../adr/0096-canon-is-pinned-not-retrieved.md)) |
| Provenance | real column + GIN index, migration applied |
| Grounding scope | all five content calls plus `remake` — not just the drafter and verifier ADR-0089 names. Owner accepted this after the fact |
| `grounding_token_budget` | **3000**, owner's number, chosen against a measured corpus |

**Still open for the owner:**

- **The embedder image question** (blocker 1). Nothing moves until this does.
- **Whether the prompt growth is acceptable.** Grounding adds ~3,000 tokens of passages
  plus ~180 (writer) / ~150 (judge) / ~140 (tier language) of fixed instruction, on top
  of the +200–836 the pinned canon already added. Owner's position is "good for now";
  Phase 4 is where it gets decided with data.
- **Per-section `topic_tags`.** The column is per-chunk by design, but the contract has
  no per-section tagging, so every chunk inherits its document's.
- **The ASCII box rule enforcement** — still Phase 6's open decision, five options tabled
  in the task doc. Ask, don't implement.

## One mistake worth not repeating

`grounding_token_budget` shipped at **6000**, derived by subtracting two numbers from
ADR-0089's table — arithmetic dressed as a measurement, which is precisely what task
0038's build order forbids. It was also **dead code**: the corpus's median passage costs
434 prompt tokens, so the 8-passage cap always bound first and the budget never fired.
Nothing failed. Nothing could have noticed.

It is now 3000, with `test_the_token_budget_binds_before_the_chunk_count` running the
shipped settings against a median-sized passage and failing if the count starts binding
again. **Measure the corpus before choosing a constant about the corpus** — the numbers
are one SQL query away.

## Then Phase 4 (not this)

Strictly after the eval harness, and strictly in this order: measure real post-RAG prompt
sizes from run logs (`chars=` on `lbprobe call` lines), then sweep Mistral concurrency at
those measured sizes. Both need blocker 1 resolved first — measuring a hash-grounded
prompt measures the wrong thing.

---

## Prompt for a fresh session

> Read `CLAUDE.md`, then `docs/handoff/next-frog-phase-3-eval-harness.md`. You are
> finishing task 0038 Phase 3. Retrieval is built and wired; what remains is a real
> embedder on the generation path, the eval harness, and the cross-topic score
> inspection. Start by putting the embedder image question to the owner — it gates
> everything else, and it is not yours to decide. Do not build an ANN index, a reranker
> or a `min_score` floor before the eval harness has produced numbers.
