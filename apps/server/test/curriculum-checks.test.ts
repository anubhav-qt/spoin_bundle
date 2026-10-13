import { HashEmbedder } from "@spoin/frog/embeddings";
import { describe, expect, test } from "vitest";
import type { AgentDeps } from "../src/agents/context.ts";
import { curriculumProblems } from "../src/agents/curriculum.ts";
import type { Curriculum } from "../src/harness/schemas.ts";
import { loadPrompts } from "../src/prompts.ts";
import { useCorpus } from "./corpus.ts";
import { makeTopic } from "./fixtures.ts";
import { deps } from "./helpers.ts";

/*
 * The curriculum rules code checks (task 0045): every tier's fixed card mix (the owner, 2026-10-13),
 * and one tier a subtopic for a scope without tiers (ADR-0106).
 */

const universe = useCorpus();
const agentDeps = {
  db: deps.db,
  universe,
  prompts: loadPrompts(),
  embedder: new HashEmbedder(),
} as unknown as AgentDeps;

const grounding = [
  "cs/caching.md#One",
  "cs/caching.md#Two",
  "cs/caching.md#Three",
  "cs/caching.md#Four",
  "cs/caching.md#Five",
];

function curriculumOf(topicId: string, tiers: Curriculum["subtopics"][number]["tiers"]): Curriculum {
  return {
    topic: topicId,
    description: "Where a copy of the data lives.",
    subtopics: [{ title: "Caching", description: "Copies, and when they lie.", prerequisites: [], tiers }],
    reasoning: "One subtopic.",
  };
}

describe("a curriculum's checks", () => {
  test("a tier's card types are the fixed mix, with prose's share split any way into code", async () => {
    const { topic } = await makeTopic({ cardsPerSubtopic: 0 });
    const plan = (cardTypes: Record<string, number>) => ({ targetCards: 10, cardTypes, grounding });

    const off = await curriculumProblems(
      agentDeps,
      topic,
      curriculumOf(topic.id, { beginner: plan({ ascii: 4, diagram: 2, prose: 3, comparison: 1 }) }),
    );
    expect(off).toContain(
      'subtopic "Caching", tier beginner: a tier of 10 cards is ascii 5, diagram 2, comparison 1, and 2 prose (a code subject may make any of those code cards)',
    );

    const coded = await curriculumProblems(
      agentDeps,
      topic,
      curriculumOf(topic.id, { beginner: plan({ ascii: 5, diagram: 2, prose: 0, code: 2, comparison: 1 }) }),
    );
    expect(coded.some((problem) => problem.includes("a tier of"))).toBe(false);
  });

  test("a survey or a one-shot gives each subtopic only its beginner tier", async () => {
    const { topic } = await makeTopic({ cardsPerSubtopic: 0, scope: "survey" });
    const plan = { targetCards: 5, cardTypes: { prose: 1, code: 4 }, grounding };

    const problems = await curriculumProblems(
      agentDeps,
      topic,
      curriculumOf(topic.id, { beginner: plan, advanced: plan }),
    );
    expect(problems).toContain(
      'subtopic "Caching", tier advanced: a survey has no tiers; give each subtopic only `beginner`',
    );
    expect(problems.some((problem) => problem.includes("tier beginner: a survey"))).toBe(false);
  });
});
