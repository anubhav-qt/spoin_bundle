# ADR-0087: `frog` is a sibling Python package that owns the embedder; `spoin` depends on it, never the reverse

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** project owner, implementing session
- **Amended by:** [ADR-0092](0092-qwen3-embedder-and-the-device-split.md) — the
  embedder becomes `Qwen3-Embedding-0.6B` at 1024 dimensions, and the `Embedder`
  interface becomes asymmetric. This ADR's "vectors stay 384-dim" no longer holds.
- **Amended by:** [ADR-0093](0093-normalize-topic-text-moves-into-frog.md) —
  `normalize_topic_text` moves into `frog` after all. The "stays in `spoin`" clause below
  no longer holds; it was written before ADR-0088 gave the function a caller on the far
  side of a boundary frog cannot cross.

## Context

[Task 0038](../tasks/0038-frog-rag-and-hybrid-generation.md) commits us to
retrieval-grounded generation. Three facts force the shape of the thing that does
the retrieving.

**We are about to draft on small models.** The [mistral-saga](../mistral-saga/README.md)
established that this account's only usable Mistral models are `ministral-3b/8b/14b`
and `codestral` — no reasoning-capable model at any tier. A 3B model's parametric
recall is not something the product's "quiz-gated mastery of true things" claim can
rest on. The facts have to come from a corpus.

**Retrieval happens several times per generation call.** The planner retrieves, the
writer retrieves, the verification pass retrieves against the same material. An HTTP
hop per retrieval buys nothing and adds both latency and a failure mode to a path
that is already fighting for calls/minute.

**We already have an embedder, and it is in the wrong place for this.**
`spoin.embeddings` provides `get_embedder()` — local, never quota'd (hard rule 5),
`BAAI/bge-small-en-v1.5` at 384 dimensions, with a deterministic `HashEmbedder`
stand-in so the stack boots without `onnxruntime`. A retrieval package needs that
embedder. If the retrieval package lives outside `spoin` and imports it from
`spoin`, the dependency runs in both directions and the boundary is decorative.

## Decision

**`frog` is a separate importable Python package at `apps/frog/`, with its own
`pyproject.toml`. It is a library, not a service. `apps/api` takes a path dependency
on it. `frog` must not import `spoin`.**

`apps/helpers/` is the precedent for a non-service sibling, though it has no
`pyproject.toml` and is not importable; frog needs both.

### frog owns the embedder classes; `spoin` keeps the factory

`Embedder`, `HashEmbedder` and `FastEmbedEmbedder` move into `frog.embeddings` as
**pure classes taking explicit parameters**. `spoin.embeddings.get_embedder()`
stays where it is, keeps reading `spoin.core.config`, and constructs a frog class.

This split is deliberate and is the only part of the move that is not mechanical.
The alternative — moving the factory too — requires frog to grow its own settings
object reading the same environment variables. `embedding_dim` configured in two
places is a silent-failure generator: a divergence produces vectors that are not
comparable, and nothing raises. Corpus chunk vectors and existing
`card.content_embedding` vectors must remain in the same space, so **384 dimensions
and the same model are load-bearing, not a default**.

~~`normalize_topic_text` stays in `spoin`. It is topic-canonicalization logic that
happens to be applied before embedding, not embedding infrastructure — task 0001's
threshold calibration depends on it not drifting, and that concern is spoin's.~~

**Superseded by [ADR-0093](0093-normalize-topic-text-moves-into-frog.md)** (2026-09-05).
The clause above held only until something needed to call the function from frog's side.
ADR-0088's ingester does, and ADR-0088's own reasoning — *one* normalizer, so corpus tags
and canonical topic names cannot become two vocabularies — made duplicating it the wrong
answer. Unlike `get_embedder()`, it reads no settings, so there was nothing for a second
home to diverge about except the code.

### All 23 import sites are rewritten, no re-export shim

`spoin.embeddings` does not re-export frog's classes. Every call site that wants an
`Embedder` type imports it from `frog.embeddings`. A shim would make the boundary
invisible at exactly the places a reader needs to see it, and would accrete code —
CLAUDE.md's "a rule stated only in a doc is a wish".

### The boundary is enforced twice

Per CLAUDE.md's rule that a hard architectural rule gets enforced twice, never
documented once — the same wiring ADR-0002 uses to confine LangChain:

1. A `ruff` `banned-api` entry in `apps/frog/pyproject.toml` on `spoin`.
2. An AST-level check in `apps/api/tests/test_architecture.py` that walks
   `apps/frog`'s source and fails on any `spoin` import. It lives beside the
   existing boundary checks because that file is where someone auditing
   architectural rules already looks.

`make check` runs `ruff` and `mypy --strict` over `apps/frog` as well as `apps/api`.
frog gets its own `tests/` directory for unit tests of its own machinery
(the embedder, chunking, retrieval), run in the same `make test` pass.

### The Docker build context moves to the repository root

`apps/api/Dockerfile` currently builds with context `./apps/api` and `COPY src ./src`.
That context cannot reach `../frog`. The `api`, `seed`, `worker` and `test` services
move to `context: .` with `dockerfile: apps/api/Dockerfile`, copying both
`apps/frog` and `apps/api/src`.

This is the real cost of the sibling-package choice and task 0038 flagged it as such.
We are paying it rather than layering badly.

## Consequences

**Easier.** The dependency direction is a fact of the filesystem, not a convention.
frog can be tested, type-checked and reasoned about without the API. A future
consumer — `content/ascii_library.py`'s hand-rolled cosine search is the obvious
first candidate — sits on frog without importing anything from the generation stack.
`the_spoin_universe` gets a natural owner ([ADR-0088](0088-the-spoin-universe.md)).

**Harder.** Four compose services change build context, which is a rebuild for
everyone and a class of path bug that only shows up in the image, not locally. A
change touching both packages is now two `pyproject.toml` files and two lint
configurations. The embedder split means a reader has to know that the classes and
the factory live in different packages — mitigated by a docstring in each pointing
at the other and at this ADR.

**Committed to.** 384-dimension vectors from `BAAI/bge-small-en-v1.5`, in both
databases, indefinitely. Changing the embedding model is now a two-database
re-embedding, not a config flip.

## Alternatives considered

**`apps/api/src/spoin/frog/` — a package inside `spoin`.** Task 0038 names this as
the fallback if packaging proves disproportionate. It needs no Docker changes at all.
It loses the thing the whole decision is for: inside `spoin`, frog *can* import
`spoin`, and the only thing stopping it is a lint rule on a package that has every
reason to reach for `spoin.core.config`. The boundary would be a wish. Kept as an
explicit fallback: if the build-context change proves worse than budgeted, this is
where we retreat to, and this ADR gets superseded rather than quietly ignored.

**frog as an HTTP service.** Rejected on the retrieval-frequency argument above.
Several retrievals per generation call, each a network hop with its own timeout and
its own failure mode, on a path whose entire history is a fight for throughput.

**Leave the embedder in `spoin`, have frog import it.** This is the inversion the
decision exists to prevent. `api → frog` and `frog → api` simultaneously means
neither package can be built, tested or reasoned about alone.

**Move the factory into frog too.** Rejected on the `embedding_dim`-drift argument:
two settings objects reading the same environment variable is a silent
incomparable-vectors bug waiting for someone to change one of them.

## Revisit when

- The Docker/CI cost of the sibling package exceeds what was budgeted — retreat to
  `spoin.frog`, supersede this.
- A second consumer of frog appears that is not in this repository. That is the
  signal that "library, not service" has stopped being right, and the retrieval-
  frequency argument should be re-measured rather than re-assumed.
- The embedding model changes. That is a two-database migration and deserves its own
  ADR.
