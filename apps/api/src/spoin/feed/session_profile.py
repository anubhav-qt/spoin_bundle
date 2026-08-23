"""Session-scoped topic shares (ADR-0055).

Turns each topic's accumulated session score into its share of the interleave
plan, bounded by `session_share_floor` and `session_share_ceiling`.

This lives at the plan layer rather than in `ranking.py` on purpose. ADR-0010's
rule is *score individual items; enforce composition rules structurally* — the
reason the difficulty mix is stratified sampling and not a fifth ranking weight.
"How much of the feed is this topic" is a composition rule of exactly that shape:
it is a property of the page, not of any card on it, so no per-card score can
express it.

Pure functions, no I/O — same shape as `strata.py` and `interleave.py`.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from spoin.core.config import Settings

#: Keeps a maximally-skipped topic's weight strictly positive. `build_plan` drops
#: anything at or below zero (interleave.py), and a topic vanishing outright is a
#: stronger statement than this signal is ever entitled to make — the floor share
#: exists precisely so a bad ten minutes cannot bury a subscription.
MIN_RAW_WEIGHT = 0.05


def squash(score: float, k: float) -> float:
    """Signed saturation into (-1, 1), reaching +/-0.5 at +/-`k`.

    Session scores are unbounded — nothing stops a user racking up fifty points in
    one topic — and feeding that to a linear weight would let a single enthusiastic
    stretch swamp every other topic before the share clamp ever got a say. Saturating
    means the difference between "engaged" and "very engaged" stops mattering long
    before the difference between "engaged" and "ignored" does.
    """

    return score / (abs(score) + k)


def raw_weight(score: float, settings: Settings) -> float:
    """One topic's unnormalized plan weight.

    A score of 0 gives exactly 1.0, which is what makes a fresh session uniform
    across every topic — the "open to anything" reset the 30-minute window exists
    to deliver.
    """

    boosted = 1.0 + settings.session_signal_boost * squash(score, settings.session_signal_k)
    return max(MIN_RAW_WEIGHT, boosted)


#: Bisection steps. Each halves the bracket, so this is far past the point where
#: a float can still tell two candidates apart.
_BISECTION_STEPS = 200


def clamp_shares(raw: dict[UUID, float], *, lo: float, hi: float) -> dict[UUID, float]:
    """Normalize `raw` into shares summing to 1.0, every one within [lo, hi].

    Solves for the single scale factor `lam` where
    `sum(clip(lam * weight, lo, hi)) == 1`, by bisection. That sum is continuous
    and non-decreasing in `lam`, running from `n*lo` up to `n*hi` — an interval
    that brackets 1.0 once the bounds below are made feasible — so a root always
    exists and bisection always finds it.

    The obvious alternative, pinning whichever topics violate a bound and
    redistributing to the rest, is what this replaced: it over-allocates. Pinning
    a topic *up* to the floor and another *down* to the ceiling in the same pass
    can commit more than 1.0 in total, and the shares then do not sum to 1 no
    matter how many passes follow. Scaling has no such failure mode because every
    topic is always evaluated against the same `lam`.

    `lo` and `hi` are requests, not guarantees. Both can be arithmetically
    impossible — a 5% floor cannot hold across 21 topics, and a 50% ceiling is
    meaningless for a single one — so they are repaired to satisfy
    `lo_eff <= 1/n <= hi_eff`, which is exactly the condition for the feasible set
    to be non-empty. Every edge case falls out of that rather than needing its own
    branch.
    """

    topics = list(raw)
    n = len(topics)
    if n == 0:
        return {}

    lo_eff = min(lo, 1.0 / n)
    hi_eff = max(hi, 1.0 / n)

    weights = {topic: max(0.0, raw[topic]) for topic in topics}
    largest = max(weights.values())
    if largest <= 0.0:
        return dict.fromkeys(topics, 1.0 / n)

    # A zero-weight topic would clip to `lo` at every `lam` and so could never
    # absorb its part of the remainder, which can leave the total stuck below 1.
    # An infinitesimal weight keeps it ordered last while letting it rise.
    floor_weight = largest * 1e-12
    weights = {topic: max(weight, floor_weight) for topic, weight in weights.items()}

    def allocated(lam: float) -> float:
        return sum(min(hi_eff, max(lo_eff, lam * weight)) for weight in weights.values())

    # At this `lam` even the smallest weight saturates, so the sum is `n * hi_eff`,
    # which the feasibility repair guarantees is at or above 1.0.
    low, high = 0.0, hi_eff / min(weights.values())
    for _ in range(_BISECTION_STEPS):
        mid = (low + high) / 2.0
        if allocated(mid) < 1.0:
            low = mid
        else:
            high = mid

    lam = (low + high) / 2.0
    return {topic: min(hi_eff, max(lo_eff, lam * weight)) for topic, weight in weights.items()}


def share_fingerprint(shares: dict[UUID, float], bucket: float) -> str:
    """A coarse, stable digest of a share distribution.

    The session score moves on every single event, so comparing shares exactly
    would rebuild the interleave plan on every ingest. Bucketing means only a
    share that crosses a boundary counts as a change worth reordering the feed for.

    `hashlib`, not the builtin `hash`, which is salted per process — a plan built
    by one worker would look stale to the next and rebuild forever.
    """

    def quantize(share: float) -> int:
        return round(share / bucket) if bucket > 0 else 0

    buckets = sorted((str(topic), quantize(share)) for topic, share in shares.items())
    return hashlib.sha1(repr(buckets).encode(), usedforsecurity=False).hexdigest()[:16]
