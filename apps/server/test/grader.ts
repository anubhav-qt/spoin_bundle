import type { FreeTextGrade, FreeTextGradeQuery, Grader } from "../src/quiz/grader.ts";

/**
 * The model, stood in for. By default a blank answer is level 0 and anything else is
 * `level`, with a justification that names the question. A test that needs the model
 * to misbehave sets `reply`; `reset` puts the default back.
 */
const standIn = (q: FreeTextGradeQuery): FreeTextGrade | null => ({
  index: q.index,
  rubricLevel: q.userAnswer.trim() ? 2 : 0,
  justification: `Graded against the question '${q.stem.slice(0, 40)}'.`,
});

export const grader: Grader & {
  reply: (q: FreeTextGradeQuery) => FreeTextGrade | null;
  calls: number;
  reset: () => void;
} = {
  reply: standIn,
  calls: 0,
  reset() {
    this.reply = standIn;
  },
  async gradeFreeText(queries) {
    this.calls += 1;
    return queries.map((q) => this.reply(q)).filter((g) => g !== null);
  },
};
