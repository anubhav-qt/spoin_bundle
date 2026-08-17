"""Near-duplicate detection (content-model.md check #1, unchanged by ADR-0030).

Two comparisons, both against `Card.content_embedding` computed AFTER the
quality gate's pass-1 correction (ADR-0030) -- comparing against
pre-correction text would compare against content that never actually ships:

1. **Corpus.** Local, free (hard rule 5), scoped to the SUBTOPIC (ADR-0007 --
   cheaper and more precise than topic-wide) against existing ACTIVE cards.
2. **Intra-batch.** Neither the corpus comparison nor the curriculum's
   title-list prevention catches a model writing near-identical cards within
   one response (ADR-0007's "intra-batch dedup is still required"). This uses
   a RUNNING SET: each new card is compared only against cards already
   accepted earlier in the same batch, not all-pairs -- linear in batch size,
   same principle as how corpus comparison already works (compare against
   what exists so far).

`card_duplicate_threshold` (config.py, currently 0.9) has not been calibrated
against real embeddings -- only `HashEmbedder` is exercised in tests, and
content-model.md's own docs call that "not semantically meaningful." Treat the
threshold as a conservative placeholder pending real `fastembed` data.
"""

from __future__ import annotations

import math
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.domain.enums import CardStatus
from spoin.domain.models import Card


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def find_corpus_duplicate(
    session: AsyncSession,
    *,
    subtopic_id: uuid.UUID,
    embedding: list[float],
    threshold: float,
) -> float | None:
    """Nearest existing ACTIVE card in this subtopic. Returns its similarity
    if it clears `threshold`, else None -- never returns a similarity below
    the threshold, so callers can treat any non-None return as a reject."""

    row = (
        await session.execute(
            select(Card.content_embedding.cosine_distance(embedding).label("distance"))
            .where(
                Card.subtopic_id == subtopic_id,
                Card.status == CardStatus.ACTIVE,
                Card.content_embedding.is_not(None),
            )
            .order_by("distance")
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    similarity = 1.0 - row.distance
    return similarity if similarity >= threshold else None


def find_batch_duplicate(
    embedding: list[float], accepted_embeddings: list[list[float]], *, threshold: float
) -> float | None:
    """Running-set intra-batch comparison. `accepted_embeddings` is every
    embedding already accepted earlier in this same batch, in the order they
    were accepted."""

    best = 0.0
    for other in accepted_embeddings:
        similarity = cosine_similarity(embedding, other)
        if similarity > best:
            best = similarity
    return best if best >= threshold else None
