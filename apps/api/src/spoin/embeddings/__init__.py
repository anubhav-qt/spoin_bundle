"""The embedder factory.

**The `Embedder` classes live in `frog.embeddings`** (ADR-0087), and since ADR-0093 so
does `normalize_topic_text`. What is left here is the one thing that is genuinely
`spoin`'s: `get_embedder()`, because choosing between `HashEmbedder` and
`Qwen3Embedder` reads `spoin.core.config`, and frog cannot import `spoin`.

**One embedder, one vector space** (ADR-0097). There were two factories here until
2026-09-05 — `get_embedder()` at 384 dimensions for cards, topics and questions, and
`get_corpus_embedder()` at 1024 for `the_spoin_universe` — because they returned
different models. They return the same model now, so the second factory would be a
distinction the code no longer has, which is exactly how the confusion started: a
retrieval query must be embedded by the model its chunks were, and two factories are a
way to get that wrong quietly. Task 0039 is the bug the split let through.

This module deliberately does **not** re-export frog's classes, and does not re-export
the normalizer either. Import `Embedder`, `HashEmbedder`, `Qwen3Embedder` and
`normalize_topic_text` from `frog.embeddings` directly — a shim here would hide the
`api -> frog` dependency at exactly the call sites that should show it.

Hard rule 5 (why any of this is local at all): embeddings never run against a paid or
quota'd API. 100% of scarce LLM quota is reserved for card generation. If embeddings
and generation shared a quota pool, topic canonicalization would throttle exactly when
signups spike — the worst possible moment for it to stop working.
"""

from __future__ import annotations

from functools import lru_cache

from frog.embeddings import Embedder, HashEmbedder, Qwen3Embedder
from frog.universe.models import EMBEDDING_DIM

from spoin.core.config import get_settings

__all__ = ["get_embedder"]


@lru_cache
def get_embedder() -> Embedder:
    """The embedder, for everything: cards, topics, questions, scenes, retrieval.

    Its dimension is frog's `EMBEDDING_DIM` rather than a setting, because that
    constant is what every vector column was created with — a configurable that
    disagreed with it could only ever produce vectors the database refuses.

    `HashEmbedder` is dimension-correct and semantically meaningless. It exists so the
    stack boots with no model weights on disk, not as a degraded mode worth running:
    see `Settings.embedder`.
    """

    settings = get_settings()
    if settings.embedder == "qwen3":
        return Qwen3Embedder(settings.embedding_model)
    return HashEmbedder(EMBEDDING_DIM)
