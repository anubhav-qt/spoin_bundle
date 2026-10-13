import { randomUUID } from "node:crypto";
import { HashEmbedder } from "@spoin/frog/embeddings";
import { and, asc, eq, inArray, sql } from "drizzle-orm";
import { Type } from "typebox";
import { describe, expect, test } from "vitest";
import {
  ART_STYLE,
  artProblems,
  artWords,
  attachArtTool,
  boxShare,
  listArtRequestsTool,
  paddedLines,
  renderArtTool,
} from "../src/agents/art.ts";
import type { AgentDeps } from "../src/agents/context.ts";
import { correctCardsOnNimTool, correctCardsTool, correctedOnNim, settleOnce } from "../src/agents/gate.ts";
import { startHelper } from "../src/agents/helpers.ts";
import { correctionsOnly, writeOnNimTool } from "../src/agents/nim-writes.ts";
import { lookAtTool } from "../src/agents/pages.ts";
import {
  artQuotas,
  cardMix,
  putCardsLiveIfDone,
  questionTarget,
  startReadyTiers,
  TIERS_AUTHOR,
  tierById,
  writeQuestionsTool,
  writerOf,
} from "../src/agents/tiers.ts";
import { card, harnessRecord, question, subtopic, topic } from "../src/db/schema.ts";
import { type Chat, endRun, openTopicChat, startRun } from "../src/harness/chats.ts";
import { CLOSED } from "../src/harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError, type ToolOutput } from "../src/harness/tools.ts";
import { loadPrompts } from "../src/prompts.ts";
import { deps } from "./helpers.ts";
import { reply, scriptedModel, TEST_MODEL } from "./scripted-model.ts";

/*
 * How code runs a topic's tiers (task 0045): the first tiers start on publish, a tier's cards go
 * live once every accepted card that asked for art has it, and only then is its writer asked for
 * its share of the topic's questions. A writer's big write is one NIM call, every try of which is
 * kept.
 */

const { db } = deps;
const prompts = loadPrompts();
const embedder = new HashEmbedder();
const agentDeps = { db, prompts, embedder } as unknown as AgentDeps;
/** Renders every card as the same picture: the tests read the records, not the pixels. */
const artDeps = {
  ...agentDeps,
  browser: { renderCard: async () => Buffer.from("png"), screenshot: async () => Buffer.from("jpeg") },
} as unknown as AgentDeps;
const MORNING = { kind: "schedule" as const, schedule: "every morning" };

/** A topic of one subtopic at three tiers of five cards, none written yet. */
async function newTopic() {
  const name = `Caching ${randomUUID().slice(0, 6)}`;
  const [made] = await db
    .insert(topic)
    .values({ slug: name.toLowerCase().replaceAll(/\W+/g, "-"), canonicalName: name, scope: "topic" })
    .returning();
  if (!made) throw new Error("No topic.");
  const group = randomUUID();
  const tiers = await db
    .insert(subtopic)
    .values(
      (["beginner", "intermediate", "advanced"] as const).map((difficulty) => ({
        topicId: made.id,
        subtopicGroupId: group,
        difficulty,
        title: "Caching",
        description: "Where a copy of the data lives, and when it lies.",
        targetCards: 5,
        minCards: 3,
        position: 0,
      })),
    )
    .returning();
  const [beginner, intermediate] = tiers;
  if (!beginner || !intermediate) throw new Error("No tiers.");
  return { topic: made, beginner, intermediate };
}

/** Accepted cards as pass 2 leaves them, the first `withArt` of them ascii cards waiting on art. */
async function acceptedCards(tier: typeof subtopic.$inferSelect, count: number, withArt = 0) {
  const gag = { kind: "gag", show: "A cache lying.", ideas: "A cache with its fingers crossed." };
  const writer = randomUUID();
  return db
    .insert(card)
    .values(
      Array.from({ length: count }, (_, index) => ({
        familyId: randomUUID(),
        topicId: tier.topicId,
        subtopicId: tier.id,
        difficulty: tier.difficulty,
        title: `Card ${index}`,
        canonicalTitle: `Concept ${index}`,
        summary: "A hook.",
        body: `The body of card ${index}.`,
        genMeta:
          index < withArt
            ? { stage: "accepted", form: "ascii", art: gag, writer }
            : { stage: "accepted", form: "prose", writer },
      })),
    )
    .returning();
}

/** The briefs written to a helper, oldest first. */
async function briefsTo(helper: string): Promise<string[]> {
  const rows = await db
    .select({ body: harnessRecord.body })
    .from(harnessRecord)
    .where(and(eq(harnessRecord.kind, "brief"), sql`${harnessRecord.body} ->> 'helper' = ${helper}`))
    .orderBy(asc(harnessRecord.seq));
  return rows.map((row) => (row.body as { brief: string }).brief);
}

/** Calls a tool as the chat would, in a run of its own that ends with the call. */
async function call(tool: HarnessTool, chat: Chat, params: unknown): Promise<ToolOutput> {
  const [output] = await callsInOneRun(chat, [[tool, params]]);
  if (!output) throw new Error("No output.");
  return output;
}

/** Calls tools one after another in one run of the chat, as a turn would. */
async function callsInOneRun(chat: Chat, calls: [HarnessTool, unknown][]): Promise<ToolOutput[]> {
  const run = await startRun(db, {
    chatId: chat.id,
    model: TEST_MODEL.id,
    triggers: [MORNING],
    systemPrompt: "",
  });
  const outputs: ToolOutput[] = [];
  try {
    for (const [tool, params] of calls) {
      outputs.push(
        await tool.execute(params, {
          db,
          chat,
          run,
          author: { kind: "chat", chatId: chat.id, runId: run.id, model: TEST_MODEL.id },
          signal: new AbortController().signal,
        }),
      );
    }
    return outputs;
  } finally {
    await endRun(db, run.id, { status: "done" });
  }
}

describe("a topic's questions", () => {
  test("the topic's card target is clamped to 200 to 300 questions, shared by the tiers' targets", async () => {
    const { beginner } = await newTopic();
    // 15 cards in all: the floor of 200, a third each.
    expect(await questionTarget(db, beginner)).toBe(67);

    const big = await newTopic();
    await db.update(subtopic).set({ targetCards: 25 }).where(eq(subtopic.topicId, big.topic.id));
    for (let group = 0; group < 10; group++) {
      await db.insert(subtopic).values({
        topicId: big.topic.id,
        difficulty: "beginner",
        title: `More ${group}`,
        description: "More.",
        targetCards: 25,
        minCards: 3,
        position: group + 1,
      });
    }
    // 325 cards in all: the ceiling of 300, 25 of 325 of it.
    expect(await questionTarget(db, await tierById(db, big.beginner.id))).toBe(23);
  });
});

describe("a tier's mix", () => {
  test("each type gets its share of the target, the largest remainders taking what is left", () => {
    expect(cardMix(10)).toEqual({ ascii: 5, diagram: 2, prose: 2, comparison: 1 });
    expect(cardMix(7)).toEqual({ ascii: 4, diagram: 1, prose: 1, comparison: 1 });
    expect(cardMix(250)).toEqual({ ascii: 125, diagram: 50, prose: 50, comparison: 25 });
  });

  test("the ascii cards' art is gags to informative drawings, 30 to 20", () => {
    expect(artQuotas(5)).toEqual({ gag: 3, informative: 2 });
    expect(artQuotas(125)).toEqual({ gag: 75, informative: 50 });
  });
});

describe("running the tiers", () => {
  test("only a subtopic's first tier starts, and the next once its cards are live", async () => {
    const { topic: made, beginner, intermediate } = await newTopic();
    const started = await db.transaction((tx) => startReadyTiers(tx, made.id));
    expect(started.map((brief) => brief.body.subtopic)).toEqual([beginner.id]);
    expect(await db.transaction((tx) => startReadyTiers(tx, made.id))).toEqual([]);

    const cards = await acceptedCards(beginner, 5, 2);
    expect(await db.transaction((tx) => putCardsLiveIfDone(tx, beginner))).toBe(false);

    // Only the two ascii cards wait on art; the prose ones need none.
    const [first, second] = cards;
    if (!first || !second) throw new Error("No cards.");
    await db
      .update(card)
      .set({ visualKind: "ascii", visualId: randomUUID() })
      .where(inArray(card.id, [first.id, second.id]));
    expect(await db.transaction((tx) => putCardsLiveIfDone(tx, beginner))).toBe(true);

    const live = await db.select({ status: card.status }).from(card).where(eq(card.subtopicId, beginner.id));
    expect(live.map((row) => row.status)).toEqual(cards.map(() => "active"));
    const writer = await writerOf(db, beginner.id);
    if (!writer) throw new Error("No writer.");
    expect((await briefsTo(writer)).at(-1)).toBe(
      "The tier's 5 cards are live. Write its 67 questions: each from one of its cards, one of them free text and the rest MCQs.",
    );
    expect(await writerOf(db, intermediate.id)).toBeDefined();
  });

  test("a tier's questions wait for its cards, then fill its share with one free-text question", async () => {
    const { topic: made, beginner: tier } = await newTopic();
    const tadpole = await openTopicChat(db, "tadpole", made.id);
    const { chat: writer } = await startHelper(db, tadpole, TIERS_AUTHOR, {
      task: "tier_writer",
      brief: "Write it.",
      topic: made.id,
      subtopic: tier.id,
    });
    const tool = writeQuestionsTool(agentDeps) as unknown as HarnessTool;
    const mcq = (cardId: string, stem: string) => ({
      card: cardId,
      kind: "mcq",
      stem,
      options: ["One", "Two", "Three", "Four"],
      correct_index: 0,
      explanation: "The card says so.",
    });

    await expect(call(tool, writer, { questions: [mcq(randomUUID(), "Too soon?")] })).rejects.toThrow(
      "once the tier's cards are live",
    );

    const [first] = await acceptedCards(tier, 5);
    if (!first) throw new Error("No card.");
    await db.update(card).set({ status: "active" }).where(eq(card.subtopicId, tier.id));
    const output = await call(tool, writer, {
      questions: [
        mcq(first.id, "Where does a cache-aside read go first?"),
        { ...mcq(first.id, "Which eviction policy drops the oldest?"), options: ["A", "B", "C"] },
        {
          card: first.id,
          kind: "free_text",
          stem: "Why does a write-through cache never serve a stale read?",
          rubric: "0: nothing. 1: names the write. 2: the order. 3: the order and why.",
          reference_answer: "Every write updates the cache before it returns.",
          explanation: "The card's second paragraph.",
        },
      ],
    });
    expect(String(output.value)).toContain("Stored 2 questions, now with a pass-2 verifier");
    expect(String(output.value)).toContain("question 2: an MCQ has 4 options");
    const stored = await db.select().from(question).where(eq(question.subtopicId, tier.id));
    expect(stored.map((row) => row.kind).sort()).toEqual(["free_text", "mcq"]);

    const second = await call(tool, writer, {
      questions: [
        {
          card: first.id,
          kind: "free_text",
          stem: "What does a cache stampede cost the database?",
          rubric: "0: -. 1: -. 2: -. 3: -.",
          reference_answer: "A burst of identical reads.",
          explanation: "The card.",
        },
        mcq(first.id, "What does a TTL bound?"),
      ],
    });
    expect(String(second.value)).toContain("the tier has its one free-text question; write an MCQ");
  });
});

describe("a write on NIM", () => {
  const Numbers = Type.Object({ n: Type.Integer({ maximum: 3 }) }, CLOSED);
  const stored: number[] = [];
  const inner: HarnessTool<typeof Numbers> = {
    name: "write_numbers",
    label: "Write numbers",
    description: "Stores a number.",
    parameters: Numbers,
    kind: "change",
    async execute(params) {
      if (params.n === 2) throw new ToolError("Two is taken.");
      stored.push(params.n);
      return { value: `Stored ${params.n}.`, dataSeen: [], recordsWritten: [] };
    },
  };
  const text = (written: string) => reply([{ type: "text", text: written }]);

  async function writerChat(): Promise<Chat> {
    const { topic: made } = await newTopic();
    const tadpole = await openTopicChat(db, "tadpole", made.id);
    return (await startHelper(db, tadpole, TIERS_AUTHOR, { task: "tier_writer", brief: "Write." })).chat;
  }

  function onNim(...answers: ReturnType<typeof reply>[]) {
    const nim = scriptedModel(answers);
    const tool = writeOnNimTool(
      prompts,
      { model: TEST_MODEL, apiKey: "test", streamFn: () => nim.streamFn },
      [inner as unknown as HarnessTool],
    );
    return { nim, tool };
  }

  test("NIM writes the tool's arguments as JSON text, and the tool stores them", async () => {
    const { nim, tool } = onNim(text('Here it is:\n```json\n{"n": 3}\n```'));
    const output = await call(tool, await writerChat(), {
      tool: "write_numbers",
      instructions: "Write three.",
    });

    expect(String(output.value)).toBe('NIM wrote:\n{"n":3}\n\nStored:\nStored 3.');
    expect(stored).toContain(3);
    expect(nim.requests).toHaveLength(1);
    expect(nim.options[0]?.toolChoice).toBe("none");
    const asked = JSON.stringify(nim.requests[0]?.at(-1));
    expect(asked).toContain("the arguments of write_numbers");
    expect(asked).toContain("Write three.");
  });

  test("a refused write comes back with what NIM wrote, for the writer to fix itself", async () => {
    const { tool } = onNim(text('{"n": 2}'));
    await expect(
      call(tool, await writerChat(), { tool: "write_numbers", instructions: "Write two." }),
    ).rejects.toThrow(/NIM wrote:\n\{"n":2\}\n\nRefused: Two is taken\.\nFix it with write_numbers yourself/);
  });

  test("the writer's own copy refuses the first write, and corrects once there is one", async () => {
    let written = false;
    const own = correctionsOnly(inner as unknown as HarnessTool, async () => written);
    const chat = await writerChat();
    await expect(call(own, chat, { n: 1 })).rejects.toThrow(
      /The first write is NIM's: call write_on_nim with write_numbers/,
    );
    written = true;
    expect(String((await call(own, chat, { n: 1 })).value)).toBe("Stored 1.");
  });

  test("a draft's first correction is NIM's, stored or refused, and the corrector fixes it after", async () => {
    const { topic: made, beginner: tier } = await newTopic();
    const tadpole = await openTopicChat(db, "tadpole", made.id);
    const { chat: corrector } = await startHelper(db, tadpole, TIERS_AUTHOR, {
      task: "corrector",
      brief: "Correct.",
      topic: made.id,
      subtopic: tier.id,
    });
    const [draft] = await db
      .insert(card)
      .values({
        familyId: randomUUID(),
        topicId: made.id,
        subtopicId: tier.id,
        difficulty: tier.difficulty,
        title: "A draft",
        canonicalTitle: "A concept",
        summary: "A hook.",
        body: "The body.",
        genMeta: { stage: "correcting", form: "prose" },
      })
      .returning();
    if (!draft) throw new Error("No draft.");
    const entry = { card: draft.id, note: "It stands." };
    const own = correctionsOnly(correctCardsTool(agentDeps), correctedOnNim) as unknown as HarnessTool;
    await expect(call(own, corrector, { cards: [entry] })).rejects.toThrow(
      /The first write is NIM's: call write_on_nim with correct_cards/,
    );

    // NIM's correction is refused (the body it keeps is too short), and still counts as its first.
    const onNim = correctCardsOnNimTool(agentDeps) as unknown as HarnessTool;
    await expect(call(onNim, corrector, { cards: [entry] })).rejects.toThrow("Nothing was stored");
    const context = { db } as unknown as ToolContext;
    expect(await correctedOnNim(context, { cards: [entry] })).toBe(true);
  });

  test("an entry naming a row not waiting, or one named again, is refused alone", () => {
    const waiting = [{ id: "a" }, { id: "b" }];
    const entries = [{ card: "a" }, { card: "x" }, { card: "a" }, { card: "b" }];
    const named = settleOnce(waiting, entries, (entry) => entry.card, "Card");
    expect(named.settled.map((one) => one.row.id)).toEqual(["a", "b"]);
    expect(named.refused).toEqual([
      "Card x isn't one waiting for you",
      "Card a is named twice; only its first entry counts",
    ]);
    expect(() => settleOnce(waiting, [{ card: "x" }], (entry) => entry.card, "Card")).toThrow(
      "Nothing was stored",
    );
  });

  test("an answer with no JSON goes back to the writer, kept", async () => {
    const { nim, tool } = onNim(text("I would rather not."));
    await expect(
      call(tool, await writerChat(), { tool: "write_numbers", instructions: "Write one." }),
    ).rejects.toThrow(/NIM wrote no JSON for write_numbers[\s\S]*I would rather not\./);
    expect(nim.requests).toHaveLength(1);
  });
});

describe("designer_toad's art", () => {
  const drawn = ["   _~^~^~_", "\\) /  o o  \\ (/", "  '_   -   _'", "  / '-----' \\   owner"].join("\n");

  test("code refuses art that is more text than picture", () => {
    expect(artWords("(o_O) oo wWw zZz HEAP owner's")).toEqual(["HEAP", "owner's"]);
    expect(artProblems(drawn, "gag")).toEqual([]);
    const sentence = "The borrow checker refuses this because the reference outlives its owner, sadly.";
    expect(artProblems(`${drawn}\n${sentence}`, "gag").join()).toContain(
      "it has 13 words; a gag has at most 12",
    );
    // An informative drawing may carry more words, never more letters than picture.
    expect(artProblems(`${drawn}\n${sentence}`, "informative").join()).toContain(
      "of its characters are letters; an informative drawing has at most 40%",
    );
  });

  test("code refuses boxes, and rows of # in place of text", () => {
    // The first redraws: a box with a small face under it, its text swapped for rows of #.
    const boxed = [
      "  +=============+",
      "  |  DOOR      |",
      "  |  ######### |",
      "  +======+=====+",
      "         |",
      "       (0_0)",
    ].join("\n");
    const problems = artProblems(boxed, "gag").join();
    expect(boxShare(boxed)).toBeGreaterThan(0.4);
    expect(problems).toContain("of its characters are box lines");
    expect(problems).toContain("line 3 is a row of # standing in for text");
    expect(paddedLines("      ##### ##### #####")).toEqual([1]);
    // # that shades a drawing is art.
    expect(paddedLines(["  (#####)", " /  |####|"].join("\n"))).toEqual([]);
  });

  test("look_at shows a public page or picture as a screenshot, and refuses a local one", async () => {
    const { topic: made } = await newTopic();
    const designer = await openTopicChat(db, "designer_toad", made.id);
    const seen = await call(lookAtTool(artDeps), designer, { url: "https://example.com/this-is-fine.png" });
    expect(seen.images).toEqual([{ data: Buffer.from("jpeg").toString("base64"), mimeType: "image/jpeg" }]);
    await expect(call(lookAtTool(artDeps), designer, { url: "http://db:5432/" })).rejects.toThrow(
      "is not a public site",
    );
  });

  test("art of an older style is redrawn after the cards waiting for their first, live cards too", async () => {
    const { topic: made, beginner, intermediate } = await newTopic();
    const waiting = await acceptedCards(beginner, 2, 2);
    const [old] = await acceptedCards(intermediate, 1, 1);
    if (!old) throw new Error("No card.");
    await db
      .update(card)
      .set({
        status: "active",
        visualId: randomUUID(),
        visualKind: "ascii",
        visualSlots: { art: "THE OLD ART, ALL WORDS", alt: "Old." },
      })
      .where(eq(card.id, old.id));
    const designer = await openTopicChat(db, "designer_toad", made.id);

    const listed = String((await call(listArtRequestsTool(artDeps), designer, {})).value);
    const firstWaiting = listed.indexOf(waiting[0]?.id ?? "none");
    expect(firstWaiting).toBeGreaterThan(-1);
    expect(firstWaiting).toBeLessThan(listed.indexOf(old.id));
    expect(listed.match(/Redraw:/g)).toHaveLength(1);

    const piece = { card: old.id, art: drawn, alt: "A crab holding its box." };
    await callsInOneRun(designer, [
      [renderArtTool(artDeps), { art: [piece] }],
      [attachArtTool(artDeps), { art: [piece] }],
    ]);
    const [redrawn] = await db.select().from(card).where(eq(card.id, old.id));
    if (!redrawn) throw new Error("No card.");
    expect(redrawn.status).toBe("active");
    expect(redrawn.visualSlots).toEqual({ art: drawn, alt: "A crab holding its box." });
    expect((redrawn.genMeta as { artStyle?: number }).artStyle).toBe(ART_STYLE);
    const after = String((await call(listArtRequestsTool(artDeps), designer, {})).value);
    expect(after).not.toContain(old.id);
  });
});
