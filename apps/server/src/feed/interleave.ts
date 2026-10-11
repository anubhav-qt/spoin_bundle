import { createHash } from "node:crypto";

/*
 * The cross-topic interleave plan (ADR-0010). Weighted round-robin with deficit
 * counters, the algorithm packet schedulers use for weighted fair queuing:
 * deterministic, and a topic with 2x the weight gets 2x the slots spread evenly
 * rather than clumped into a run.
 *
 * This is the cheap, volatile half of pagination. The per-topic ranked slate is
 * cached because it is rarely invalidated; this half is rebuilt freely on a filter
 * change, a share shift or a slate refill, since rebuilding it ranks nothing.
 */

/**
 * `size` topic slots, in proportion to weight. `runLength` is how many consecutive
 * slots a topic wins at a time: at 1 this is ADR-0010's "spread evenly"; above 1 the
 * share each topic gets is unchanged, only the granularity of alternation, which is
 * what lets the client group cards under per-topic headings.
 *
 * No topics is an empty plan, not an error: a user with no subscriptions is ordinary.
 */
export function buildPlan(weights: Map<string, number>, size: number, runLength = 1): string[] {
  const topics = [...weights.keys()].filter((t) => (weights.get(t) ?? 0) > 0);
  if (topics.length === 0 || size <= 0) return [];
  const w = (t: string) => weights.get(t) ?? 0;
  const run = Math.max(1, runLength);

  // Deterministic, so a surprising feed can be reproduced from a bug report.
  topics.sort((a, b) => w(b) - w(a) || (a < b ? -1 : Number(a > b)));

  const total = topics.reduce((sum, t) => sum + w(t), 0);
  const deficits = new Map(topics.map((t) => [t, 0]));
  const plan: string[] = [];
  // Deficit round-robin over whole runs: awarding a run and charging the winner for
  // all of it keeps the long-run share proportional to weight.
  while (plan.length < size) {
    for (const t of topics) deficits.set(t, (deficits.get(t) ?? 0) + (run * w(t)) / total);
    // Ties go to the earlier topic in the sorted order.
    let winner = topics[0] as string;
    for (const t of topics) if ((deficits.get(t) ?? 0) > (deficits.get(winner) ?? 0)) winner = t;
    deficits.set(winner, (deficits.get(winner) ?? 0) - run);
    for (let i = 0; i < Math.min(run, size - plan.length); i++) plan.push(winner);
  }
  return plan;
}

/**
 * A stable key for the active topic filter. A filter change rebuilds the plan and
 * keeps every slate, which is why filtering to one topic, reading and unfiltering
 * resumes every other topic exactly where it was. A digest, not the joined ids: two
 * ids already overflow the 64-character column, which 500'd the Python feed.
 */
export const filterKey = (topicIds?: string[] | null): string =>
  topicIds?.length
    ? createHash("sha1")
        .update([...topicIds].sort().join(","))
        .digest("hex")
    : "";
