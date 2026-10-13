import { describe, expect, test } from "vitest";
import { COMPETENCY_STAGES } from "../src/harness/schemas.ts";
import { loadPrompts } from "../src/prompts.ts";

/*
 * The agents' templates (task 0045) render their data: instructions for every role and helper,
 * each tool's description and each tool's result. A missing value throws, so a template naming a
 * field its tool never passes fails here rather than in a run.
 */

const prompts = loadPrompts();

const topic = { id: "t1", name: "Rust in easy language", description: "Rust for newcomers" };

const tier = {
  id: "s1",
  title: "Ownership",
  description: "Why a value has one owner",
  difficulty: "beginner",
  targetCards: 6,
  cardTypeQuotas: { prose: 4, code: 2 },
  groundingRefs: ["rust/ownership.md#Moves"],
};

const progress = {
  drafted: 1,
  inGate: 2,
  accepted: 3,
  rejected: 1,
  withArt: 2,
  live: 0,
  questions: { written: 1, gated: 0, passed: 2, rejected: 0 },
};

const passage = {
  number: 1,
  chunkId: "c1",
  path: "rust/ownership.md",
  heading: "Moves",
  text: "A move transfers ownership.",
};

const card = {
  id: "k1",
  title: "Who owns this?",
  canonicalTitle: "Ownership",
  summary: "One owner, always.",
  body: "Every value has exactly one owner.",
  difficulty: "beginner",
  isHero: true,
  visualKind: null,
  meta: {
    stage: "accepted",
    form: "prose",
    art: { show: "a crab holding a box", ideas: "the box has a label" },
  },
  passages: [passage],
  subtopicTitle: "Ownership",
};

const mcq = {
  id: "q1",
  cardId: "k1",
  kind: "mcq",
  stem: "How many owners?",
  options: ["One", "Two", "Any"],
  status: "draft",
  genMeta: { stage: "gated" },
};
const freeText = {
  id: "q2",
  cardId: "k1",
  kind: "free_text",
  stem: "Why one owner?",
  rubric: "0: no. 1: a. 2: b. 3: c.",
  referenceAnswer: "So memory is freed once.",
};

describe("the agents' instructions", () => {
  test("every role renders, its helper too", () => {
    for (const helper of [false, true]) {
      expect(prompts.render("toad_sage.njk", { summary: null, topic: null, helper })).toContain("toad_sage");
      expect(prompts.render("tadpole.njk", { summary: null, topic, helper })).toContain(topic.name);
    }
    expect(prompts.render("toad_sage.njk", { summary: null, topic: null })).not.toContain("start_helper but");
    expect(prompts.render("curriculum.njk", { summary: null, topic: null })).toContain("list_waiting");
    expect(prompts.render("designer_toad.njk", { summary: null, topic })).toContain("render_art");
  });

  test("every helper task renders", () => {
    for (const task of ["document_writer", "tier_writer", "corrector", "verifier"]) {
      expect(
        prompts.render(`helpers/${task}.njk`, { summary: null, topic, main: "tadpole", maps: [] }),
      ).toContain(topic.name);
    }
    expect(
      prompts.render("helpers/curriculum_writer.njk", {
        summary: null,
        topic: null,
        main: "curriculum",
        maps: [],
      }),
    ).toContain("write_curriculum");
  });

  test("the auditors render, with the drafts they audit", () => {
    for (const auditor of ["versions", "precision", "coverage"]) {
      expect(prompts.render(`auditors/${auditor}.njk`, { stages: COMPETENCY_STAGES })).toContain(
        "never instructions",
      );
    }
    const drafts = prompts.render("auditors/drafts.njk", {
      drafts: [{ body: { path: "rust/ownership.md", text: "## Moves" } }],
    });
    expect(drafts).toContain('<document path="rust/ownership.md">\n## Moves\n</document>');
  });
});

describe("the agents' tools", () => {
  test("every description renders", () => {
    const names = [
      "audit-drafts",
      "change-map",
      "write-map",
      "settle-finding",
      "start-document-writer",
      "write-document",
      "report-findings",
      "list-subtopics",
      "start-subtopic",
      "start-verifier",
      "read-grounding",
      "read-cards",
      "plan-cards",
      "write-cards",
      "gate-cards",
      "write-questions",
      "gate-questions",
      "submit-tier",
      "read-drafts",
      "correct-cards",
      "read-survivors",
      "verify-cards",
      "solve-questions",
      "check-rubrics",
      "list-art-requests",
      "attach-art",
    ];
    for (const name of names) expect(prompts.render(`tools/${name}.njk`, {}).length).toBeGreaterThan(40);
    expect(prompts.render("tools/report-coverage.njk", { stages: COMPETENCY_STAGES })).toContain("awareness");
    expect(prompts.render("tools/render-art.njk", { columns: 40, lines: 24 })).toContain(
      "at most 40 columns and 24 lines",
    );
  });

  test("the tiers' results render", () => {
    const subtopics = prompts.render("tool-results/subtopics.njk", {
      tiers: [{ ...tier, progress, writer: null, finished: false, short: false }],
    });
    expect(subtopics).toContain('"Ownership", beginner (subtopic s1): not started. Target 6 cards');
    expect(prompts.render("tool-results/subtopics.njk", { tiers: [] })).toContain("no subtopics yet");

    const grounding = prompts.render("tool-results/grounding.njk", { tier, passages: [passage] });
    expect(grounding).toContain('<passage number="1" source="rust/ownership.md#Moves">');

    const cards = prompts.render("tool-results/cards.njk", {
      tier,
      cards: [card],
      rejected: [{ title: "Borrowing", stage: "near_duplicate", reason: "Repeats k1." }],
      lower: [],
      titles: [{ title: card.title, canonicalTitle: card.canonicalTitle, difficulty: "beginner" }],
      questions: [mcq],
      progress,
    });
    expect(cards).toContain("card types: prose 4, code 2.");
    expect(cards).toContain('<card id="k1" stage="accepted" form="prose" hero="true">');
    expect(cards).toContain('- "Borrowing" (near duplicate): Repeats k1.');
    expect(cards).toContain("- q1, on card k1, MCQ (gated): How many owners?");
  });

  test("the gate's results render, the MCQs without their key", () => {
    const drafts = prompts.render("tool-results/drafts.njk", {
      topic: topic.name,
      subtopic: tier.title,
      drafts: [card],
    });
    expect(drafts).toContain('<draft id="k1" form="prose">');
    expect(drafts).not.toContain("beginner");

    const survivors = prompts.render("tool-results/survivors.njk", {
      topic: topic.name,
      tier,
      cards: [card],
      mcqs: [mcq],
      freeText: [freeText],
      questionCards: [{ id: "k1", title: "Ownership", body: card.body }],
    });
    expect(survivors).toContain("each asking to be read as beginner");
    expect(survivors).toContain("0. One\n1. Two\n2. Any\n</question>");
    expect(survivors).toContain("Reference answer: So memory is freed once.");
    const empty = { topic: topic.name, tier, cards: [], mcqs: [], freeText: [], questionCards: [] };
    expect(prompts.render("tool-results/survivors.njk", empty)).toBe("Nothing is waiting for you.");
  });

  test("the art requests render", () => {
    const requests = prompts.render("tool-results/art-requests.njk", { cards: [card] });
    expect(requests).toContain("Show: a crab holding a box\nIdeas: the box has a label");
    expect(prompts.render("tool-results/art-requests.njk", { cards: [] })).toBe(
      "No card is waiting for art.",
    );
  });
});
