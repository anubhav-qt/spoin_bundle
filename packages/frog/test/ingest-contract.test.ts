import { describe, expect, it } from "vitest";
import { MAX_SECTION_CHARS, parseDocument } from "../src/ingest/contract.ts";

/*
 * What the ingester accepts, and what it hands back as a work item. Pure: no database,
 * no model. Every failing case here has happened in a real delivery (task 0038, Phase 2),
 * which is the argument for validating rather than trusting the contract document.
 */

const VALID = `---
title: MVCC and transaction isolation in PostgreSQL
kind: topic_source
category: Computer Science
sub_category: Databases
scope: topic
source: https://www.postgresql.org/docs/17/mvcc.html
source_date: 2026-08-01
topic_tags:
  - PostgreSQL
  - Distributed Systems
---

## Snapshot isolation

Each transaction sees a snapshot taken at its start.

## What REPEATABLE READ guarantees

Postgres also prevents phantom reads.
`;

const CANON = `---
title: Card anatomy
kind: spoin_canon
source: Spoin docs/architecture/content-model.md
topic_tags:
  - spoin canon
---

## The card as the atomic unit

A card is a self-contained explanation of one idea.
`;

const bytes = (text: string) => new TextEncoder().encode(text);
const parse = (text: string, path = "x.md") => parseDocument(path, bytes(text));
const problems = (text: string) => parse(text).errors.problems;
const BODY = "Each transaction sees a snapshot taken at its start.";

describe("the corpus contract", () => {
  it("parses a valid topic_source document", () => {
    const { document, errors } = parse(VALID, "cs/pg/mvcc.md");
    expect(errors.problems).toEqual([]);
    expect(document).toMatchObject({ kind: "topic_source", scope: "topic", sourcePath: "cs/pg/mvcc.md" });
    expect(document?.sections.map((s) => s.heading)).toEqual([
      "Snapshot isolation",
      "What REPEATABLE READ guarantees",
    ]);
  });

  it("puts category, sub-category and tags through one normalizer (ADR-0091)", () => {
    expect(parse(VALID).document).toMatchObject({
      category: "computer science",
      subCategory: "databases",
      topicTags: ["postgresql", "distributed systems"],
    });
  });

  it("accepts one_shot, the third scope (ADR-0106)", () => {
    expect(parse(VALID.replace("scope: topic", "scope: one_shot")).document?.scope).toBe("one_shot");
  });

  it("needs no hierarchy on canon, which the CHECK exempts", () => {
    const { document, errors } = parse(CANON, "_canon/card-anatomy.md");
    expect(errors.problems).toEqual([]);
    expect(document).toMatchObject({ category: null, scope: null, sourceDate: null });
  });

  it("fails canon that carries a category: the exemption runs both ways", () => {
    const raw = CANON.replace("kind: spoin_canon", "kind: spoin_canon\ncategory: computer science");
    expect(parse(raw).document).toBeNull();
    expect(problems(raw).some((p) => p.includes("outside the subject hierarchy"))).toBe(true);
  });

  it("names the file and the field when `title` is missing", () => {
    const { document, errors } = parse(
      VALID.replace("title: MVCC and transaction isolation in PostgreSQL\n", ""),
      "cs/pg/mvcc.md",
    );
    expect(document).toBeNull();
    expect(errors.sourcePath).toBe("cs/pg/mvcc.md");
    expect(errors.problems.some((p) => p.includes("`title` is missing"))).toBe(true);
  });

  it("reports every problem, not just the first", () => {
    const found = problems(
      VALID.replace("title: MVCC and transaction isolation in PostgreSQL\n", "").replace(
        "scope: topic\n",
        "",
      ),
    );
    expect(found.length).toBeGreaterThanOrEqual(2);
    expect(found.some((p) => p.includes("title"))).toBe(true);
    expect(found.some((p) => p.includes("scope"))).toBe(true);
  });

  it("fails a mistyped kind rather than making a silent third kind", () => {
    const found = problems(VALID.replace("kind: topic_source", "kind: topic-source"));
    expect(found.some((p) => p.includes("spoin_canon"))).toBe(true);
  });

  it.each([
    ["2026-08-01", "2026-08-01T00:00:00.000Z"],
    ["2026-08", "2026-08-01T00:00:00.000Z"],
    ["2024", "2024-01-01T00:00:00.000Z"],
    ['"2024"', "2024-01-01T00:00:00.000Z"],
  ])("widens source_date %s to the start of its period", (written, expected) => {
    const { document, errors } = parse(VALID.replace("source_date: 2026-08-01", `source_date: ${written}`));
    expect(errors.problems).toEqual([]);
    expect(document?.sourceDate?.toISOString()).toBe(expected);
  });

  it.each(["last summer", "2024-02-30", "2024-13"])("fails source_date %s", (written) => {
    const found = problems(VALID.replace("source_date: 2026-08-01", `source_date: ${written}`));
    expect(found.some((p) => p.includes("source_date"))).toBe(true);
  });

  it("fails prose before the first heading (owner's decision, 2026-09-05)", () => {
    const raw = VALID.replace(
      "\n## Snapshot isolation",
      "\nThis document surveys isolation.\n\n## Snapshot isolation",
    );
    expect(problems(raw).some((p) => p.includes("before the first `##`"))).toBe(true);
  });

  it("lets an H1 line through: it repeats the title every chunk's header carries", () => {
    const raw = VALID.replace("\n## Snapshot isolation", "\n# MVCC in PostgreSQL\n\n## Snapshot isolation");
    expect(problems(raw)).toEqual([]);
  });

  it("fails a document with no sections", () => {
    expect(
      problems(VALID.replaceAll("## ", "Not a heading: ")).some((p) => p.includes("`##` sections")),
    ).toBe(true);
  });

  it("fails a file with no front matter", () => {
    const { document, errors } = parseDocument("x.md", bytes("## Just a heading\n\nBody.\n"));
    expect(document).toBeNull();
    expect(errors.problems.some((p) => p.includes("front matter"))).toBe(true);
  });

  it("fails bytes that are not UTF-8", () => {
    const raw = new Uint8Array([...bytes("---\ntitle: "), 0xff, 0xfe, ...bytes("\n---\n")]);
    expect(parseDocument("x.md", raw).errors.problems[0]).toMatch(/^not valid UTF-8/);
  });

  it("changes the content hash when the file changes", () => {
    const first = parse(VALID).document;
    const second = parse(VALID.replace("Postgres also", "PostgreSQL also")).document;
    expect(first?.contentHash).toHaveLength(64);
    expect(first?.contentHash).not.toBe(second?.contentHash);
  });

  it("fails an oversized section, naming it (owner's decision, 2026-09-05)", () => {
    const found = problems(VALID.replace(BODY, "word ".repeat(500)));
    expect(found.some((p) => p.includes("over the 2200 limit") && p.includes("Snapshot isolation"))).toBe(
      true,
    );
  });

  it("holds the size limit inclusive, at exactly 2200 characters", () => {
    expect(problems(VALID.replace(BODY, "a".repeat(MAX_SECTION_CHARS)))).toEqual([]);
    expect(problems(VALID.replace(BODY, "a".repeat(MAX_SECTION_CHARS + 1)))).not.toEqual([]);
  });

  it("counts characters as an author does, not UTF-16 units", () => {
    // An emoji is one character and two UTF-16 units.
    expect(problems(VALID.replace(BODY, "🌌".repeat(MAX_SECTION_CHARS)))).toEqual([]);
  });
});
