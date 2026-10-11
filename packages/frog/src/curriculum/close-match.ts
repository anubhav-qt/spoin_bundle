/*
 * Python's `difflib.get_close_matches`, for the curriculum check's "did you mean". The
 * similarity is SequenceMatcher's Ratcliff/Obershelp ratio, 2*M/T, where M counts the
 * characters in the longest matching blocks found recursively. Without the autojunk
 * heuristic, which only applies to strings of 200 characters or more; headings are
 * shorter than that.
 */

/** The longest common block in a[alo:ahi] and b[blo:bhi]: earliest in `a`, then earliest in `b`. */
function longestMatch(
  a: string[],
  b2j: Map<string, number[]>,
  alo: number,
  ahi: number,
  blo: number,
  bhi: number,
): [number, number, number] {
  let best: [number, number, number] = [alo, blo, 0];
  let j2len = new Map<number, number>();
  for (let i = alo; i < ahi; i++) {
    const next = new Map<number, number>();
    for (const j of b2j.get(a[i] as string) ?? []) {
      if (j < blo) continue;
      if (j >= bhi) break;
      const k = (j2len.get(j - 1) ?? 0) + 1;
      next.set(j, k);
      if (k > best[2]) best = [i - k + 1, j - k + 1, k];
    }
    j2len = next;
  }
  return best;
}

/** SequenceMatcher(None, a, b).ratio(). */
export function similarity(left: string, right: string): number {
  const a = [...left];
  const b = [...right];
  if (a.length + b.length === 0) return 1;
  const b2j = new Map<string, number[]>();
  b.forEach((ch, j) => {
    const list = b2j.get(ch);
    if (list) list.push(j);
    else b2j.set(ch, [j]);
  });
  let matched = 0;
  const queue: [number, number, number, number][] = [[0, a.length, 0, b.length]];
  while (queue.length > 0) {
    const [alo, ahi, blo, bhi] = queue.pop() as [number, number, number, number];
    const [i, j, k] = longestMatch(a, b2j, alo, ahi, blo, bhi);
    if (k === 0) continue;
    matched += k;
    if (alo < i && blo < j) queue.push([alo, i, blo, j]);
    if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
  }
  return (2 * matched) / (a.length + b.length);
}

/** The candidate most like `word`, if any scores at least `cutoff`; a tie goes to the later string, as in Python. */
export function closestMatch(word: string, candidates: string[], cutoff = 0.6): string | null {
  let best: { score: number; candidate: string } | null = null;
  for (const candidate of candidates) {
    const score = similarity(candidate, word);
    if (score < cutoff) continue;
    if (!best || score > best.score || (score === best.score && candidate > best.candidate)) {
      best = { score, candidate };
    }
  }
  return best?.candidate ?? null;
}
