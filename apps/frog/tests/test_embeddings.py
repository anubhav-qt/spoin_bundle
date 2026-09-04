"""`HashEmbedder`'s contract, which several thresholds quietly depend on.

These are unit tests with no database — the corpus store's behaviour is exercised in
task 0038's later phases, once ingestion exists to put something in it.
"""

from __future__ import annotations

import math

from frog.embeddings import HashEmbedder


def test_embed_takes_a_collection_and_returns_one_vector_per_text() -> None:
    """ADR-0005's batch rule applies to the embedder interface too, and the
    positional correspondence is what every caller assumes without checking."""

    vectors = HashEmbedder(dim=384).embed(["postgres", "kubernetes", "raft consensus"])

    assert len(vectors) == 3
    assert all(len(vector) == 384 for vector in vectors)


def test_vectors_are_unit_length() -> None:
    """pgvector cosine distance does not require normalized input, but
    `content_embedding` comparisons across the two databases assume a single
    convention. A stand-in that returned unnormalized vectors would make
    HashEmbedder-backed tests disagree with production for a reason no test names.
    """

    vector = HashEmbedder(dim=384).embed_one("distributed systems")
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)


def test_the_empty_string_does_not_divide_by_zero() -> None:
    """No tokens means a zero vector and a zero norm. Reachable from real input —
    a document chunk that is entirely punctuation normalizes to nothing."""

    assert HashEmbedder(dim=8).embed_one("   ") == [0.0] * 8


def test_it_is_deterministic() -> None:
    """The whole point of the stand-in. If this drifts, every test that compares a
    stored vector against a freshly computed one starts failing for an unrelated
    reason."""

    a = HashEmbedder(dim=64).embed_one("raft consensus")
    b = HashEmbedder(dim=64).embed_one("raft consensus")
    assert a == b


async def test_aembed_matches_embed() -> None:
    """`aembed` exists only to move the CPU-bound call off the event loop; it must
    not become a second implementation."""

    embedder = HashEmbedder(dim=32)
    texts = ["btree", "wal"]
    assert await embedder.aembed(texts) == embedder.embed(texts)
