import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, test } from "vitest";

/*
 * frog is a library the server imports, never the reverse (ADR-0087), and it does not
 * import the shared wire contract either: the values it shares with the app (scopes,
 * tiers, card types) are mirrored by value and kept equal by a server test. Enforced
 * twice: a Biome `noRestrictedImports` override in the editor, and this walk in CI.
 */

const SRC = resolve(import.meta.dirname, "../src");
const FORBIDDEN = /^@spoin\/(server|shared)(\/|$)/;
const IMPORT = /(?:import|export)\s[^"']*?from\s*["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\)/g;

describe("architecture", () => {
  test("frog imports neither the server nor the shared contract (ADR-0087)", () => {
    const files = readdirSync(SRC, { recursive: true, encoding: "utf8" }).filter((f) => f.endsWith(".ts"));
    // The walk must actually be looking at something.
    expect(files.length).toBeGreaterThan(10);
    const offenders = files.flatMap((file) =>
      [...readFileSync(join(SRC, file), "utf8").matchAll(IMPORT)]
        .map((m) => (m[1] ?? m[2]) as string)
        .filter((spec) => FORBIDDEN.test(spec))
        .map((spec) => `${file}: ${spec}`),
    );
    expect(offenders).toEqual([]);
  });
});
