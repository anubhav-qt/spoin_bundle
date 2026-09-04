"""The embedder factory.

**The `Embedder` classes live in `frog.embeddings`** (ADR-0087), and since ADR-0093 so
does `normalize_topic_text`. What is left here is the one thing that is genuinely
`spoin`'s: `get_embedder()`, because choosing between `HashEmbedder` and
`FastEmbedEmbedder` reads `spoin.core.config`, and frog cannot import `spoin`. Giving
frog its own settings object would put `embedding_dim` in two places, and a divergence
there produces vectors that are silently not comparable to `card.content_embedding`.

This module deliberately does **not** re-export frog's classes, and does not re-export
the normalizer either. Import `Embedder`, `HashEmbedder`, `FastEmbedEmbedder` and
`normalize_topic_text` from `frog.embeddings` directly — a shim here would hide the
`api -> frog` dependency at exactly the call sites that should show it.

Hard rule 5 (why any of this is local at all): embeddings never run against a paid or
quota'd API. 100% of scarce LLM quota is reserved for card generation. If embeddings
and generation shared a quota pool, topic canonicalization would throttle exactly when
signups spike — the worst possible moment for it to stop working.
"""

from __future__ import annotations

from functools import lru_cache

from frog.embeddings import Embedder, FastEmbedEmbedder, HashEmbedder

from spoin.core.config import get_settings

__all__ = ["get_embedder"]


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedder == "fastembed":
        return FastEmbedEmbedder(settings.embedding_model)
    return HashEmbedder(settings.embedding_dim)
