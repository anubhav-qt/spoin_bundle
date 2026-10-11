import { asc, desc } from "drizzle-orm";
import { generationJob } from "../db/schema.ts";

/*
 * The order the worker claims jobs in, and the one the topic queue page shows: higher
 * priority first, then oldest first. `id` breaks a tie between jobs made in one
 * transaction, which share `created_at`.
 */

export const QUEUE_ORDER = [
  desc(generationJob.priority),
  asc(generationJob.createdAt),
  asc(generationJob.id),
];

/** A topic the owner adds runs behind readers' requests (10) and ahead of repairs (-10). */
export const OWNER_PRIORITY = 0;

export type Waiting = { id: string; priority: number };

/**
 * The priorities that put `moved` just ahead of `before` (last, when null), given the
 * waiting jobs in claim order. Only what has to change changes: the moved job takes a
 * priority from its new neighbours, and when the jobs above it no longer run first they
 * are lifted one tie at a time, so jobs that tied before still tie. Returns the jobs
 * whose priority changes.
 */
export function reprioritize(
  queue: Waiting[],
  movedId: string,
  beforeId: string | null,
): Map<string, number> {
  if (beforeId === movedId) return new Map();
  // Within one priority the claim order is age then id, which is the order `queue` came in.
  const rank = new Map(queue.map((j, i) => [j.id, i]));
  const p = new Map(queue.map((j) => [j.id, j.priority]));
  const pr = (id: string) => p.get(id) as number;
  const earlier = (a: string, b: string) => (rank.get(a) as number) < (rank.get(b) as number);
  const runsBefore = (a: string, b: string) => (pr(a) !== pr(b) ? pr(a) > pr(b) : earlier(a, b));

  const order = queue.map((j) => j.id).filter((id) => id !== movedId);
  const at = beforeId === null ? order.length : order.indexOf(beforeId);
  if (at < 0 || !rank.has(movedId)) throw new Error("reprioritize: both jobs must be waiting");
  order.splice(at, 0, movedId);
  const above = order[at - 1];
  const below = order[at + 1];

  const fits = (!above || runsBefore(above, movedId)) && (!below || runsBefore(movedId, below));
  if (!fits) {
    // The lowest priority that still runs ahead of the job below, or with nothing below,
    // the highest that runs after the job above.
    if (below !== undefined) p.set(movedId, earlier(movedId, below) ? pr(below) : pr(below) + 1);
    else if (above !== undefined) p.set(movedId, earlier(above, movedId) ? pr(above) : pr(above) - 1);
  }

  for (let i = at - 1; i >= 0; ) {
    const id = order[i] as string;
    const next = order[i + 1] as string;
    if (runsBefore(id, next)) break;
    const was = pr(id);
    const to = earlier(id, next) ? pr(next) : pr(next) + 1;
    let j = i;
    while (j >= 0 && pr(order[j] as string) === was) {
      p.set(order[j] as string, to);
      j -= 1;
    }
    i = j;
  }

  const changed = new Map<string, number>();
  for (const j of queue) if (pr(j.id) !== j.priority) changed.set(j.id, pr(j.id));
  return changed;
}
