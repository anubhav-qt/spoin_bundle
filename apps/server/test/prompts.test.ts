import { describe, expect, test } from "vitest";
import { loadPrompts } from "../src/prompts.ts";

/*
 * Every template renders its fixture, and the same data always renders the same prompt
 * (task 0045, after Trotter's ADR 0020).
 */

const prompts = loadPrompts();

const items = [
  {
    index: 0,
    stem: "Why does ice float on water?",
    rubric: "0: wrong. 1: lighter. 2: less dense. 3: and why: hydrogen bonds hold it open.",
    referenceAnswer: "Ice is less dense than liquid water.",
    userAnswer: "It is less dense,\nso it floats.",
  },
  {
    index: 1,
    stem: "Name a noble gas.",
    rubric: "2: any noble gas.",
    referenceAnswer: "Neon.",
    userAnswer: "",
  },
];

describe("the grader's prompts", () => {
  test("the instructions and the tool's description render, with no data", () => {
    expect(prompts.render("grader.njk", {})).toMatch(/^You grade readers' written quiz answers/);
    expect(prompts.render("tools/grade.njk", {})).toMatch(/^Hands in your grades/);
  });

  test("each answer sits in its own question, after its rubric and reference answer", () => {
    const text = prompts.render("grader-answers.njk", { items });
    expect(text).toContain(
      '<question index="0">\n<stem>\nWhy does ice float on water?\n</stem>\n<rubric>\n0: wrong.',
    );
    expect(text).toContain("<answer>\nIt is less dense,\nso it floats.\n</answer>\n</question>");
    expect(text).toContain('<question index="1">');
    expect(text.endsWith("grade each reader's answer against its question's rubric.")).toBe(true);
    expect(prompts.render("grader-answers.njk", { items })).toBe(text);
  });

  test("a missing value is an error, not a blank in the prompt", () => {
    const [first] = items;
    expect(() =>
      prompts.render("grader-answers.njk", { items: [{ ...first, rubric: undefined }] }),
    ).toThrow();
  });
});
