# ADR-0092: `Qwen3-Embedding-0.6B` at 1024 dimensions, with an asymmetric query/passage interface and a GPU/CPU device split

- **Status:** Accepted
- **Date:** 2026-09-05
- **Amends:** [ADR-0087](0087-frog-is-a-sibling-package.md) — replaces its "vectors stay
  384-dim, same model" commitment
- **Depends on:** [task 0039](../tasks/0039-embedder-never-reached-the-containers.md) —
  the reason a re-embed is happening at all

## Context

Task 0039 established that `SPOIN_EMBEDDER` never reached the containers, so every
vector in `spoin_db_2` is `HashEmbedder` output rather than a semantic embedding. The
repair requires re-embedding everything.

**That is what makes this decision cheap.** Re-embedding is the expensive part of any
embedding-model change, and we are paying it regardless. Switching models now costs
approximately nothing; switching later costs a second full backfill. The window is
open exactly once.

Three constraints shape the choice.

**1. The generation pipeline moves to the owner's machine.** Only the app-serving
backend deploys online; generation runs manually on a home PC with an RTX 5070 (12GB).
There is no cron refill and no intention to automate one soon. So bulk embedding has a
GPU available and is not latency-sensitive.

**2. Something still embeds on the live request path.** Topic requests move to a queued,
manual flow — beta users are told generation takes up to two days — which removes most
of it. But AskAI's off-topic gate ([ADR-0077](0077-askai-deterministic-single-call-retrieval.md))
embeds the user's question **every turn** and compares it against `topic.embedding`.
That cannot be queued.

**3. Dimension parity is not space parity.** Two different models that both emit 1024
floats produce vectors that are not comparable. A gate comparing a query vector from one
model against a topic vector from another is comparing noise, and nothing would raise.

## Decision

**The embedder is `Qwen/Qwen3-Embedding-0.6B`, 1024 dimensions, run on GPU for bulk work
and on CPU for the request path — the same weights on both devices.**

Verified before committing to it: the model exists and is widely used (~7M downloads),
and `onnx-community/Qwen3-Embedding-0.6B-ONNX` publishes fp16/int8/bnb4 exports, so the
CPU path is real rather than assumed.

0.6B is the deliberate size. A 4B model would score better and fits the 5070, but it
would be **GPU-only in practice** — and constraint 2 means something must run on a CPU
in the deployed backend. Choosing a model that cannot is choosing to break the gate or
to split the vector space. 0.6B is the largest size that keeps one model everywhere.

### The `Embedder` interface becomes asymmetric

Retrieval models are trained asymmetrically: a query and a passage are encoded
differently. Qwen3-Embedding expects queries wrapped as
`Instruct: <task>\nQuery: <text>` and passages left bare. Our previous model,
`bge-small-en-v1.5`, wanted its own query prefix — and **we were not applying it
anywhere**, which was a silent recall loss for as long as a real embedder was in use.

So `Embedder` grows `embed_query` and `embed_passage` rather than one `embed`. The
asymmetry is a property of the model, not of the caller, and an interface that hides it
makes forgetting it the default. `HashEmbedder` treats both identically, which is
correct — it has no notion of either.

### 1024 dimensions, and why the cost is irrelevant

5,491 cards × 1024 dims × 4 bytes ≈ 22MB. At this corpus size dimension is free, so
there is no reason to economise against quality. This supersedes ADR-0087's "vectors
stay 384-dim" — that commitment was made to keep corpus and card vectors comparable,
and comparability is preserved by both moving together, not by the number staying still.

### The two databases diverge temporarily, on purpose

`the_spoin_universe` moves to 1024 now. **`spoin_db_2` stays at 384 until the
regeneration wipe.** `spoin.domain.models.topic` reads `embedding_dim` at import time to
declare `Vector(...)`, so changing it before the columns change would make the ORM
disagree with the live schema and break every insert.

This is safe only because of a specific fact: nothing currently compares a card vector
to a chunk vector, and `spoin_db_2`'s vectors are hash output — meaningless in any
space. The divergence ends when the regeneration runs. It is a sequencing artefact with
a defined end, not a design.

### The CPU/ONNX path is deferred, not dropped

Bulk embedding on GPU is needed now; the CPU path is needed when the backend deploys,
which has not happened. Deferred to its own task rather than built speculatively — but
the interface is designed for it now, so adding it is an implementation, not a redesign.

**One thing to measure when it is built:** int8 ONNX quantization drifts from fp16 torch.
Typically cosine ≈ 0.99+, usually fine for a threshold gate — but "usually fine" is how
task 0039 happened. Measure the drift against the gate's actual threshold before
trusting it, and prefer the fp16 export if the drift is material.

## Consequences

**Easier.** Retrieval quality rises substantially from a genuinely weak baseline —
`bge-small-en-v1.5` was the weakest retrieval model on fastembed's list, and we were not
even applying its query prefix. The asymmetric interface makes that class of silent loss
structurally hard to repeat. GPU bulk embedding makes a full re-embed a minutes-long
operation, which makes future model changes cheap to evaluate rather than dreaded.

**Harder.** A new dependency (`sentence-transformers` + torch) that `fastembed` did not
need, and a device split to keep straight. Two vector spaces exist until the
regeneration — a real hazard, mitigated only by the fact that nothing compares them and
by this ADR saying so out loud. Every call site must now choose `embed_query` or
`embed_passage`, and choosing wrong is silent.

**Committed to.** One model on two devices. The moment a model is picked that cannot run
on a CPU, the AskAI gate needs a different design.

## Alternatives considered

**Stay on `bge-small-en-v1.5`, just fix the flag.** Smallest change. Rejected: it is the
weakest retrieval model available to us, and the re-embed that makes a switch free is
happening either way. Refusing the upgrade now means paying a second backfill later to
get it.

**`snowflake-arctic-embed-l` via fastembed.** No new dependency, ONNX-ready, CPU-safe
today. Genuinely the conservative choice and it would have worked. Rejected because the
GPU removes the constraint that made fastembed's catalogue the limit, and Qwen3 is the
stronger model.

**`Qwen3-Embedding-4B` (2560d).** Better retrieval, fits the 5070. Rejected on
constraint 2: GPU-only in practice, so the AskAI gate would need either a second model
(incomparable space) or a redesign. Not worth it for an increment.

**A different CPU model of the same dimension for the gate.** What "same dimensional CPU
embedder" could be read to mean. Rejected outright — dimension parity is not space
parity, and the failure is silent.

**Drop the embedding half of AskAI's gate** and rely on its `OFF_TOPIC` sentinel alone.
Would have freed the model size entirely. Not chosen; the gate keeps both mechanisms.

## Revisit when

- The backend actually deploys. That is when the ONNX CPU path gets built and its
  quantization drift measured against the gate threshold.
- The eval harness produces retrieval numbers. If 0.6B underperforms, the trade against
  4B can be re-argued with data rather than by reasoning about constraints.
- `spoin_db_2` is regenerated. That closes the temporary two-space divergence, and if it
  does not, this ADR is being violated.
