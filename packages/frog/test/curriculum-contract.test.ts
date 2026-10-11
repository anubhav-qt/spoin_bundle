import { describe, expect, it } from "vitest";
import {
  MAX_TARGET_CARDS,
  parseCurriculum,
  sourcePaths,
  splitGroundingRef,
} from "../src/curriculum/contract.ts";

/*
 * What the projection accepts from an authored curriculum, and what `curriculum:check`
 * hands back. Pure, like the corpus contract.
 */

const VALID = `---
topic: Rust
description: Systems programming with ownership, borrowing and fearless concurrency
scope: topic
subtopics:
  - title: Ownership & Move Semantics
    description: Why a value has exactly one owner, and what a move costs
    prerequisites: []
    tiers:
      beginner:
        target_cards: 18
        card_types: { prose: 8, code: 6, comparison: 2, ascii: 2 }
        grounding:
          - "cs/rust/foundations.md#Ownership"
          - "cs/rust/foundations.md#Move Semantics"
      intermediate:
        target_cards: 14
        card_types: { prose: 5, code: 6, diagram: 1, ascii: 2 }
        grounding:
          - "cs/rust/foundations.md#Borrowing"
  - title: Smart Pointers
    description: Heap ownership, shared ownership, and what each pointer costs
    prerequisites: [Ownership & Move Semantics]
    tiers:
      intermediate:
        target_cards: 15
        card_types: { prose: 6, code: 7, ascii: 2 }
        grounding:
          - "cs/rust/smart-pointers.md#Box and Heap Allocation"
---
`;

/** One subtopic and one tier, with `tier` spliced in under `tiers:`. */
const single = (tier: string, front = "scope: topic") => `---
topic: Rust
description: Systems programming
${front}
subtopics:
  - title: Ownership
    description: One owner per value
    prerequisites: []
    tiers:
${tier}
---
`;

const BEGINNER = `      beginner:
        target_cards: 5
        card_types: { prose: 5 }
        grounding:
          - "a.md#Ownership"`;

const parse = (text: string) => parseCurriculum("rust/curriculum.md", new TextEncoder().encode(text));
const problems = (text: string) => parse(text).errors.problems;
const has = (text: string, needle: string) => problems(text).some((p) => p.includes(needle));

describe("the curriculum contract", () => {
  it("parses a valid curriculum", () => {
    const { curriculum, errors } = parse(VALID);
    expect(errors.problems).toEqual([]);
    expect(curriculum).toMatchObject({ topic: "Rust", scope: "topic" });
    expect(curriculum?.subtopics.map((s) => s.title)).toEqual([
      "Ownership & Move Semantics",
      "Smart Pointers",
    ]);
    const first = curriculum?.subtopics[0];
    expect(first?.tiers.map((t) => t.tier)).toEqual(["beginner", "intermediate"]);
    expect(first?.tiers[0]?.cardTypes).toEqual({ prose: 8, code: 6, comparison: 2, ascii: 2 });
    expect(curriculum?.contentHash).toHaveLength(64);
  });

  it.each(["survey", "topic", "one_shot"])("takes scope %s", (scope) => {
    expect(parse(VALID.replace("scope: topic", `scope: ${scope}`)).curriculum?.scope).toBe(scope);
  });

  it("names `scope` as the replacement for `is_survey`", () => {
    const found = problems(VALID.replace("scope: topic", "is_survey: false"));
    expect(found).toEqual([
      "`is_survey` was replaced by `scope`: `survey` for true, `topic` or `one_shot` for false",
    ]);
  });

  it("fails `is_survey` even beside a `scope`", () => {
    expect(
      has(VALID.replace("scope: topic", "scope: topic\nis_survey: false"), "`is_survey` was replaced"),
    ).toBe(true);
  });

  it("fails a scope outside the three", () => {
    expect(has(VALID.replace("scope: topic", "scope: maybe"), "`scope` must be one of")).toBe(true);
  });

  it("fails a file with no front matter", () => {
    expect(has("# Rust\n\njust prose\n", "front matter")).toBe(true);
  });

  it("fails a prose body after the front matter", () => {
    expect(has(`${VALID.trimEnd()}\n\nSome stray authoring notes.\n`, "no prose body")).toBe(true);
  });

  it("reports every missing top-level field at once", () => {
    const joined = problems("---\nsubtopics: []\n---\n").join("\n");
    expect(joined).toContain("`topic` is missing");
    expect(joined).toContain("`description` is missing");
    expect(joined).toContain("`scope` is required");
  });

  it("fails an empty subtopic list", () => {
    expect(
      has(
        "---\ntopic: X\ndescription: y\nscope: topic\nsubtopics: []\n---\n",
        "`subtopics` must be a non-empty list",
      ),
    ).toBe(true);
  });

  it("names the subtopic a missing field belongs to", () => {
    const raw =
      "---\ntopic: Rust\ndescription: d\nscope: topic\nsubtopics:\n  - title: Ownership\n    prerequisites: []\n---\n";
    expect(has(raw, 'subtopic "Ownership": `description` is missing')).toBe(true);
    expect(has(raw, 'subtopic "Ownership": `tiers` is missing')).toBe(true);
  });

  it("fails an unknown tier", () => {
    expect(has(VALID.replace("beginner:", "novice:"), 'unknown tier "novice"')).toBe(true);
  });

  it("fails an unknown card type", () => {
    expect(
      has(
        VALID.replace("{ prose: 6, code: 7, ascii: 2 }", "{ prose: 6, code: 7, meme: 2 }"),
        'unknown card type "meme"',
      ),
    ).toBe(true);
  });

  it("fails target_cards below the band the database enforces", () => {
    const raw = VALID.replace("target_cards: 15", "target_cards: 3").replace(
      "{ prose: 6, code: 7, ascii: 2 }",
      "{ prose: 1, code: 1, ascii: 1 }",
    );
    expect(has(raw, "outside the 5-25 band")).toBe(true);
  });

  it("fails target_cards above the band", () => {
    expect(
      has(
        VALID.replace("target_cards: 15", `target_cards: ${MAX_TARGET_CARDS + 1}`),
        "outside the 5-25 band",
      ),
    ).toBe(true);
  });

  it("fails a fractional target_cards", () => {
    expect(
      has(VALID.replace("target_cards: 15", "target_cards: 15.5"), "`target_cards` must be an integer"),
    ).toBe(true);
  });

  it("fails card_types that do not sum to target_cards", () => {
    const raw = VALID.replace(
      "{ prose: 8, code: 6, comparison: 2, ascii: 2 }",
      "{ prose: 8, code: 6, comparison: 2, ascii: 1 }",
    );
    expect(has(raw, "sums to 17, not `target_cards` (18)")).toBe(true);
  });

  it("fails a prerequisite that is not in the file", () => {
    expect(
      has(
        VALID.replace("prerequisites: [Ownership & Move Semantics]", "prerequisites: [Lifetimes]"),
        'prerequisite "Lifetimes" is not a subtopic',
      ),
    ).toBe(true);
  });

  it("reports a prerequisite cycle as a path", () => {
    const unit = (title: string, before: string) => `  - title: ${title}
    description: d
    prerequisites: [${before}]
    tiers:
      beginner:
        target_cards: 5
        card_types: { prose: 5 }
        grounding:
          - "x.md#${title}"`;
    const raw = `---\ntopic: Rust\ndescription: d\nscope: topic\nsubtopics:\n${unit("A", "B")}\n${unit("B", "A")}\n---\n`;
    expect(problems(raw)).toContain("prerequisite cycle: A -> B -> A: the graph must be a DAG");
  });

  it("fails a subtopic that is its own prerequisite", () => {
    expect(
      has(
        VALID.replace("prerequisites: [Ownership & Move Semantics]", "prerequisites: [Smart Pointers]"),
        "lists itself as a prerequisite",
      ),
    ).toBe(true);
  });

  it("fails a duplicate title, the projection's match key", () => {
    expect(
      has(VALID.replace("title: Smart Pointers", "title: Ownership & Move Semantics"), "duplicate title"),
    ).toBe(true);
  });

  it("derives a subtopic's source paths from its grounding, first seen first", () => {
    const { curriculum } = parse(VALID);
    expect(sourcePaths(curriculum?.subtopics[0] as never)).toEqual(["cs/rust/foundations.md"]);
    expect(curriculum?.subtopics[0]?.tiers[0]?.grounding).toEqual([
      "cs/rust/foundations.md#Ownership",
      "cs/rust/foundations.md#Move Semantics",
    ]);
  });

  it("fails a tier without grounding: it would fall through to an open query", () => {
    expect(
      has(
        single("      beginner:\n        target_cards: 5\n        card_types: { prose: 5 }"),
        "`grounding` is missing",
      ),
    ).toBe(true);
  });

  it("fails a grounding entry that is not path#heading", () => {
    expect(
      has(single(BEGINNER.replace('"a.md#Ownership"', '"invalid_path_without_hash"')), "grounding entry"),
    ).toBe(true);
  });

  it("fails the old subtopic-level `sources`, naming its replacement", () => {
    const raw = single(BEGINNER).replace(
      "    prerequisites: []",
      "    prerequisites: []\n    sources: [a.md]",
    );
    expect(has(raw, "`sources` was replaced by per-tier `grounding`")).toBe(true);
  });

  it("collapses a section named twice rather than failing", () => {
    const { curriculum, errors } = parse(single(`${BEGINNER}\n          - "a.md#Ownership"`));
    expect(errors.problems).toEqual([]);
    expect(curriculum?.subtopics[0]?.tiers[0]?.grounding).toEqual(["a.md#Ownership"]);
  });

  it("keeps a quoted heading that contains a colon", () => {
    const ref = "stellar.md#Physical Foundations: Hydrostatic Equilibrium and the Virial Thermostat";
    const { curriculum, errors } = parse(single(BEGINNER.replace('"a.md#Ownership"', `"${ref}"`)));
    expect(errors.problems).toEqual([]);
    expect(curriculum?.subtopics[0]?.tiers[0]?.grounding).toEqual([ref]);
  });

  it("splits a grounding reference on its first #", () => {
    expect(splitGroundingRef("a/b.md#C# and .NET")).toEqual(["a/b.md", "C# and .NET"]);
    expect(splitGroundingRef("a/b.md")).toBeNull();
    expect(splitGroundingRef("#heading")).toBeNull();
    expect(splitGroundingRef("a.md# ")).toBeNull();
  });
});
