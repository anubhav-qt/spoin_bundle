"""Local embeddings. Hard rule 5: these never run against a paid or quota'd API.

100% of scarce LLM quota is reserved for card generation, the only task that
genuinely needs a frontier model. If embeddings and generation shared a quota pool,
topic canonicalization would throttle exactly when signups spike — which is the
worst possible moment for it to stop working.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from abc import ABC, abstractmethod
from functools import lru_cache

from spoin.core.config import get_settings


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Takes a collection, like every other batch interface here.

        **Synchronous and CPU-bound.** `FastEmbedEmbedder` runs ONNX inference
        here. Call `aembed` from anything async — see below.
        """

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        """`embed`, off the event loop.

        Calling `embed` directly from a coroutine parks the whole event loop
        for the duration of the inference, which on the API means every
        concurrent request — including the ~50ms feed swipe the architecture is
        built around — waits behind it. That was reachable from a real request
        path: POST /topics -> match_and_create_topics -> embed.

        A thread is the right tool rather than a process pool: ONNX Runtime
        releases the GIL inside its native inference call, so the event loop
        genuinely runs during it.
        """

        return await asyncio.to_thread(self.embed, texts)


class HashEmbedder(Embedder):
    """A dependency-free deterministic stand-in.

    **Not semantically meaningful.** It exists so the stack boots and the tests run
    without pulling onnxruntime, not so anyone can reason about similarity. Any
    threshold measured against this is meaningless — see docs/tasks/0001, which is
    specifically about measuring thresholds against a real model.
    """

    def __init__(self, dim: int) -> None:
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

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
    """BGE-small via `fastembed`: CPU-only, unlimited, free forever.

    Install with the `embeddings` extra. Kept optional so the default image stays
    small; anything where similarity has to actually mean something needs this.
    """

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, vector)) for vector in self._model.embed(texts)]


def normalize_topic_text(raw: str) -> str:
    """The normalization applied before embedding a topic string.

    **This must stay identical between calibration and production.** Task 0001 is
    required to write down exactly what it did; if the two ever diverge, the alias
    cache silently misses and every measured threshold stops meaning what it meant.
    """

    lowered = raw.strip().lower()
    kept = [char if char.isalnum() or char.isspace() else " " for char in lowered]
    return " ".join("".join(kept).split())


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedder == "fastembed":
        return FastEmbedEmbedder(settings.embedding_model)
    return HashEmbedder(settings.embedding_dim)
