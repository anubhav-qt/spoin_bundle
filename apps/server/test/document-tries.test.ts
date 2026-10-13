import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "vitest";
import { lastTry, mergeTry } from "../src/agents/documents.ts";

/*
 * A document writer's tries (task 0045): each is kept, and the next call sends only the sections
 * that change, so a document refused for one section is never written again whole.
 */

const fields = {
  title: "Caching",
  source: "https://example.org/caching",
  source_date: "2026-01",
  tags: ["caching"],
  knowledge_kind: "empirical" as const,
  source_tier: "official_documentation" as const,
};

const section = (heading: string, text: string) => ({ heading, text });

describe("a document's tries", () => {
  test("a section replaces its namesake where it stood, a new one goes last, and drop takes one out", () => {
    const first = mergeTry(null, {
      ...fields,
      sections: [section("Cache-aside", "a"), section("Write-through", "b"), section("Eviction", "c")],
    });
    const second = mergeTry(first, {
      ...fields,
      title: "Caching, revised",
      sections: [section("Write-through", "b, shorter"), section("TTLs", "d")],
      drop: ["Eviction"],
    });
    expect(second.title).toBe("Caching, revised");
    expect(second.sections).toEqual([
      section("Cache-aside", "a"),
      section("Write-through", "b, shorter"),
      section("TTLs", "d"),
    ]);
  });

  test("a document written before tries were kept starts from its written sections", () => {
    const directory = mkdtempSync(join(tmpdir(), "spoin-try-"));
    const full = join(directory, "caching.md");
    const body = (letter: string) => `${letter} `.repeat(600).trim();
    const written = [
      "---",
      'title: "Caching"',
      'kind: "topic_source"',
      'category: "computer-science-engineering"',
      'scope: "topic"',
      'source: "https://example.org/caching"',
      'source_date: "2026-01"',
      'topic_tags: ["caching"]',
      "---",
      "",
      "## Cache-aside",
      "",
      body("a"),
      "",
      "## Eviction",
      "",
      body("c"),
      "",
    ].join("\n");
    writeFileSync(full, written);

    const last = lastTry(`${full}.try.json`, full, "computer-science-engineering/caching.md");
    expect(last?.sections.map((one) => one.heading)).toEqual(["Cache-aside", "Eviction"]);

    const merged = mergeTry(last, { ...fields, sections: [section("Eviction", "c, revised")] });
    expect(merged.sections).toEqual([section("Cache-aside", body("a")), section("Eviction", "c, revised")]);
  });
});
