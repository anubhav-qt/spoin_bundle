import { describe, expect, it } from "vitest";
import { chunkTexts, contextualText } from "../src/ingest/chunking.ts";
import { type ParsedDocument, parseDocument } from "../src/ingest/contract.ts";

/*
 * Contextual chunk headers (rag-design-space 3.8). A missing header does not fail; it
 * makes a chunk harder to find and impossible to attribute, which no one notices.
 */

const VALID = `---
title: CSS layout and stacking contexts
kind: topic_source
category: computer science
scope: survey
source: https://www.w3.org/TR/css-position-3/
topic_tags:
  - css
---

## The stacking context trap

The root cause is that z-index does not operate globally across the document.

## CSS layout and stacking contexts

A section whose heading restates the document title.
`;

const document = parseDocument("x.md", new TextEncoder().encode(VALID)).document as ParsedDocument;

describe("chunking", () => {
  it("heads a chunk with the document and the section", () => {
    // The prose never says CSS or which document it came from: the case the header is for.
    const [first] = chunkTexts(document);
    expect(first?.startsWith("CSS layout and stacking contexts — The stacking context trap\n\n")).toBe(true);
    expect(first).toContain("z-index does not operate globally");
  });

  it("does not repeat a heading that restates the title", () => {
    const second = chunkTexts(document)[1] as string;
    expect(second.startsWith("CSS layout and stacking contexts\n\n")).toBe(true);
    expect(second.split("\n\n")[0]).not.toContain("—");
  });

  it("stores the header as part of the text (owner's decision, 2026-09-05)", () => {
    expect(contextualText(document, "The stacking context trap", "Body prose.")).toBe(
      "CSS layout and stacking contexts — The stacking context trap\n\nBody prose.",
    );
  });

  it("makes one chunk per section, in document order", () => {
    expect(chunkTexts(document)).toHaveLength(document.sections.length);
    expect(document.sections).toHaveLength(2);
  });
});
