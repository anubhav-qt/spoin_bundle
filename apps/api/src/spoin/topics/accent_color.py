"""ADR-0075: the default topic accent hue, chosen by embedding similarity.

When a user subscribes to a topic and hasn't picked a colour, the old default
(ADR-0034) was a client-side function of subscription order and a string hash --
no meaning, and not even distinct past the tenth topic. This module replaces it:
rank a curated colour vocabulary by embedding similarity to the topic, then walk
that ranking best-first and take the first hue that is at least
`ACCENT_HUE_MIN_DISTANCE` degrees from every hue the user's other topics already
use. The chosen int is written to `UserTopic.accent_hue` at subscribe time.

Which colour is taste -- embeddings decide it. That the colour is *distinct* is a
constraint -- angle arithmetic here decides it, never the model or the prompt
(CLAUDE.md, "generator trusted for taste, never for constraints").

Degradation is deliberate and total: with the `HashEmbedder` stand-in (no
fastembed model -- the dev/test default) `assign_accent_hue` returns `None`, the
caller leaves the column null, and the client renders `defaultTopicHue` exactly
as before ADR-0075. A missing/broken vocabulary file falls to that same
positional default. Neither is an error path.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from spoin.embeddings import Embedder, HashEmbedder, normalize_topic_text

#: ADR-0075. A vocabulary hue within this many degrees of a hue one of the
#: user's other topics already uses is skipped. 360 / 25 -> ~14 distinct slots
#: before the wheel is crowded and assignment falls back to the positional
#: default -- ADR-0034's curated scheme hit its own ceiling at 10.
ACCENT_HUE_MIN_DISTANCE = 25

#: ADR-0051's opt-out sentinel stored in `UserTopic.accent_hue` -- "render the
#: plain palette accent, no per-topic tint". Not a real hue; excluded from the
#: used-hue set and never returned by `assign_accent_hue`. Mirrors
#: `NO_TOPIC_COLOR` in apps/web/lib/topicColor.ts.
NO_TOPIC_COLOR = -1

#: ADR-0034's curated ten, 36 deg apart. The fallback spread when the vocabulary
#: cannot place a distinct hue. Ported from `CURATED_DEFAULT_HUES` in
#: apps/web/lib/topicColor.ts -- the two must stay identical so a `null` row the
#: client renders and the hue the server infers for it during dedup agree.
_CURATED_DEFAULT_HUES = (12, 48, 84, 120, 156, 192, 228, 264, 300, 336)


@dataclass(frozen=True)
class ColorEntry:
    name: str
    hue: int


@lru_cache
def load_color_vocabulary() -> tuple[ColorEntry, ...]:
    """`accent_color_data/colors.json`, parsed once per process. A missing or
    malformed file returns an empty tuple -- the caller then uses the positional
    default, which is a correct fallback, not a broken one (same stance as
    `content/ascii_library.load_library`)."""

    target = resources.files("spoin.topics") / "accent_color_data" / "colors.json"
    if not target.is_file():
        return ()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        rows = payload["colors"]
    except (ValueError, KeyError, OSError):
        return ()

    entries: list[ColorEntry] = []
    for row in rows:
        try:
            name = str(row["name"]).strip()
            hue = int(row["hue"]) % 360
        except (KeyError, TypeError, ValueError):
            continue
        if name:
            entries.append(ColorEntry(name=name, hue=hue))
    return tuple(entries)


def _to_int32(value: int) -> int:
    """JS `x | 0`: wrap to a signed 32-bit int."""

    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def hash_topic_hue(topic_id: str) -> int:
    """Port of `hashTopicId` in apps/web/lib/topicColor.ts. Kept byte-identical
    so the server can reconstruct the effective hue of a legacy `null` row the
    client is rendering, and dedup a new topic against it."""

    hash_ = 0
    for char in topic_id:
        hash_ = _to_int32(hash_ * 31 + ord(char))
    return abs(hash_) % 360


def default_hue_positional(topic_id: str, subscription_index: int | None) -> int:
    """Port of `defaultTopicHue`: ADR-0034's curated-ten-then-hash spread. The
    fallback when embeddings are present but the wheel is too crowded for a
    distinct vocabulary hue, and the value the server imputes for a legacy
    `null` row when building the used-hue set."""

    if subscription_index is not None and subscription_index < len(_CURATED_DEFAULT_HUES):
        return _CURATED_DEFAULT_HUES[subscription_index]
    return hash_topic_hue(topic_id)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _angular_distance(a: int, b: int) -> int:
    delta = abs(a - b) % 360
    return min(delta, 360 - delta)


#: Populated once per process by `_vocabulary_index`, behind `_index_lock` so two
#: concurrent subscriptions don't both pay the embedding cost. `None` until first
#: computed. Assumes one embedder process-wide, same as `embeddings.get_embedder`'s
#: own `lru_cache`.
_index_cache: list[list[float]] | None = None
_index_lock = asyncio.Lock()


async def _vocabulary_index(embedder: Embedder) -> list[list[float]]:
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    async with _index_lock:
        if _index_cache is None:  # re-check: another caller may have won the race
            vocab = load_color_vocabulary()
            _index_cache = (
                await embedder.aembed([normalize_topic_text(entry.name) for entry in vocab])
                if vocab
                else []
            )
    return _index_cache


async def assign_accent_hue(
    embedder: Embedder,
    *,
    topic_id: str,
    topic_name: str,
    topic_embedding: list[float] | None,
    used_hues: set[int],
    subscription_index: int | None,
) -> int | None:
    """The hue to persist on `UserTopic.accent_hue` for a fresh subscription, or
    `None` when there is no real embedder (the caller leaves the column null and
    the client renders the positional default -- ADR-0075's total degradation).

    `topic_embedding` is reused from `Topic.embedding` (ADR-0025 already paid for
    it); only a topic that somehow has none triggers a name embed here.
    `used_hues` is the set of hues the user's *other* topics occupy -- explicit
    choices as-is, legacy `null` rows imputed via `default_hue_positional`, opt-out
    (`-1`) rows omitted entirely.
    """

    if isinstance(embedder, HashEmbedder):
        return None

    vocab = load_color_vocabulary()
    if not vocab:
        return default_hue_positional(topic_id, subscription_index)

    if topic_embedding is not None:
        query_vec = list(topic_embedding)
    else:
        query_vec = list((await embedder.aembed([normalize_topic_text(topic_name)]))[0])

    index = await _vocabulary_index(embedder)
    ranked = sorted(
        zip(vocab, index, strict=True),
        key=lambda pair: _cosine(pair[1], query_vec),
        reverse=True,
    )
    for entry, _vec in ranked:
        if all(_angular_distance(entry.hue, used) >= ACCENT_HUE_MIN_DISTANCE for used in used_hues):
            return entry.hue

    # The wheel is too crowded for a distinct vocabulary hue. Fall back to the
    # positional spread, and persist it so later subscriptions dedup against it.
    return default_hue_positional(topic_id, subscription_index)
