import { createHash } from "node:crypto";
import { readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { parse } from "yaml";

/*
 * What the three delivery contracts (corpus documents, curricula, image manifests) share:
 * a file that opens with YAML front matter, identified by its path and changed when its
 * bytes change. Each contract reports every problem it finds rather than the first,
 * because an authored tree drifts in batches.
 */

/**
 * A leading `---` line, a YAML block, a closing `---` line. Anchored at the start of the
 * file: a `---` later on is a horizontal rule in the prose, not a delimiter.
 */
const FRONT_MATTER = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*\r?\n?([\s\S]*)$/;

/**
 * sha256 of the file as delivered, hashed as bytes before decoding so a re-encoding that
 * changes no characters still reads as a change. A hash rather than a version field in
 * front matter, because a version bump can be forgotten and stale rows then survive a
 * revision invisibly (ADR-0088).
 */
export function contentHash(raw: Uint8Array | string): string {
  return createHash("sha256").update(raw).digest("hex");
}

/** A value from the file, quoted back in a problem line. */
export const show = (value: unknown): string => (value === undefined ? "nothing" : JSON.stringify(value));

/** Python's `len()`: code points, so a limit an author counts is the limit enforced. */
export const charCount = (text: string): number => [...text].length;

export const isMapping = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * The front matter as a mapping and the text after it, or null with the reason pushed
 * onto `problems`. YAML 1.2, so a duplicated key is an error rather than a silent
 * last-one-wins, and `2026-08-01` stays a string.
 */
export function readFrontMatter(
  raw: Uint8Array,
  problems: string[],
): { front: Record<string, unknown>; body: string } | null {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
  } catch (err) {
    problems.push(`not valid UTF-8: ${(err as Error).message}`);
    return null;
  }
  const match = FRONT_MATTER.exec(text);
  if (!match) {
    problems.push("no YAML front matter (file must open with a `---` line)");
    return null;
  }
  let loaded: unknown;
  try {
    loaded = parse(match[1] ?? "");
  } catch (err) {
    problems.push(`front matter is not valid YAML: ${(err as Error).message.split("\n")[0]}`);
    return null;
  }
  if (!isMapping(loaded)) {
    problems.push("front matter is not a mapping");
    return null;
  }
  return { front: loaded, body: match[2] ?? "" };
}

/**
 * A file's identity within its tree: its path, POSIX-separated. This is a database key,
 * and the tree is written on one OS and ingested on another, so `a\b.md` and `a/b.md`
 * must not become two rows.
 */
export const posixPath = (root: string, path: string): string => relative(root, path).split(sep).join("/");

/** Path order by component, as Python sorts paths, so a run's report diffs against the last one. */
const byComponents = (a: string, b: string): number => {
  const pa = a.split("/");
  const pb = b.split("/");
  for (let i = 0; i < Math.min(pa.length, pb.length); i++) {
    const x = pa[i] as string;
    const y = pb[i] as string;
    if (x !== y) return x < y ? -1 : 1;
  }
  return pa.length - pb.length;
};

/** Every `.md` file under `root` as `[posix path, absolute path]`, in a stable order. */
export function markdownFiles(root: string): [string, string][] {
  return readdirSync(root, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
    .map((entry): [string, string] => {
      const full = join(entry.parentPath, entry.name);
      return [posixPath(root, full), full];
    })
    .sort(([a], [b]) => byComponents(a, b));
}
