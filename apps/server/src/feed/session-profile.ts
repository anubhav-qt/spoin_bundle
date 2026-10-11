import { createHash } from "node:crypto";
import type { Env } from "../env.ts";

/*
 * Session-scoped topic shares (ADR-0055): each topic's accumulated session score
 * becomes its share of the interleave plan, between a floor and a ceiling. This is
 * the plan layer, not ranking, on purpose: "how much of the feed is this topic" is a
 * property of the page, not of any card on it, so no per-card score can express it.
 */

/**
 * Keeps a maximally skipped topic's weight positive. `buildPlan` drops anything at or
 * below zero, and a topic vanishing outright is more than this signal may say: the
 * floor exists so a bad ten minutes cannot bury a subscription.
 */
export const MIN_RAW_WEIGHT = 0.05;

/**
 * Signed saturation into (-1, 1), reaching ±0.5 at ±k. Session scores are unbounded;
 * saturating means "engaged" vs "very engaged" stops mattering long before "engaged"
 * vs "ignored" does.
 */
export const squash = (score: number, k: number) => score / (Math.abs(score) + k);

/** One topic's unnormalised weight. A score of 0 is exactly 1, so a fresh session is uniform. */
export const rawWeight = (score: number, env: Pick<Env, "SESSION_SIGNAL_BOOST" | "SESSION_SIGNAL_K">) =>
  Math.max(MIN_RAW_WEIGHT, 1 + env.SESSION_SIGNAL_BOOST * squash(score, env.SESSION_SIGNAL_K));

/** Each halves the bracket: far past where a float can tell two candidates apart. */
const BISECTION_STEPS = 200;

/**
 * Normalises `raw` into shares summing to 1, each within [lo, hi], by bisecting for
 * the one scale factor where the clipped sum is 1. Pinning violators and
 * redistributing, the obvious alternative, over-allocates when one topic is pinned up
 * and another down in the same pass; one scale for everyone cannot.
 *
 * `lo` and `hi` are requests: a 5% floor cannot hold across 21 topics, and a 50%
 * ceiling is meaningless for one. They are repaired to lo ≤ 1/n ≤ hi, exactly the
 * condition for a solution to exist, and every edge case falls out of that.
 */
export function clampShares(
  raw: Map<string, number>,
  bounds: { lo: number; hi: number },
): Map<string, number> {
  const n = raw.size;
  if (n === 0) return new Map();
  const lo = Math.min(bounds.lo, 1 / n);
  const hi = Math.max(bounds.hi, 1 / n);

  const largest = Math.max(...[...raw.values()].map((w) => Math.max(0, w)));
  if (largest <= 0) return new Map([...raw.keys()].map((t) => [t, 1 / n]));
  // A zero weight would clip to `lo` at every scale and could never absorb its part
  // of the remainder; an infinitesimal one keeps it last while letting it rise.
  const weights = new Map([...raw].map(([t, w]) => [t, Math.max(w, largest * 1e-12)]));
  const clip = (x: number) => Math.min(hi, Math.max(lo, x));
  const allocated = (lam: number) => [...weights.values()].reduce((sum, w) => sum + clip(lam * w), 0);

  // At this scale even the smallest weight saturates, so the sum is n·hi ≥ 1.
  let low = 0;
  let high = hi / Math.min(...weights.values());
  for (let i = 0; i < BISECTION_STEPS; i++) {
    const mid = (low + high) / 2;
    if (allocated(mid) < 1) low = mid;
    else high = mid;
  }
  const lam = (low + high) / 2;
  return new Map([...weights].map(([t, w]) => [t, clip(lam * w)]));
}

/**
 * A coarse, stable digest of a share distribution. The score moves on every event, so
 * exact comparison would rebuild the plan on every ingest; only a share crossing a
 * bucket boundary counts as a change worth reordering the feed for.
 */
export function shareFingerprint(shares: Map<string, number>, bucket: number): string {
  const buckets = [...shares]
    .map(([t, s]) => [t, bucket > 0 ? Math.round(s / bucket) : 0] as const)
    .sort(([a], [b]) => (a < b ? -1 : Number(a > b)));
  return createHash("sha1").update(JSON.stringify(buckets)).digest("hex").slice(0, 16);
}
