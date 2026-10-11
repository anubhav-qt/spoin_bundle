import type { ParsedDocument } from "./contract.ts";

/*
 * A parsed document becomes the text that is embedded and stored. Section-level: one
 * `##` section, one chunk. Sections stay chunk-sized because the contract enforces
 * `MAX_SECTION_CHARS`: measured over 358 real sections, 17% ran over 512 tokens when it
 * was only a guideline (task 0038, Phase 2).
 */

/**
 * The exact string both embedded and stored (rag-design-space 3.8): the document title
 * and section heading, a blank line, then the author's prose.
 *
 * A section is retrieved without its neighbours, and dense prose routinely never names
 * its own subject: a chunk on why `z-index` fails inside a transformed ancestor says
 * nothing about CSS. That makes the vector vague and the chunk unattributable, and the
 * header fixes both for free.
 *
 * Stored, not merely embedded (owner's decision, 2026-09-05): embedding a header the
 * stored text lacks makes the vector and the text describe different strings, the
 * silent divergence ADR-0092 was written about.
 */
export function contextualText(document: ParsedDocument, heading: string, text: string): string {
  // A heading that restates the title would spend prompt tokens saying it twice.
  const header =
    heading.trim().toLowerCase() === document.title.trim().toLowerCase()
      ? document.title
      : `${document.title} — ${heading}`;
  return `${header}\n\n${text}`;
}

/** Every chunk of one document, in order: `ordinal` makes a chunk citable as "part 3 of". */
export function chunkTexts(document: ParsedDocument): string[] {
  return document.sections.map((s) => contextualText(document, s.heading, s.text));
}
