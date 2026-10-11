import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { asc, count } from "drizzle-orm";
import { describe, expect, it } from "vitest";
import { closestMatch, similarity } from "../src/curriculum/close-match.ts";
import { ingestCurricula, validateCurricula } from "../src/curriculum/runner.ts";
import { curriculum, curriculumSubtopic } from "../src/universe/schema.ts";
import { useUniverse } from "./universe.ts";

/*
 * The cross-file check (every grounding reference names a real section) and ingestion,
 * idempotent by content hash. Ingestion runs against the real database because what is
 * under test is `source_path`'s UNIQUE and the CASCADE on `curriculum_subtopic`.
 */

const db = useUniverse();

const corpusDoc = (heading: string) => `---
kind: topic_source
title: Rust reference material
source: The Rust Reference
scope: topic
category: computer-science
topic_tags: [rust]
---
## ${heading}
Reference prose for the ${heading} section.
`;

const RUST = (description = "Systems programming") => `---
topic: Rust
description: ${description}
scope: topic
subtopics:
  - title: Ownership
    description: One owner per value
    prerequisites: []
    tiers:
      beginner:
        target_cards: 6
        card_types: { prose: 4, code: 2 }
        grounding:
          - "cs/ownership.md#Ownership Foundations"
  - title: Smart Pointers
    description: Heap and shared ownership
    prerequisites: [Ownership]
    tiers:
      intermediate:
        target_cards: 8
        card_types: { prose: 5, code: 3 }
        grounding:
          - "cs/pointers.md#Smart Pointers"
---
`;

/** A curricula tree and a corpus tree; `rust` replaces the Rust curriculum's text. */
function tree(rust = RUST()): { curricula: string; corpus: string } {
  const root = mkdtempSync(join(tmpdir(), "frog-curricula-"));
  const curricula = join(root, "curricula");
  const corpus = join(root, "corpus");
  mkdirSync(join(curricula, "rust"), { recursive: true });
  mkdirSync(join(corpus, "cs"), { recursive: true });
  writeFileSync(join(corpus, "cs", "ownership.md"), corpusDoc("Ownership Foundations"));
  writeFileSync(join(corpus, "cs", "pointers.md"), corpusDoc("Smart Pointers"));
  writeFileSync(join(curricula, "rust", "curriculum.md"), rust);
  return { curricula, corpus };
}

const failuresOf = (rust: string) => {
  const { curricula, corpus } = tree(rust);
  return validateCurricula(curricula, corpus).failures.flatMap((f) => f.problems);
};

describe("validating curricula against the corpus", () => {
  it("passes references to real sections", () => {
    const { curricula, corpus } = tree();
    const { passed, failures } = validateCurricula(curricula, corpus);
    expect(failures).toEqual([]);
    expect(passed.map((c) => [c.topic, c.sourcePath])).toEqual([["Rust", "rust/curriculum.md"]]);
  });

  it("fails a missing document, naming the subtopic and the path", () => {
    const found = failuresOf(RUST().replace("cs/ownership.md", "cs/typo.md"));
    expect(
      found.some((p) => p.includes('subtopic "Ownership"') && p.includes('"cs/typo.md" does not exist')),
    ).toBe(true);
  });

  it("fails a missing heading", () => {
    const found = failuresOf(RUST().replace("#Ownership Foundations", "#Nonexistent Heading"));
    expect(found.some((p) => p.includes("has no `## Nonexistent Heading` section"))).toBe(true);
  });

  it("does not take a prefix of a real heading for a match", () => {
    // `## Ownership Foundations` must not satisfy `#Ownership`; agreeing with the chunker
    // is the point, because a reference that validates must resolve to a row.
    const found = failuresOf(RUST().replace("#Ownership Foundations", "#Ownership"));
    expect(found.some((p) => p.includes("has no `## Ownership` section"))).toBe(true);
  });

  it("names a near-miss heading", () => {
    const found = failuresOf(RUST().replace("#Ownership Foundations", "#Ownership Foundatons"));
    expect(found.some((p) => p.endsWith(', did you mean "Ownership Foundations"?'))).toBe(true);
  });

  it("says when a grounding document fails the corpus contract", () => {
    const { curricula, corpus } = tree();
    writeFileSync(join(corpus, "cs", "ownership.md"), "## Ownership Foundations\nprose\n");
    const found = validateCurricula(curricula, corpus).failures.flatMap((f) => f.problems);
    expect(found.some((p) => p.includes("does not satisfy the corpus contract"))).toBe(true);
  });

  it("is clean with no curricula at all", () => {
    const root = mkdtempSync(join(tmpdir(), "frog-curricula-"));
    mkdirSync(join(root, "curricula"));
    expect(validateCurricula(join(root, "curricula"), join(root, "corpus"))).toEqual({
      passed: [],
      failures: [],
    });
  });
});

describe("the near-miss match, as Python's difflib", () => {
  it.each([
    ["Ownership Foundations", "Ownership Foundatons", 0.975609756097561],
    ["abcd", "bcda", 0.75],
    ["Photometric Fundamentals", "Photometric Fundamentals: Flux", 0.8888888888888888],
    ["Telescope Optics", "Spectroscopy", 0.35714285714285715],
    ["aaab", "abaa", 0.5],
    ["", "", 1],
  ])("scores %j against %j as SequenceMatcher does", (a, b, ratio) => {
    expect(similarity(a, b)).toBeCloseTo(ratio, 12);
  });

  it("picks the best above the cutoff, a tie going to the later string", () => {
    expect(closestMatch("Ownership Foundatons", ["Ownership Foundations", "Ownership", "Borrowing"])).toBe(
      "Ownership Foundations",
    );
    expect(closestMatch("ab", ["ac", "ad"], 0.4)).toBe("ad");
    expect(closestMatch("Snapshot", ["Phantom reads", "Write skew"])).toBeNull();
  });
});

async function counts(): Promise<[number, number]> {
  const [c] = await db.select({ n: count() }).from(curriculum);
  const [s] = await db.select({ n: count() }).from(curriculumSubtopic);
  return [c?.n ?? 0, s?.n ?? 0];
}

describe("ingesting curricula", () => {
  it("writes once, and a re-run is a no-op", async () => {
    const { curricula, corpus } = tree();
    expect(await ingestCurricula(db, curricula, corpus)).toMatchObject({ ingested: 1, unchanged: 0 });
    expect(await counts()).toEqual([1, 2]);
    expect(await ingestCurricula(db, curricula, corpus)).toMatchObject({ ingested: 0, unchanged: 1 });
    expect(await counts()).toEqual([1, 2]);
    const [row] = await db.select().from(curriculum);
    expect(row).toMatchObject({ topicName: "Rust", scope: "topic", sourcePath: "rust/curriculum.md" });
  });

  it("replaces a revised curriculum's subtopics, keeping its row", async () => {
    const { curricula, corpus } = tree();
    await ingestCurricula(db, curricula, corpus);
    const [first] = await db.select({ id: curriculum.id }).from(curriculum);

    writeFileSync(
      join(curricula, "rust", "curriculum.md"),
      `---
topic: Rust
description: Now with fewer subtopics
scope: one_shot
subtopics:
  - title: Ownership
    description: One owner per value
    prerequisites: []
    tiers:
      beginner:
        target_cards: 6
        card_types: { prose: 6 }
        grounding: ["cs/ownership.md#Ownership Foundations"]
---
`,
    );
    expect(await ingestCurricula(db, curricula, corpus)).toMatchObject({ ingested: 1 });

    const [again] = await db.select().from(curriculum);
    expect(again).toMatchObject({
      id: first?.id,
      description: "Now with fewer subtopics",
      scope: "one_shot",
    });
    expect(await counts()).toEqual([1, 1]);
    const [remaining] = await db.select().from(curriculumSubtopic).orderBy(asc(curriculumSubtopic.ordinal));
    expect(remaining).toMatchObject({ title: "Ownership", sourcePaths: ["cs/ownership.md"] });
    // The declared scope rides in the tier JSON, which the projection reads into `subtopic.grounding_refs`.
    expect(remaining?.tiers).toEqual({
      beginner: {
        target_cards: 6,
        card_types: { prose: 6 },
        grounding: ["cs/ownership.md#Ownership Foundations"],
      },
    });
  });

  it("reports an invalid curriculum and writes only the valid ones", async () => {
    const { curricula, corpus } = tree();
    mkdirSync(join(curricula, "broken"));
    writeFileSync(
      join(curricula, "broken", "curriculum.md"),
      "---\ntopic: Broken\ndescription: d\nscope: topic\nsubtopics: []\n---\n",
    );
    expect(await ingestCurricula(db, curricula, corpus)).toMatchObject({ ingested: 1, failed: 1 });
    expect(await counts()).toEqual([1, 2]);
  });
});
