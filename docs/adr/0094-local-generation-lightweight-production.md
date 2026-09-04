# ADR-0094: Generation and every heavy workload run locally; the production server hosts only the app backend

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** project owner
- **Formalises:** the deployment split that [ADR-0092](0092-qwen3-embedder-and-the-device-split.md)
  and task 0038's Phase 2 already assume without anything deciding it

## Context

This split has been operating since early September 2026 and shaping real
decisions, but it was only ever written down as *context* inside an ADR about an
embedding model. ADR-0092 opens with "the generation pipeline moves to the owner's
machine... only the app-serving backend deploys online" and reasons from it; the
`frog` compose service exists because of it; the deferred ONNX CPU path is deferred
because of it. Three consequences, no decision.

That is the shape CLAUDE.md warns about: a rule stated only in passing is a rule
the next session re-derives or quietly violates. The specific violation this
invites is cheap and permanent — adding a dependency to `apps/api` because
generation needs it, and discovering later that the deployed image carries several
gigabytes it never executes.

The two workloads have genuinely opposite profiles:

| | Generation / ingestion | Serving |
|---|---|---|
| Shape | bursty, batch, manual | constant, per-request |
| Bound by | GPU and provider quota | latency |
| Latency budget | minutes to days | ~50ms for a feed swipe |
| Frequency | when the owner runs it | every user interaction |
| Needs | torch, CUDA, LLM clients, the corpus | Postgres, FastAPI |

Sizing one machine to satisfy both means paying continuously for GPU-class
capacity in order to serve a feed that needs almost none of it. And the hardware
for the first column is already owned and otherwise idle: an RTX 5070.

## Decision

**There are exactly two environments.**

**Local machine (RTX 5070) + the GitHub remote.** Card generation and the whole
LLM pipeline, bulk embedding, corpus ingestion into `the_spoin_universe`, the eval
harness, benchmarks and probes. Run **manually** — there is no cron refill and no
plan to automate one for v1. Beta users are told a topic request is generated
manually and can take up to two days.

**The production server.** Only what the app needs to serve a request: the feed
read path, engagement, auth, AskAI. **As lightweight as possible.** If the
deployed backend does not execute it on a request path, it does not belong in the
deployed image.

### The operational rule this creates

**Before adding a dependency to `apps/api`, ask whether the production server
needs it.** If only generation or ingestion does, it belongs in a separate image.

This is already precedent rather than aspiration: the `frog` compose service
carries torch and the CUDA runtime — roughly 3GB — in its own image built from
`apps/frog/Dockerfile`, specifically so it stays out of the image that `api`,
`worker`, `seed` and `test` all build from. Folding it in would have put 3GB into
four images to serve one command.

### Why this constrains the embedder, permanently

The split is not clean, and the place it leaks is the reason ADR-0092 chose the
model it did. **Something still embeds on the live request path:** AskAI's
off-topic gate ([ADR-0077](0077-askai-deterministic-single-call-retrieval.md))
embeds the user's question every turn and compares it against `topic.embedding`.
That cannot be queued or moved to the home PC.

So the embedding model must run on a CPU in the deployed backend, which is why
`Qwen3-Embedding-0.6B` was chosen over the stronger 4B that fits the 5070 just
fine. 0.6B is the largest size that keeps **one** model on both devices, and one
model is not negotiable: two models emitting the same number of dimensions do not
share a vector space, so a gate comparing a query vector from one against a topic
vector from the other compares noise, and nothing raises.

**Any future model choice inherits this constraint.** A model that cannot run on
a CPU is a decision to break the gate or to split the vector space.

## Consequences

**Easier.** The production server is small, cheap and boring, which is what a
serving tier should be. Generation gets a GPU for free and is not competing with
user traffic for anything. A full corpus re-embed is a minutes-long local
operation rather than a cloud cost, which makes embedding-model changes cheap to
evaluate instead of dreaded.

**Harder.** Generation does not happen unless someone runs it, and "up to two
days" is a real product promise made to beta users rather than a technical
detail. Two environments must be kept in step by hand — the `frog` image and the
`api` image install from the same `apps/frog/pyproject.toml` but with different
extras, and nothing enforces that they agree. The CPU/ONNX embedding path is owed
and unbuilt.

**Committed to.** Manual generation for v1. One embedding model that must run on
a CPU, indefinitely. A deployed image that deliberately cannot generate anything.

## Alternatives considered

**One environment that does both.** Simplest to reason about and to deploy.
Rejected on cost and shape: a GPU-class instance running continuously to serve a
read path that needs ~50ms of Postgres, when the GPU is already owned and idle at
home. It also couples generation load to user-facing latency, which the read/write
split in `docs/architecture/overview.md` exists to prevent.

**Generation in the cloud, on rented GPU or a provider API.** What the project did
before, and the [gemini-saga](../gemini-saga/README.md) is four weeks of what it
cost. Not rejected forever — this ADR is about v1 economics, and a provider that
behaves would change the arithmetic. Rejected for now because the local GPU makes
it free.

**Automate generation on a cron from the home PC.** Keeps the split, removes the
manual step. Rejected as premature: the pipeline is being actively rewritten
(task 0038's hybrid generator), and automating a thing that is changing weekly
means debugging the automation instead of the pipeline. Revisit when Phase 7 has
run end-to-end.

**Deploy the full image and simply never call the generation endpoints.** No
second image, no extras to keep in step. Rejected: an unused 3GB of torch is still
3GB in every pull, every restart and every image scan, and "we just don't call it"
is not a boundary — it is a habit.

## Revisit when

- **The backend actually deploys.** That is when the ONNX CPU path gets built and
  its int8 quantization drift measured against the gate's real threshold.
- **Generation stops being manual.** A cron or a queue on the home PC is a real
  change to the promise made to users, and to what "local" means operationally.
- **A second person needs to run generation.** "The owner's machine" stops being a
  location and becomes a role, and the corpus/model caches need somewhere shared.
- **AskAI's embedding gate is removed or redesigned.** It is the only thing forcing
  a CPU-capable embedder; without it the model size reopens.
