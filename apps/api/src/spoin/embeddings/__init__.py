"""The embedder factory, and topic-text normalization.

**The `Embedder` classes themselves live in `frog.embeddings`** (ADR-0087). This
module keeps only the two things that are genuinely `spoin`'s:

- `get_embedder()`, because choosing between `HashEmbedder` and `FastEmbedEmbedder`
  reads `spoin.core.config`, and frog cannot import `spoin`. Giving frog its own
  settings object would put `embedding_dim` in two places, and a divergence there
  produces vectors that are silently not comparable to `card.content_embedding`.
- `normalize_topic_text`, which is topic-canonicalization logic that happens to run
  before embedding rather than embedding infrastructure. Task 0001's threshold
  calibration depends on it, and ADR-0088 has `the_spoin_universe`'s chunk topic tags
  produced by this exact function so that tags and canonical topic names cannot drift
  into two vocabularies.

This module deliberately does **not** re-export frog's classes. Import `Embedder`,
`HashEmbedder` and `FastEmbedEmbedder` from `frog.embeddings` directly — a shim here
would hide the `api -> frog` dependency at exactly the call sites that should show it.

Hard rule 5 (why any of this is local at all): embeddings never run against a paid or
quota'd API. 100% of scarce LLM quota is reserved for card generation. If embeddings
and generation shared a quota pool, topic canonicalization would throttle exactly when
signups spike — the worst possible moment for it to stop working.
"""

from __future__ import annotations

from functools import lru_cache

from frog.embeddings import Embedder, FastEmbedEmbedder, HashEmbedder

from spoin.core.config import get_settings

__all__ = ["get_embedder", "normalize_topic_text"]


def normalize_topic_text(raw: str) -> str:
    """The normalization applied before embedding a topic string.

    **This must stay identical between calibration and production.** Task 0001 is
    required to write down exactly what it did; if the two ever diverge, the alias
    cache silently misses and every measured threshold stops meaning what it meant.

    ADR-0088 added a second caller with the same requirement: `the_spoin_universe`'s
    chunk `topic_tags` are produced by this function, and a change here re-tags the
    whole corpus or silently stops matching it.
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
