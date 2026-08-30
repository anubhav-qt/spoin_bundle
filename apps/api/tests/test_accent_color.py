"""ADR-0075: embedding-derived topic accent hue.

The semantic half (which colour a topic leans toward) is taste and not pinned
here. What is pinned is the constraint half -- the distance filter, the
positional fallback, the byte-for-byte agreement with the client's hash, and the
total degradation to `None` when there is no real embedder.
"""

from __future__ import annotations

import pytest

from spoin.embeddings import Embedder, HashEmbedder
from spoin.topics import accent_color
from spoin.topics.accent_color import (
    ACCENT_HUE_MIN_DISTANCE,
    ColorEntry,
    _angular_distance,
    assign_accent_hue,
    default_hue_positional,
    hash_topic_hue,
    load_color_vocabulary,
)


class _StubEmbedder(Embedder):
    """Returns a fixed vector per (normalized) string, [0,0,0,0] for anything
    unknown. Not a `HashEmbedder`, so `assign_accent_hue` treats it as real."""

    def __init__(self, table: dict[str, list[float]]) -> None:
        self._table = table

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(self._table.get(text, [0.0, 0.0, 0.0, 0.0])) for text in texts]


@pytest.fixture(autouse=True)
def _reset_vocab_caches() -> object:
    """`load_color_vocabulary` is `lru_cache`d and `_vocabulary_index` holds a
    module global -- both have to be cleared around any test that monkeypatches
    the vocabulary."""

    accent_color._index_cache = None
    load_color_vocabulary.cache_clear()
    yield
    accent_color._index_cache = None
    load_color_vocabulary.cache_clear()


# --------------------------------------------------------- pure arithmetic ---


def test_angular_distance_wraps_around_the_wheel() -> None:
    assert _angular_distance(10, 20) == 10
    assert _angular_distance(350, 10) == 20
    assert _angular_distance(0, 359) == 1
    assert _angular_distance(0, 180) == 180


def test_hash_topic_hue_matches_the_client_port() -> None:
    """`hashTopicId` in apps/web/lib/topicColor.ts, reference values computed
    from that exact JS. If this drifts, a legacy `null` row the client renders
    one colour and the server dedups against another."""

    # h = ((0*31 + 97) | 0) => 97 ; 97 % 360 == 97
    assert hash_topic_hue("a") == 97
    # "abc": 97 -> 97*31+98=3105 -> 3105*31+99=96354 ; 96354 % 360 == 234
    assert hash_topic_hue("abc") == 96354 % 360
    assert 0 <= hash_topic_hue("11111111-1111-1111-1111-111111111111") < 360


def test_default_hue_positional_is_curated_then_hash() -> None:
    assert default_hue_positional("x", 0) == 12
    assert default_hue_positional("x", 9) == 336
    assert default_hue_positional("abc", 10) == 96354 % 360
    assert default_hue_positional("abc", None) == 96354 % 360


# ------------------------------------------------------------- vocabulary ----


def test_shipped_vocabulary_is_well_formed() -> None:
    vocab = load_color_vocabulary()
    assert len(vocab) >= 150, "the shipped list should be a few hundred entries"
    assert all(0 <= entry.hue < 360 for entry in vocab)
    assert all(entry.name.strip() for entry in vocab)
    # A spread, not a cluster: every 40-degree bucket has at least one name.
    buckets = {entry.hue // 40 for entry in vocab}
    assert buckets == set(range(9))


# ------------------------------------------------------ assign_accent_hue ----

_VECS = {
    "blue": [1.0, 0.0, 0.0, 0.0],
    "navy": [0.99, 0.14, 0.0, 0.0],
    "red": [0.0, 1.0, 0.0, 0.0],
    "green": [0.0, 0.0, 1.0, 0.0],
    "moss": [0.0, 0.0, 0.0, 1.0],
    "ocean topic": [1.0, 0.0, 0.0, 0.0],
}
_FAKE_VOCAB = (
    ColorEntry("blue", 230),
    ColorEntry("navy", 235),
    ColorEntry("red", 0),
    ColorEntry("green", 120),
    ColorEntry("moss", 100),
)


@pytest.fixture
def _fake_vocab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(accent_color, "load_color_vocabulary", lambda: _FAKE_VOCAB)


async def test_hash_embedder_yields_no_hue() -> None:
    """Total degradation: dev/test default leaves the column null and the client
    renders the positional default, exactly as before ADR-0075."""

    hue = await assign_accent_hue(
        HashEmbedder(4),
        topic_id="t",
        topic_name="Marine Biology",
        topic_embedding=[0.1, 0.2, 0.3, 0.4],
        used_hues=set(),
        subscription_index=0,
    )
    assert hue is None


async def test_picks_the_nearest_vocabulary_hue(_fake_vocab: None) -> None:
    hue = await assign_accent_hue(
        _StubEmbedder(_VECS),
        topic_id="t",
        topic_name="ocean",
        topic_embedding=list(_VECS["blue"]),
        used_hues=set(),
        subscription_index=0,
    )
    assert hue == 230


async def test_skips_hues_within_the_min_distance_of_a_used_hue(_fake_vocab: None) -> None:
    """blue (230) and navy (235) are both too close to the taken hue 230; the
    next-best surviving candidate by similarity is red (0)."""

    hue = await assign_accent_hue(
        _StubEmbedder(_VECS),
        topic_id="t",
        topic_name="ocean",
        topic_embedding=list(_VECS["blue"]),
        used_hues={230},
        subscription_index=1,
    )
    assert hue == 0
    assert _angular_distance(hue, 230) >= ACCENT_HUE_MIN_DISTANCE


async def test_embeds_the_name_when_the_topic_has_no_embedding(_fake_vocab: None) -> None:
    hue = await assign_accent_hue(
        _StubEmbedder(_VECS),
        topic_id="t",
        topic_name="ocean topic",
        topic_embedding=None,
        used_hues=set(),
        subscription_index=0,
    )
    assert hue == 230


async def test_falls_back_to_positional_when_every_candidate_is_too_close(
    _fake_vocab: None,
) -> None:
    """Wheel crowded from every side -> no vocab hue clears the filter -> the
    curated positional default, persisted so later topics dedup against it."""

    hue = await assign_accent_hue(
        _StubEmbedder(_VECS),
        topic_id="t",
        topic_name="ocean",
        topic_embedding=list(_VECS["blue"]),
        used_hues={0, 100, 120, 230, 235},
        subscription_index=0,
    )
    assert hue == 12  # curated slot 0


async def test_empty_vocabulary_falls_back_to_positional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(accent_color, "load_color_vocabulary", lambda: ())
    hue = await assign_accent_hue(
        _StubEmbedder(_VECS),
        topic_id="abc",
        topic_name="ocean",
        topic_embedding=list(_VECS["blue"]),
        used_hues=set(),
        subscription_index=15,  # past the curated 10 -> hash path
    )
    assert hue == hash_topic_hue("abc") == 234
