import { DIFFICULTIES, type Difficulty } from "@spoin/shared/enums";

/*
 * Stratified allocation of a slate across difficulty tiers. ADR-0010's central move:
 * the difficulty mix is a constraint, not a score. Folded into ranking as a weight it
 * would drift with the candidate pool and be untestable; pulled per stratum and
 * ranked within each, it is exact. Score items; enforce composition structurally.
 */

export type Mix = Partial<Record<Difficulty, number>>;

/**
 * The mix per reader tier (content-model.md). The upward slice is load-bearing beyond
 * variety: a beginner engaging with their intermediate cards is the promotion signal,
 * so do not "simplify" it away.
 */
export const DIFFICULTY_MIX: Record<Difficulty, Mix> = {
  beginner: { beginner: 0.8, intermediate: 0.2 },
  intermediate: { beginner: 0.2, intermediate: 0.7, advanced: 0.1 },
  advanced: { beginner: 0.02, intermediate: 0.08, advanced: 0.9 },
};

const entries = (mix: Mix) =>
  DIFFICULTIES.filter((d) => mix[d] !== undefined).map((d) => [d, mix[d] ?? 0] as const);

/**
 * The mix for one topic and tier now, given how much of that tier's own cards the
 * reader has read (0-1). Below `rampStart` it is all `tier`: there is no promotion
 * signal to collect yet. Between the two it eases linearly toward DIFFICULTY_MIX,
 * which is the ceiling it ramps to, not the start. At `rampEnd` and above, the preset.
 */
export function dynamicMix(
  tier: Difficulty,
  readFraction: number,
  ramp: { start: number; end: number },
): Mix {
  const target = DIFFICULTY_MIX[tier];
  if (readFraction <= ramp.start) return { [tier]: 1 };
  if (readFraction >= ramp.end || ramp.end <= ramp.start) return { ...target };
  const t = (readFraction - ramp.start) / (ramp.end - ramp.start);
  const mix: Mix = {};
  for (const d of DIFFICULTIES) {
    if (d !== tier && target[d] === undefined) continue;
    mix[d] = (d === tier ? 1 : 0) * (1 - t) + (target[d] ?? 0) * t;
  }
  return mix;
}

/**
 * `size` slots split across difficulties by largest remainder, so the parts always
 * sum to exactly `size`. Naive rounding gains or loses a slot and turns "exactly 80%"
 * back into "roughly 80%", the thing this whole approach exists to avoid.
 */
export function allocate(
  size: number,
  tier: Difficulty,
  mix: Mix = DIFFICULTY_MIX[tier],
): Map<Difficulty, number> {
  const exact = entries(mix).map(([d, share]) => ({ d, share, value: size * share }));
  const counts = new Map(exact.map((e) => [e.d, Math.trunc(e.value)]));
  const remaining = size - [...counts.values()].reduce((a, b) => a + b, 0);
  if (remaining > 0) {
    const byRemainder = [...exact].sort(
      (a, b) => b.value - Math.trunc(b.value) - (a.value - Math.trunc(a.value)) || b.share - a.share,
    );
    for (const e of byRemainder.slice(0, remaining)) counts.set(e.d, (counts.get(e.d) ?? 0) + 1);
  }
  return counts;
}

export type StratumFill = { difficulty: Difficulty; requested: number; available: number };

export const served = (f: StratumFill) => Math.min(f.requested, f.available);

/**
 * What a slate build could actually serve, and whether that is degraded. The mix is
 * a target, not a guarantee; with a thin corpus it falls short constantly, so the
 * honest outcome is a return value rather than an exception.
 */
export type MixOutcome = { fills: StratumFill[]; degraded: boolean };

/**
 * What to serve when the pool cannot satisfy the mix (ADR-0006):
 *
 * 1. Never backfill a starved stratum with the current difficulty: serve a shorter
 *    page. Backfilling destroys the upward slice that is the promotion signal and
 *    hides pool starvation exactly when it most needs seeing.
 * 2. Hysteresis: enter degraded below `poolLow`, leave only above `poolHigh`. With one
 *    threshold the pool sits on the line and every crossing re-triggers work.
 */
export function resolveMix(
  size: number,
  tier: Difficulty,
  available: Map<Difficulty, number>,
  opts: { wasDegraded: boolean; poolLow: number; poolHigh: number; mix?: Mix },
): MixOutcome {
  const fills = [...allocate(size, tier, opts.mix)].map(([difficulty, requested]) => ({
    difficulty,
    requested,
    available: available.get(difficulty) ?? 0,
  }));
  const total = fills.reduce((sum, f) => sum + f.available, 0);
  return { fills, degraded: opts.wasDegraded ? total < opts.poolHigh : total < opts.poolLow };
}
