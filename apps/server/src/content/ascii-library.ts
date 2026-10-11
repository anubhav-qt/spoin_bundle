import { readFileSync } from "node:fs";

/*
 * The curated ASCII art library (ADR-0068): hand-titled entries, each verified to fit
 * the phone's column budget. ADR-0079 keeps gags only, so only that file is loaded.
 * The file sits beside this module in the source tree and beside the bundle in
 * `dist/` (build.mjs copies it), so the same relative URL finds it in both.
 */

export const ASCII_MAX_WIDTH = 40;

export interface AsciiLibraryEntry {
  id: string;
  title: string;
  category: string;
  subcategory: string;
  art: string;
}

/** A stable, machine-written header, then a fenced block: verified against every entry. */
const ENTRY =
  /=== ID: (?<id>\S+) \| TITLE: (?<title>.*?) \| ARTIST: .*? \| CATEGORY: (?<category>.*?) \| SUBCATEGORY: (?<subcategory>.*?) \| SIZE: .*? ===\n```\n(?<art>[\s\S]*?)```/g;

let library: Map<string, AsciiLibraryEntry> | undefined;

/** Parsed once per process. The file is committed, so a missing one is a build bug and throws. */
export function loadLibrary(): Map<string, AsciiLibraryEntry> {
  if (library) return library;
  const text = readFileSync(new URL("./ascii-library/use_for_gags.txt", import.meta.url), "utf8");
  library = new Map();
  for (const m of text.replaceAll("\r\n", "\n").matchAll(ENTRY)) {
    const { id, title, category, subcategory, art } = m.groups as Record<string, string>;
    library.set(id as string, {
      id: id as string,
      title: (title as string).trim(),
      category: (category as string).trim(),
      subcategory: (subcategory as string).trim(),
      art: (art as string).replace(/\n+$/, ""),
    });
  }
  return library;
}

/** One entry by id, or null when the id is not in the library. */
export const entryById = (id: string): AsciiLibraryEntry | null => loadLibrary().get(id) ?? null;
