"""Local embeddings. Hard rule 5: these never run against a paid or quota'd API.

100% of scarce LLM quota is reserved for card generation, the only task that
genuinely needs a frontier model. If embeddings and generation shared a quota pool,
topic canonicalization would throttle exactly when signups spike — which is the
worst possible moment for it to stop working.

**These are pure classes. The factory that chooses between them lives in
`spoin.embeddings.get_embedder()`, not here** (ADR-0087). frog cannot read
`spoin.core.config`, and giving frog its own settings object would mean
`embedding_dim` is configured in two places — a divergence there produces vectors
that are silently not comparable and nothing raises. One config, one direction.

`normalize_topic_text` deliberately did *not* move here: it is topic-canonicalization
logic that happens to run before embedding, and task 0001's threshold calibration
depends on it. It stays in `spoin.embeddings`.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from abc import ABC, abstractmethod


class Embedder(ABC):
    """Asymmetric by design (ADR-0092).

    Retrieval models are trained so that a *query* and a *passage* are encoded
    differently — Qwen3-Embedding wraps a query in an instruction preamble and leaves
    passages bare; BGE wanted its own query prefix. Getting this wrong is a
    silent recall loss, not an error, and we shipped exactly that for as long as a real
    embedder was configured: nothing in the codebase ever applied BGE's query prefix.

    So the interface names the distinction instead of hiding it behind one `embed`.
    A caller has to decide which side it is on, which is the point.
    """

    @abstractmethod
    def embed_passage(self, texts: list[str]) -> list[list[float]]:
        """Embed corpus-side text: chunks, card bodies, topic descriptions.

        **Synchronous and CPU/GPU-bound.** Call `aembed_passage` from anything async.
        """

    @abstractmethod
    def embed_query(self, texts: list[str]) -> list[list[float]]:
        """Embed search-side text: a retrieval query, an AskAI turn.

        Implementations with no notion of the distinction return `embed_passage`.
        """

    def embed_one_passage(self, text: str) -> list[float]:
        return self.embed_passage([text])[0]

    def embed_one_query(self, text: str) -> list[float]:
        return self.embed_query([text])[0]

    async def aembed_passage(self, texts: list[str]) -> list[list[float]]:
        """`embed_passage`, off the event loop.

        Calling `embed` directly from a coroutine parks the whole event loop
        for the duration of the inference, which on the API means every
        concurrent request — including the ~50ms feed swipe the architecture is
        built around — waits behind it. That was reachable from a real request
        path: POST /topics -> match_and_create_topics -> embed.

        A thread is the right tool rather than a process pool: ONNX Runtime
        releases the GIL inside its native inference call, so the event loop
        genuinely runs during it.
        """

        return await asyncio.to_thread(self.embed_passage, texts)

    async def aembed_query(self, texts: list[str]) -> list[list[float]]:
        """`embed_query`, off the event loop, for the same reason as above.

        This is the one that sits on a live request path: AskAI's off-topic gate
        embeds every turn (ADR-0077).
        """

        return await asyncio.to_thread(self.embed_query, texts)


class HashEmbedder(Embedder):
    """A dependency-free deterministic stand-in.

    **Not semantically meaningful.** It exists so the stack boots and the tests run
    without pulling onnxruntime, not so anyone can reason about similarity. Any
    threshold measured against this is meaningless — see docs/tasks/0001, which is
    specifically about measuring thresholds against a real model.
    """

    def __init__(self, dim: int) -> None:
        self._dim = dim

    def embed_passage(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        """Identical to `embed_passage`, correctly: a token hash has no notion of a
        query/passage asymmetry to honour."""

        return self.embed_passage(texts)

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode()).digest()
            for offset in range(0, min(len(digest), 32), 4):
                index = int.from_bytes(digest[offset : offset + 2], "big") % self._dim
                vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


class FastEmbedEmbedder(Embedder):
    """BGE via `fastembed`: CPU-only, unlimited, free forever.

    Superseded as the default by `Qwen3Embedder` (ADR-0092) and kept because it needs
    no torch, which makes it the fallback if the deployed backend ever has to embed
    without one.

    **Applies no query prefix.** BGE v1.5 wants retrieval queries wrapped in
    ``Represent this sentence for searching relevant passages: ``; this class does not
    do it, which is the recall loss ADR-0092 describes. Left as-is rather than fixed,
    because the prefix differs per BGE variant and nothing should be using this by the
    time it matters. Do not adopt it for retrieval without adding the prefix.
    """

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed_passage(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, vector)) for vector in self._model.embed(texts)]

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        return self.embed_passage(texts)


class Qwen3Embedder(Embedder):
    """`Qwen/Qwen3-Embedding-0.6B` via sentence-transformers (ADR-0092).

    1024 dimensions, normalized. Runs on CUDA for bulk work — a full corpus re-embed is
    minutes on the RTX 5070 — and on CPU for the request path, which is why 0.6B was
    chosen over the stronger 4B: one model on both devices keeps the vector space
    single, and dimension parity between two *different* models would not.

    Install with the `embeddings-gpu` extra. Kept optional so the default image and the
    test suite stay free of torch.
    """

    #: Qwen3-Embedding is instruction-tuned on the query side. sentence-transformers
    #: ships the model's own `query` prompt, so we ask for it by name rather than
    #: hand-rolling the instruction wrapper here and drifting from whatever the model
    #: card says.
    _QUERY_PROMPT = "query"

    def __init__(self, model_name: str, *, device: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        #: `None` lets sentence-transformers pick CUDA when it is there and fall back to
        #: CPU when it is not, which is exactly the GPU-here / CPU-deployed split.
        self._model = SentenceTransformer(model_name, device=device)

    def embed_passage(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, prompt_name=None)

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, prompt_name=self._QUERY_PROMPT)

    def _encode(self, texts: list[str], *, prompt_name: str | None) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            prompt_name=prompt_name,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return [[float(value) for value in vector] for vector in vectors]
