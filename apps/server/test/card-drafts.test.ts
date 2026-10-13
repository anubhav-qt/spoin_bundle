import { describe, expect, test } from "vitest";
import { draftProblems, PROSE_MAX } from "../src/agents/tiers.ts";

/*
 * The faults code refuses in a card draft (task 0045), the old gate's included: a wall of prose,
 * code in a topic with none, an emoji in a diagram, and a correction note left in the body.
 */

const draft = (body: string) => ({
  title: "Why your cache lies",
  canonical_title: "Cache invalidation",
  summary: "The hardest part of caching isn't the cache.",
  body,
  passages: [1],
});

const words = (count: number) => "You read the cache first, then the database. ".repeat(count).trim();

describe("a card draft", () => {
  test("passes when it is one idea in plain prose", () => {
    expect(draftProblems(draft(words(10)), 1, false)).toEqual([]);
  });

  test("is refused as a wall of prose, but its code and diagrams don't count", () => {
    const long = words(40);
    expect(long.length).toBeGreaterThan(PROSE_MAX);
    expect(draftProblems(draft(long), 1, true).join()).toContain("its prose outside code and diagrams");

    const fence = `\`\`\`python\n${"x = 1\n".repeat(150)}\`\`\``;
    expect(draftProblems(draft(`${words(10)}\n\n${fence}`), 1, true)).toEqual([]);
  });

  test("carries no code block in a tier with no code cards, though a diagram is fine", () => {
    const code = `${words(10)}\n\n\`\`\`bash\nredis-cli FLUSHALL\n\`\`\``;
    expect(draftProblems(draft(code), 1, false).join()).toContain("this tier has no code cards");
    expect(draftProblems(draft(code), 1, true)).toEqual([]);

    const diagram = `${words(10)}\n\n\`\`\`mermaid\nflowchart TD\n  A[App] --> C[Cache]\n\`\`\``;
    expect(draftProblems(draft(diagram), 1, false)).toEqual([]);
  });

  test("is refused for an emoji in a diagram", () => {
    const diagram = `${words(10)}\n\n\`\`\`mermaid\nflowchart TD\n  A[App 🚀] --> C[Cache]\n\`\`\``;
    expect(draftProblems(draft(diagram), 1, false)).toEqual(["a mermaid block has an emoji"]);
  });

  test("is refused for a correction note left in its body", () => {
    const noted = `${words(10)}\n\n**Correction:** the TTL is per key, not per cache.`;
    expect(draftProblems(draft(noted), 1, false).join()).toContain("carries a correction note");
  });
});
