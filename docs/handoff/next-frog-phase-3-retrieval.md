# Handoff: task 0038 Phase 3 — retrieval and the eval harness ("frog achieved")

> Written 2026-09-05 at the end of the session that landed Phase 2, ADRs 0093–0095, and
> the first real ingestion. Paste the prompt at the bottom into a fresh session, or read
> this directly.

---

## What you're picking up

`the_spoin_universe` **exists and is loaded**. `frog/ingest/` fills it; nothing reads it
back yet. **Your job is Phase 3: retrieval over the corpus, wired into the generator
prompts, plus an eval harness.**

After you, Phase 4 measures real prompt sizes and sweeps Mistral concurrency at them.
Not your job.

## Read in this order

| | |
|---|---|
| `CLAUDE.md` | the bootstrap. Note it now says **four** databases |
| [`docs/tasks/0038-...`](../tasks/0038-frog-rag-and-hybrid-generation.md) | the plan. Phase 3 is yours; read Phase 2's "what landed" first |
| ADR [0089](../adr/0089-retrieval-grounded-generation.md) | **the ADR you are implementing** — what gets retrieved, the token budget, chunk-ID provenance |
| ADR [0088](../adr/0088-the-spoin-universe.md) | cross-topic by default, and the risk it names for you to inspect |
| ADR [0092](../adr/0092-qwen3-embedder-and-the-device-split.md) | the asymmetric embedder. Getting this backwards is silent |
| ADR [0085](../adr/0085-tokens-are-metered-too.md) | `pack_by_tokens` — reuse the posture, don't reinvent |
| [`docs/architecture/rag-design-space.md`](../architecture/rag-design-space.md) | what comes after, and which ideas are deliberately deferred |

## Already true — don't redo it

- **The corpus database is live.** 90 documents, 646 chunks, embedded with
  `Qwen3-Embedding-0.6B` at 1024-d on the RTX 5070. Verified semantic, not hash.
- **Ingestion is idempotent and fast** — a full run is ~30s, and re-running on an
  unchanged corpus writes nothing. `make corpus-ingest`.
- **`make corpus-check`** validates the delivered corpus with no GPU, no database and no
  model. That purity is load-bearing; don't add network calls to it.
- **`normalize_topic_text` lives in `frog.embeddings`** now (ADR-0093), not `spoin`.
- **The `frog` compose service** is the only image with torch + CUDA. Built and verified:
  torch 2.11.0+cu128, RTX 5070, capability (12, 0).
- `make check` green: 45 frog tests + 534 api tests.

## Things that will waste your time if you don't know them

**The ingested corpus is already stale.** 112 documents on disk versus 90 ingested — the
authoring track commits continuously, and it did so several times *during* the last
session. **Run `make corpus-ingest` before you measure anything**, and re-run it before
you trust any eval number. It is idempotent, so this is cheap and safe.

**Retrieval must use `embed_query`, ingestion used `embed_passage`.** ADR-0092 made
`Embedder` asymmetric precisely because getting this backwards is a **silent recall loss**,
not an error. This is the single easiest catastrophic mistake in the phase.

**Chunk text already contains a contextual header.** Every chunk is stored as
`<document title> — <section heading>\n\n<prose>`. Do not strip it when assembling
context, and do not add a second one — the model reading a retrieved chunk is meant to see
that line.

**There is no ANN index on `chunk.embedding`, deliberately.** Only `pk_chunk`, the
ordinal index and a GIN on `topic_tags`. At 646 chunks a sequential scan is fast *and
exact*. pgvector's HNSW is **approximate**, so adding it before the eval harness runs would
make your retrieval numbers reflect index recall rather than embedding quality — you would
not be able to tell a bad number from a lossy index. **Measure first, index second**, and
when you do add one, re-run the eval to quantify what it cost.

**The two databases hold incomparable vectors, on purpose.** `the_spoin_universe` is
1024-d Qwen3; `spoin_db_2` is still 384-d `HashEmbedder` output (task 0039). Never compare
a card vector to a chunk vector. The divergence ends at the regeneration wipe, not before.

**`spoin_db_2` is untouched and must stay that way** — 41 topics / 447 subtopics / 5,491
cards, verified after the ingestion. Reads are fine; anything else needs the owner.

**Docker: build `api test seed worker` together.** Rebuilding one leaves the others stale,
which surfaces as a confusing `ModuleNotFoundError`. The `frog` image is separate and
built from `apps/frog/Dockerfile`.

## Phase 3 has two consumers, not one

This is the design constraint that is easy to miss, and it is new since the task doc was
written.

[Task 0040](../tasks/0040-open-licensed-image-catalog.md) (ADR-0095, photographs on cards)
assigns images by retrieving against image descriptions, and is **deliberately blocked on
this phase** rather than forking a second pgvector search. Its query is not prompt
assembly:

- top-1 above a **similarity floor**, not top-k packed to a budget
- filtered by "not already used by an active card in this topic"
- returning a row, not a block of prose

So **expose search as something callable in its own right**, with context packing built on
top of it — not as a step buried inside a `build_prompt_context()` function. If you only
build the packing path, task 0040 has to either reimplement search or contort itself
through a prompt-shaped API.

## The build

1. **Search.** Query → `embed_query` → pgvector cosine → top-k. Cross-topic by default;
   `topic_tags` and `kind` filters available and **not applied by default** (ADR-0088).
   Return chunk IDs and scores alongside text.
2. **Context assembly against a token budget.** Reuse `pack_by_tokens`' posture
   (ADR-0085, `generation/load_balancer.py`). ADR-0089's table is the constraint:
   `ministral-8b` drops below target throughput above ~18k tokens.
3. **Wire into the prompts — both drafters and thinkers.** ADR-0089 is explicit that the
   verifier grounding its factual check in the same corpus is *the point*, not a nicety.
4. **Record chunk IDs on the card.** ADR-0089's citability claim dead-ends without it.
5. **Inspect cross-topic retrieval scores.** ADR-0088 names this as a risk to *look at*,
   not assume away: does a PostgreSQL card get dragged off-subtopic by distributed-systems
   material? Report real numbers.
6. **The eval harness.** The thing that makes every later retrieval decision measurable
   rather than argued.

## Ask the owner — don't decide alone

- **What the eval harness scores against.** There is no labelled ground truth, and
  inventing one silently would make every later number meaningless. Options worth putting
  to them: hand-labelled query→chunk pairs for a small set, LLM-as-judge on relevance, or
  a proxy like "did the gate accept the card". This shapes the whole harness — ask first.
- **Whether `spoin_canon` is retrieved or pinned.** rag-design-space §3.9 argues canon
  should be a fixed prompt preamble rather than competing for retrieval slots, and says
  this would **amend ADR-0088**. Five canon documents currently sit in the corpus as
  ordinary retrievable rows.
- **The ASCII box rule enforcement mechanism** — still open from task 0038 Phase 6, five
  options tabled, needs its own ADR. Take the next free number; 0095 is used.
- **Anything that writes to, migrates, or repoints `spoin_db_2`.**

## Don't

- Start task 0040. It's designed and blocked on you; leave it.
- Add an ANN index before the eval harness runs (see above).
- Re-litigate cross-topic-by-default without reading ADR-0088's "Alternatives considered".

---

## The prompt

```
Read CLAUDE.md first, then docs/handoff/next-frog-phase-3-retrieval.md.
That doc is your brief; task 0038 Phase 3 is the work — retrieval over
the_spoin_universe, wired into the generator prompts, plus an eval harness.
Everything the repo can't tell you is in it, including three things that
will cost you time: the ingested corpus is already stale (112 docs on disk
vs 90 ingested — run `make corpus-ingest` first), retrieval must use
embed_query where ingestion used embed_passage (getting it backwards is a
silent recall loss), and there is deliberately no ANN index yet because an
approximate index would confound the eval numbers you're about to produce.

Read before writing code, in this order:
  docs/tasks/0038-frog-rag-and-hybrid-generation.md   the plan; Phase 2's
                                                      "what landed" first
  docs/adr/0089   the ADR you are implementing
  docs/adr/0088   cross-topic by default, and the risk to inspect
  docs/adr/0092   the asymmetric embedder
  docs/adr/0085   pack_by_tokens — reuse the posture

Phase 3 now has TWO consumers: task 0040 (ADR-0095, photographs on cards)
assigns images by retrieval and is blocked on you. Expose search as a
callable in its own right — top-k with scores and chunk IDs — with context
packing built on top, not buried inside a prompt-assembly function.

Don't start task 0040. Don't add an ANN index before the eval harness runs.
Ask me the questions listed under "Ask the owner" before implementing them —
especially what the eval harness scores against, since there is no ground
truth yet and inventing one quietly would make every later number meaningless.
```
