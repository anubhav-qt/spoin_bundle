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

from frog.embeddings import Embedder, FastEmbedEmbedder, HashEmbedder, Qwen3Embedder
from frog.universe.models import EMBEDDING_DIM

from spoin.core.config import get_settings

__all__ = ["get_corpus_embedder", "get_embedder"]


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedder == "fastembed":
        return FastEmbedEmbedder(settings.embedding_model)
    return HashEmbedder(settings.embedding_dim)


@lru_cache
def get_corpus_embedder() -> Embedder:
    """The embedder for `the_spoin_universe` queries -- a SECOND factory on purpose.

    A retrieval query has to be embedded by the model the chunks were embedded with,
    and that is not the model `get_embedder()` returns: `card.content_embedding` is
    384-dimensional today while `chunk.embedding` is 1024 (ADR-0092), so sharing one
    factory would make every retrieval a dimension error rather than a silent quality
    loss. Task 0039 is where the two converge; until then they are two spaces and the
    code says so.

    Its dimension comes from frog's `EMBEDDING_DIM` rather than from a setting, because
    that constant is what the `chunk.embedding` column was created with -- a
    configurable that disagreed with it could only ever produce vectors the database
    refuses.
    """

    settings = get_settings()
    if settings.corpus_embedder == "qwen3":
        return Qwen3Embedder(settings.corpus_embedding_model)
    return HashEmbedder(EMBEDDING_DIM)
