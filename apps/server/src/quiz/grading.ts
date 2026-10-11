/*
 * Grading arithmetic and the prompt-injection guard. Pure functions, so the scoring
 * formula and the injection defence are tested with a table, not through a model.
 */

/** Words of 4+ letters, used by `referencesQuestion`. */
const TOKEN = /[a-zA-Z]{4,}/g;

export const tokens = (text: string): Set<string> =>
  new Set(Array.from(text.matchAll(TOKEN), (m) => m[0].toLowerCase()));

/**
 * A code-level check that the grader's justification is about THIS question
 * (ADR-0009's prompt-injection defence: the prompt tells the model to grade the
 * answer as data, and this re-checks the model's output rather than trusting it).
 *
 * A cheap heuristic, not a second model call: any shared 4+-letter word with the
 * stem, the reference answer or the submitted answer is enough. Sharing none is a
 * strong sign an injected instruction got echoed back, or the response is degenerate.
 */
export function referencesQuestion(justification: string, ...contexts: string[]): boolean {
  const said = tokens(justification);
  if (said.size === 0) return false;
  return contexts.some((context) => [...tokens(context)].some((t) => said.has(t)));
}

/**
 * ADR-0009's weighted split, rounded before any threshold comparison. The rounding is
 * load-bearing: 0.7 + 0.3 * (1/3) is 0.7999999999999999 in binary floating point, which
 * fails an exact `>= 0.80` pass mark the reader earned.
 */
export function combinedScore(o: {
  mcqFraction: number;
  rubricLevel: number;
  mcqWeight: number;
  freeTextWeight: number;
}): number {
  return Math.round((o.mcqWeight * o.mcqFraction + o.freeTextWeight * (o.rubricLevel / 3)) * 1e6) / 1e6;
}
