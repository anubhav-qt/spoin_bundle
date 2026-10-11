import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { describe, expect, expectTypeOf, test } from "vitest";
import type { AskChat } from "../src/ask/chat.ts";
import type { Grader } from "../src/quiz/grader.ts";

/*
 * Hard rules enforced twice: a Biome `noRestrictedImports` override stops a stray
 * import in the editor, and this walk catches it in CI even if lint is bypassed. This
 * one follows imports transitively, so a helper that reaches a model is caught too.
 */

const SRC = resolve(import.meta.dirname, "../src");

/** Hard rule 1: a swipe is ~50ms and a model call seconds; they never share a code path. */
const READ_PATH = ["feed", "engagement", "cards", "routes/feed.ts", "routes/engagement.ts"];

const MODEL_CLIENTS = [
  /^@google\/genai/,
  /^@google\/generative-ai/,
  /^openai($|\/)/,
  /^@anthropic-ai\//,
  /^ai$/,
  /^@ai-sdk\//,
  /^@mariozechner\/pi-/,
  /^@spoin\/pi-/,
];

const filesUnder = (path: string): string[] => {
  const full = join(SRC, path);
  if (full.endsWith(".ts")) return [full];
  return readdirSync(full, { recursive: true, encoding: "utf8" })
    .filter((f) => f.endsWith(".ts"))
    .map((f) => join(full, f));
};

const IMPORT =
  /(?:import|export)\s[^"']*?from\s*["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\)|import\s+["']([^"']+)["']/g;

/** Every bare specifier reachable from `roots`, with the file that imports it. */
function reach(roots: string[]) {
  const seen = new Set<string>();
  const bare: { spec: string; from: string }[] = [];
  const stack = [...roots];
  while (stack.length > 0) {
    const file = stack.pop() as string;
    if (seen.has(file)) continue;
    seen.add(file);
    for (const m of readFileSync(file, "utf8").matchAll(IMPORT)) {
      const spec = (m[1] ?? m[2] ?? m[3]) as string;
      if (spec.startsWith(".")) {
        const target = resolve(dirname(file), spec);
        if (target.endsWith(".ts")) stack.push(target);
      } else bare.push({ spec, from: file.slice(SRC.length + 1) });
    }
  }
  return { files: seen, bare };
}

/**
 * The methods of `T` whose first parameter is not a collection. ADR-0005: the free tiers
 * meter requests, not tokens, so every model-facing method takes a batch.
 */
type SingleItem<T> = {
  [K in keyof T]: T[K] extends (...args: infer P) => unknown
    ? P[0] extends readonly unknown[]
      ? never
      : K
    : never;
}[keyof T];

describe("architecture", () => {
  test("no model client anywhere the feed read path reaches (hard rule 1)", () => {
    const { files, bare } = reach(READ_PATH.flatMap(filesUnder));
    // The walk must actually be looking at something.
    expect(files.size).toBeGreaterThan(10);
    const offenders = bare.filter(({ spec }) => MODEL_CLIENTS.some((re) => re.test(spec)));
    expect(offenders, "The feed read path must never touch a model: precompute a column instead.").toEqual(
      [],
    );
  });

  test("every model-facing method takes a collection (ADR-0005)", () => {
    // Checked by the typechecker: an offending method's name shows up in the error.
    expectTypeOf<SingleItem<Grader>>().toEqualTypeOf<never>();
    // ADR-0077's one sanctioned exception: a streamed AskAI turn is one reader at their own time.
    expectTypeOf<SingleItem<AskChat>>().toEqualTypeOf<"turn">();
  });
});
