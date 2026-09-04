# RAG for Spoin: how production systems work, and what would make ours exceptional

> **Status:** design research, written 2026-09-05 to inform task 0038's Phase 3. Not a
> decision — the decisions it argues for should become ADRs when taken.
> **Scope:** how production-grade retrieval systems are actually built, then what
> Spoin's unusual constraints let us do that a normal RAG system cannot.
>
> Where this doc gives a number from the literature it says so, and every one of them
> should be re-measured locally before it is built on. That is the rule the
> [gemini-saga](../gemini-saga/README.md) cost four weeks to learn.

---

## 0. A finding that comes before every recommendation below

**The containers are running `HashEmbedder`, not `bge-small-en-v1.5`.**

`.env` sets `SPOIN_EMBEDDER=fastembed`, but `docker-compose.yml` never passes
`SPOIN_EMBEDDER` into the `api`, `worker` or `seed` services — and compose only injects
variables it explicitly names, as its own comments say. The setting therefore falls
back to its default, `hash`. Verified directly in the container:

```
embedder setting : hash
model            : BAAI/bge-small-en-v1.5     ← set, and unused
actual class     : HashEmbedder
```

`HashEmbedder`'s own docstring says it plainly: *"Not semantically meaningful. It
exists so the stack boots and the tests run without pulling onnxruntime... Any
threshold measured against this is meaningless."*

**What this means in production, right now:**

| | |
|---|---|
| `card.content_embedding` | **5,491 rows**, all hash vectors |
| `topic.embedding` | 11 of 41 topics, all hash vectors |

Everything sitting on those vectors is running on a token-frequency hash rather than
on meaning: topic matching and the alias cache, the AskAI off-topic embedding gate
(ADR-0077), the embedding-derived accent colour (ADR-0075), near-duplicate card
detection, and `ascii_library.py`'s cosine search.

**This blocks the entire RAG plan**, because retrieval over `the_spoin_universe` is
supposed to share a vector space with `card.content_embedding` (ADR-0087) — and half
of that space is currently not a semantic space at all.

**I have not fixed it**, because the fix is not one line. Turning the flag on makes
*new* vectors semantic while 5,491 existing ones stay hash, and a column holding both
is worse than a column holding either: comparisons across the two kinds are noise.
The real fix is `SPOIN_EMBEDDER` reaching the containers **plus a backfill re-embed of
every existing row**, which is a bulk write to `spoin_db_2` and needs your explicit
approval (CLAUDE.md). It also wants an `embedding_model` stamp per row so a future
model change can tell which vectors are comparable.

Everything below assumes this is fixed first. Tuning retrieval on a hash embedder
would produce numbers that mean nothing.

---

## 1. How a production RAG system is actually built

Nine stages. Most systems that disappoint are weak in stages 1, 5 and 8, and
over-invested in stage 3.

### 1.1 Ingestion and chunking — the most underrated stage

Chunking decides the ceiling on everything downstream: a fact split across two chunks
is a fact retrieval can only find half of.

- **Structure-aware beats fixed-size.** Split on real document structure — headings,
  sections — not on a character count. Fixed-size splitting cuts sentences and
  separates a claim from its qualifier.
- **Overlap, or a sentence window.** 10–20% overlap, or index single sentences and
  return a window of neighbours around a hit.
- **Small-to-big (parent-document retrieval).** Embed a small, precise unit for
  *matching*; return a larger parent for *reading*. Precision at match time, context at
  generation time — you rarely want the same granularity for both.
- **Contextual chunk augmentation.** Before embedding, prepend a one- or two-sentence
  blurb situating the chunk in its document ("This section of the PostgreSQL MVCC
  documentation explains what REPEATABLE READ guarantees..."). Anthropic's published
  work on this reports a large reduction in retrieval-failure rate when combined with
  BM25 and reranking. It is the highest-value cheap trick in modern RAG, and it exists
  because a chunk ripped out of a document loses the referents that made it findable.
- **Attach metadata at chunk level** for filtering later.

### 1.2 Embedding

- **Bi-encoder, and usually asymmetric.** Query and passage are encoded separately and
  compared by cosine. Most retrieval models expect an *instruction prefix on the query
  only* — E5 wants `query:` / `passage:`; **BGE v1.5 wants queries prefixed with
  `Represent this sentence for searching relevant passages:` and passages left bare.**
  Omitting it is a silent recall loss, not an error.
- **Normalize**, so cosine and inner product coincide and the index can use the cheaper
  operator.
- **Dimension is a storage/quality trade.** Matryoshka-trained models let you truncate
  a 1024-d vector to 256-d with graceful degradation.
- **Quantization** for large corpora: pgvector's `halfvec` (fp16) halves storage;
  binary quantization plus a full-precision rerank pass is the standard billion-scale
  trick. Irrelevant below a few million chunks.
- **Fine-tuning the embedder** on domain pairs is real but is the *last* lever, not the
  first — it needs labelled data you will not have until you have an eval harness.

### 1.3 Indexing

- **pgvector offers HNSW and IVFFlat.** HNSW gives better recall-per-latency, costs
  more memory and a slower build; IVFFlat is cheaper to build but needs its `lists`
  tuned to the row count and its `probes` tuned at query time.
- **Both are approximations.** They trade recall for speed. `ef_search` / `probes` is
  the knob, and the default is usually tuned for latency, not for recall.
- **Filters interact badly with ANN.** A pre-filter that removes most rows makes the
  graph traversal degenerate; a post-filter can silently return fewer than `k`. This is
  a classic production footgun.
- **Below roughly 100k chunks, the right index is often no index.** An exact sequential
  scan gives **100% recall** and completes in milliseconds. You accept approximation
  only when exactness stops being affordable.

### 1.4 Retrieval

- **Dense** finds paraphrase and synonymy. It is *bad* at rare exact tokens —
  identifiers, version numbers, flags, error codes — because they are barely
  represented in the embedding.
- **Sparse / lexical (BM25)** is the opposite: excellent at exact rare terms, blind to
  synonymy. In Postgres this is `tsvector` + GIN with `ts_rank_cd`; heavier BM25 is
  available via extensions.
- **Hybrid is the production default**, fused with **Reciprocal Rank Fusion**:
  `score(d) = Σ_i 1 / (k + rank_i(d))`, conventionally `k ≈ 60`. RRF works on *ranks*,
  so it needs no score normalization between two systems whose scores are not
  comparable — which is why it beat weighted-score blending in practice.
- **Query transformation** when the query is a user's natural language: multi-query
  (generate several phrasings, union the results), HyDE (embed a *hypothetical answer*
  rather than the question, because answers live nearer answers in embedding space),
  and decomposition for multi-hop questions.
- **Metadata filtering**, pre- or post-, with the ANN caveat above.

### 1.5 Reranking — usually the single biggest quality jump

A **cross-encoder** encodes query and passage *together* and scores the pair. It is far
more accurate than any bi-encoder because it can attend across both — and far too slow
to run over a corpus, because it is one model call per candidate. So the shape is
always: retrieve 50–100 cheaply, rerank them, keep the top 3–8.

- Open models: `bge-reranker-base` / `-large`, `mxbai-rerank`. Base-size runs on CPU.
- **Late interaction (ColBERT)** sits in between: per-token vectors and a MaxSim
  operator, much of the cross-encoder's accuracy at lower query cost, but storage
  balloons because you store a vector per token.

If a RAG system is going to get exactly one upgrade, it should usually be this one.

### 1.6 Context assembly

- **Deduplicate** near-identical passages; retrieval loves returning three copies of
  the same paragraph.
- **Order deliberately.** Attention degrades in the middle of a long context
  ("lost in the middle"), so the strongest evidence goes first and last, not buried.
- **Budget tokens** with spillover rather than truncating mid-passage.
- **Carry IDs** so the model can cite and so provenance is recordable.
- **Compress** when the budget bites — extractive sentence selection is safer than
  abstractive summarisation, which can introduce the error you were trying to avoid.

### 1.7 Generation

Ask for per-claim citations. Instruct explicitly that unsupported claims must be
declined rather than filled in — this matters far more for a *verifier* than for a
chatbot. Use structured output so the answer is parseable rather than scraped.

### 1.8 Evaluation — what actually separates production from demo

Without this you are not tuning, you are guessing.

- **Retrieval metrics** against a golden set of (query → the chunks that *should* come
  back): recall@k, MRR, nDCG. Recall@k is the ceiling — if the right chunk is not in
  the candidate set, no reranker and no model can recover it.
- **End-to-end metrics**: groundedness/faithfulness (is every claim in the output
  supported by the retrieved context?), context precision (how much of what you sent
  was actually used), answer relevance.
- **A fixed set and a number that moves.** Fifty hand-labelled examples beat a
  thousand-example set you never look at.

### 1.9 Operations

Stamp every vector with the embedding model that produced it — without it you cannot
tell which vectors are comparable after a model change, and a model change is
inevitable. Plan the reindex. Cache aggressively wherever the query repeats.

---

## 2. Spoin is not a chat RAG — eight asymmetries, and what each unlocks

This is where an exceptional system comes from. Almost every default in §1 is tuned for
a situation we are not in.

**1. Retrieval is offline and batched, not in a user's request.** It happens in the
generation worker. There is no p99 to protect — the feed read path never touches any of
this (hard rule 1). *Unlocks:* expensive retrieval is affordable. Cross-encoder
reranking, multi-query, iterative retrieval, per-claim verification — all of the things
a chat RAG cannot afford are simply fine here.

**2. The query is machine-generated, structured, and known in advance.** It is not
"what does the user mean?" — it is a topic name, a subtopic title, a subtopic
description and a difficulty tier, produced by the curriculum pass *before* generation
starts. *Unlocks:* the hardest problem in RAG (query understanding) largely disappears,
and retrieval becomes **precomputable**.

**3. The corpus is small, curated, and slow-changing.** Thousands of hand-authored
documents, not millions of scraped pages. *Unlocks:* exact search with 100% recall; no
ANN tuning, no sharding, no approximation, no filter-interaction footgun. Delete a
whole category of engineering.

**4. We own the authoring.** Almost no RAG system does. *Unlocks:* work moves from
retrieval time to authoring time, which is the cheapest possible place to put it — and
the authoring procedure already exists to carry the instructions.

**5. Two consumers with opposite needs.** The writer wants *breadth* — enough material
to draft N cards on a subtopic. The verifier wants *precision* — the one passage that
settles this one claim. Same corpus, genuinely different retrieval.

**6. Token budget converts directly into throughput.** ADR-0089's table: sustainable
rate is `min(TPM / prompt_tokens, RPM)`. On `ministral-8b`, 12k tokens sustains ~52
calls/min and 30k sustains ~21. **Retrieval precision is not a quality metric here; it
is a throughput metric.** A reranker that lets you send 6k instead of 20k tokens does
not just improve cards — it roughly triples how many you can make per hour.

**7. The drafting model is small.** 3B–8B models suffer worse from long, noisy context
than frontier models do. *Implication:* four excellent chunks beat twenty mediocre
ones. Precision, throughput and quality all point the same direction — which is rare,
and worth exploiting hard.

**8. Cards are generated once and are permanent.** A card built on a wrong chunk stays
wrong for every reader forever. *Unlocks:* provenance is not bookkeeping, it is a
**retraction mechanism** — see §3.12.

---

## 3. What to build, ranked by leverage

Roughly ordered by (impact × confidence) ÷ effort.

### 3.1 Fix the embedder, and backfill — *blocking*

§0. Nothing below is measurable until vectors mean something. Needs your approval for
the backfill because it is a bulk write to `spoin_db_2`.

### 3.2 Build the eval harness before tuning anything

Hand-label a golden set: for 30–50 real subtopics, which chunks *should* be retrieved.
Then every change below is a number that moves rather than an opinion. This is the same
discipline the mistral-saga enforced on providers, applied to retrieval, and it is the
single most valuable thing to build first.

Two levels worth measuring: **recall@50** (is the right material in the candidate set
at all — the ceiling) and **precision@5 after reranking** (is it at the top).

### 3.3 Hybrid dense + lexical, fused with RRF

Non-negotiable for a technical corpus. Card correctness lives in exactly the tokens
dense retrieval is worst at: `REPEATABLE READ`, `O_DIRECT`, `SIGKILL`, version numbers,
flag names. Postgres gives us `tsvector` + GIN in the same database — no new service, no
new dependency, and `the_spoin_universe` already has the `chunk.text` column to index.

### 3.4 A local cross-encoder reranker

Retrieve ~50 hybrid candidates, rerank with `bge-reranker-base`, keep 4–6. Runs on CPU,
free forever, no quota — it satisfies hard rule 5 the same way the embedder does, and
frog is already the package that owns local models.

Combined with §2's asymmetry 6, this is the highest-value item in the document: it is
simultaneously the biggest quality gain *and* a large throughput gain, because it lets
the context shrink.

### 3.5 The query instruction prefix — free recall

`bge-small-en-v1.5` expects retrieval queries to be prefixed and passages not to be.
Nothing in the codebase does this today. It costs one line and an `Embedder` API that
distinguishes `embed_query` from `embed_passage` — which frog should have anyway,
because the asymmetry is a property of the model, not of the caller.

### 3.6 No ANN index, deliberately

At our corpus size, exact search is milliseconds and gives perfect recall. Write it
down as a decision with a revisit threshold (say, 250k chunks) rather than reaching for
HNSW because it is what one does. Every filter-interaction bug in §1.3 is a bug we
simply never have.

### 3.7 Retrieve once per subtopic, not once per call

The query is known before generation and does not change within a subtopic (asymmetry
2). So retrieve **once**, assemble the context **once**, and reuse it across every card
draft in that subtopic and across both providers. Key the cache by
`subtopic_group_id` + corpus version.

This turns retrieval from a per-call cost into a per-subtopic cost — roughly a 10–25×
reduction in retrieval work, and it makes the expensive reranker in §3.4 essentially
free in aggregate.

### 3.8 Contextual chunk headers, generated at ingestion

§1.1's biggest cheap win. Because ingestion is offline and one-time, we can afford to
produce a situating sentence per chunk and embed it with the chunk. Two sources for it,
in increasing cost: derive it structurally from the document title and heading path
(free, deterministic, most of the benefit), or generate it once per chunk with a cheap
model. Start with the structural version and measure whether the generated one earns
its cost.

### 3.9 Pin canon; do not retrieve it

`spoin_canon` — how Spoin writes, the dual-title rule, the ASCII box rule, silliness in
the hook layer — is small and relevant to **every** generation call regardless of
subject. Making it compete for retrieval slots against topic material is a mistake in
both directions: it displaces facts the model needs, and it sometimes fails to be
retrieved at all for a call that needed it.

Pin it into the prompt as a fixed preamble and give the retrieval budget entirely to
`topic_source`. ADR-0088 currently implies canon is retrieved by relevance like
anything else; this would amend that.

### 3.10 The verifier retrieves per claim, not per subtopic

The sharpest idea in this document, and the one most specific to Spoin.

The writer's retrieval is subtopic-shaped. The verifier's should not be. Decompose the
drafted card's `body` into atomic claims, retrieve for **each claim**, and check each
against its own evidence. That converts "does this card look right?" — which is what a
verifier with subtopic-level context is really answering — into "is this specific
sentence supported by this specific passage?"

That is what makes *quiz-gated mastery of true things* an enforced property rather than
an aspiration. It is expensive, and it is on the thinking ladder where expense is the
point.

### 3.11 Difficulty-aware retrieval

A beginner card and an advanced card on the same subtopic want different passages.
Nobody else's RAG has this signal; ours does, on every query, from `subtopic.difficulty`.
Tag chunks with a complexity signal at authoring or ingestion time and boost accordingly.
Cheap to add, and it directly serves the tiering the product is built on.

### 3.12 Provenance as a retraction pipeline

ADR-0089 already records the chunk IDs that grounded a card. Take it further: record the
retrieval scores and the corpus version too. Then when a chunk is found wrong — and one
will be — you can answer *"which cards did this ground?"* with a query, and regenerate
exactly those. Without it, a single corrected passage means either re-generating
everything or living with known-bad cards.

Given cards are permanent and served to everyone (asymmetry 8), this is closer to a
safety requirement than a feature.

### 3.13 Make the authoring loop's coverage check a retrieval query

The authoring procedure's Phase B asks "what does the corpus already cover?" That is a
retrieval problem, answerable with the same index: embed the proposed subject, find the
nearest existing chunks, report density and nearest neighbours. It turns the
compositional-reuse goal from an instruction Antigravity is asked to honour into a
measurement it is handed.

### 3.14 Revisit the embedding model — but only after §3.2

`bge-small-en-v1.5` is a small, older model. Embedding is local and free, the corpus is
small, and inference cost barely matters offline — so a stronger embedder is affordable.
The cost is a re-embed of both databases (ADR-0087 warns about exactly this) and it is
only justifiable with the eval harness in place to show the gain. Do not lead with it.

---

## 4. What not to build

- **A dedicated vector database.** pgvector in the same instance is correct at this
  scale and keeps the corpus in one transactional store. A separate service adds an
  operational surface and a consistency problem for no measurable gain.
- **GraphRAG / knowledge graphs.** Real value for multi-hop questions over entity-dense
  corpora. Our queries are single-subject and the curriculum already supplies the
  structure a graph would reconstruct.
- **Agentic / iterative retrieval loops.** Each iteration is a model call, and calls are
  the scarce resource. Revisit only if measurement shows single-shot retrieval missing.
- **A fine-tuned embedder.** Needs labelled data that will not exist until §3.2 has been
  running for a while.
- **ColBERT / late interaction.** Storage cost is large and a cross-encoder over 50
  candidates gets most of the benefit in a setting with no latency budget.
- **Semantic caching of generations.** Solves a problem interactive systems have.

---

## 5. A staged plan

| Stage | What | Gate |
|---|---|---|
| **0** | Fix the embedder + backfill `spoin_db_2` | **Your approval** — bulk write |
| **1** | Eval harness: golden set, recall@50, precision@5 | Nothing after this is guesswork |
| **2** | Exact search, query prefix, hybrid + RRF | Measure each against stage 1 |
| **3** | Cross-encoder rerank | Expect the largest single jump |
| **4** | Per-subtopic retrieval cache, contextual headers, pinned canon | Throughput + precision |
| **5** | Per-claim verifier retrieval, difficulty-aware boost | Quality ceiling |
| **6** | Provenance → retraction; coverage query for authoring | Operability |

Stages 2–4 are task 0038's Phase 3. Stage 5 touches ADR-0030's gate and would amend it.

## 6. What I would verify before building

- Every number in §1 is from published work and my own knowledge through mid-2026 — the
  reranker and contextual-retrieval gains especially. Re-measure locally.
- Current best small open reranker and embedder move quickly; worth a fresh check before
  committing to specific model names.
- pgvector's exact-search crossover point should be measured on our actual row counts,
  not assumed from the ~100k figure quoted above.
