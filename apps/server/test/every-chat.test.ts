import { randomUUID } from "node:crypto";
import type { Static, TSchema } from "typebox";
import { describe, expect, test } from "vitest";
import { askConversation } from "../src/db/schema.ts";
import { answerTool, askTool } from "../src/harness/asking.ts";
import {
  type Chat,
  endRun,
  newHelperChat,
  openAskChat,
  openChat,
  openTopicChat,
  startRun,
} from "../src/harness/chats.ts";
import { checkValue } from "../src/harness/check.ts";
import { everyChatTools } from "../src/harness/every-chat.ts";
import { indiaTime } from "../src/harness/india-time.ts";
import { openingMessageFor } from "../src/harness/instructions.ts";
import { listRecordsTool, readRecordHistoryTool, readRecordTool } from "../src/harness/reading.ts";
import { changeRecord, createRecord, refOf } from "../src/harness/records.ts";
import { routeNewRecords } from "../src/harness/routing.ts";
import {
  type Author,
  CompactionSummaryRecord,
  QuestionRecord,
  type RecordRef,
} from "../src/harness/schemas.ts";
import type { HarnessTool, ToolOutput } from "../src/harness/tools.ts";
import { listWakes } from "../src/harness/wakes.ts";
import { loadPrompts } from "../src/prompts.ts";
import { makeTopic } from "./fixtures.ts";
import { deps, signedUp, userIdOf } from "./helpers.ts";
import { TEST_MODEL } from "./scripted-model.ts";

/*
 * The tools every chat has (task 0045, Phase 9): reading any record, and asking and answering
 * between chats, each record rendered from its own template.
 */

const { db } = deps;
const prompts = loadPrompts();
const MORNING = { kind: "schedule" as const, schedule: "every morning" };

async function newTadpole(): Promise<Chat> {
  const { topic } = await makeTopic();
  return openTopicChat(db, "tadpole", topic.id);
}

/** A reader's AskAI chat, on a thread of their own. */
async function newAskChat(): Promise<Chat> {
  const { topic } = await makeTopic();
  const userId = await userIdOf(await signedUp());
  const [conversation] = await db
    .insert(askConversation)
    .values({ userId, topicId: topic.id })
    .returning({ id: askConversation.id });
  if (!conversation) throw new Error("No thread.");
  return openAskChat(db, conversation.id);
}

function chatAuthor(chat: Chat): Author {
  return { kind: "chat", chatId: chat.id, runId: randomUUID(), model: TEST_MODEL.id };
}

/** Calls a tool as the chat would, in a run of its own that ends with the call. */
async function call<Parameters extends TSchema>(
  tool: HarnessTool<Parameters>,
  chat: Chat,
  params: Static<Parameters>,
): Promise<ToolOutput> {
  const run = await startRun(db, {
    chatId: chat.id,
    model: TEST_MODEL.id,
    triggers: [MORNING],
    systemPrompt: "",
  });
  const author: Author = { kind: "chat", chatId: chat.id, runId: run.id, model: TEST_MODEL.id };
  try {
    return await tool.execute(params, { db, chat, run, author, signal: new AbortController().signal });
  } finally {
    await endRun(db, run.id, { status: "done" });
  }
}

/** These tools hand back records rendered from their templates. */
function text(output: ToolOutput): string {
  if (typeof output.value !== "string") throw new Error("The tool handed back no text.");
  return output.value;
}

function written(output: ToolOutput): RecordRef {
  const [ref] = output.recordsWritten;
  if (!ref) throw new Error("The tool wrote nothing.");
  return ref;
}

/** The chats a record has a wake waiting for. */
async function wokenBy(record: RecordRef): Promise<string[]> {
  const waiting = await listWakes(db, "waiting");
  return waiting.flatMap((wake) =>
    wake.trigger.kind === "record" && wake.trigger.record.id === record.id ? [wake.chatId] : [],
  );
}

describe("ask and answer", () => {
  test("a question wakes the chat asked, and each answer wakes the chat that asked", async () => {
    const tadpole = await newTadpole();
    const toadSage = await openChat(db, "toad_sage");

    const asked = await call(askTool(prompts), tadpole, {
      to: "toad_sage",
      question: "Is the coverage note enough?",
      reasoning: "It names four sources.",
    });
    const question = written(asked);
    expect(asked.value).toContain(
      `Question (question ${question.id} version 1)\nFrom tadpole of topic ${tadpole.topicId}, to toad_sage\nQuestion: Is the coverage note enough?\nWhy it asks: It names four sources.`,
    );
    await routeNewRecords(db, new Date());
    expect(await wokenBy(question)).toEqual([toadSage.id]);

    const first = await call(answerTool(prompts), toadSage, { question: question.id, answer: "Not yet." });
    const second = await call(answerTool(prompts), toadSage, { question: question.id, answer: "Now it is." });
    expect(first.value).toContain(
      `From toad_sage, to tadpole of topic ${tadpole.topicId}\nIt answers question ${question.id} version 1: Is the coverage note enough?\nAnswer: Not yet.`,
    );
    await routeNewRecords(db, new Date());
    expect(await wokenBy(written(first))).toEqual([tadpole.id]);
    expect(await wokenBy(written(second))).toEqual([tadpole.id]);
  });

  test("the chat woken by an answer reads the question with it", async () => {
    const tadpole = await newTadpole();
    const toadSage = await openChat(db, "toad_sage");
    const question = written(
      await call(askTool(prompts), tadpole, {
        to: "toad_sage",
        question: "Which sources?",
        reasoning: "To start.",
      }),
    );
    const answer = written(
      await call(answerTool(prompts), toadSage, { question: question.id, answer: "Primary ones." }),
    );

    const opening = await openingMessageFor(
      db,
      prompts,
      tadpole,
      [{ kind: "record", record: answer }],
      new Date(),
    );

    expect(opening).toContain(
      `The answer to a question you asked:\nAnswer (answer ${answer.id} version 1)\nFrom toad_sage, to tadpole of topic ${tadpole.topicId}\nIt answers question ${question.id} version 1: Which sources?\nAnswer: Primary ones.`,
    );
  });

  test("a question another has changed since is still from its asker, and its answer wakes the asker", async () => {
    const tadpole = await newTadpole();
    const toadSage = await openChat(db, "toad_sage");
    const first = written(
      await call(askTool(prompts), tadpole, {
        to: "toad_sage",
        question: "Which sources?",
        reasoning: "To start.",
      }),
    );
    await changeRecord(db, QuestionRecord, {
      from: first,
      status: "disputed",
      author: { kind: "owner" },
      reason: "Asked before.",
      body: { to: { role: "toad_sage" }, question: "Which sources?", reasoning: "To start." },
    });

    const answered = await call(answerTool(prompts), toadSage, {
      question: first.id,
      answer: "Primary ones.",
    });
    await routeNewRecords(db, new Date());

    expect(answered.value).toContain(
      `From toad_sage, to tadpole of topic ${tadpole.topicId}\nIt answers question ${first.id} version 2: Which sources?`,
    );
    expect(await wokenBy(written(answered))).toEqual([tadpole.id]);
  });

  test("a chat asks neither itself, nor a topic's chat that hasn't started, nor with the wrong topic", async () => {
    const tadpole = await newTadpole();
    const ask = (params: Parameters<ReturnType<typeof askTool>["execute"]>[0]) =>
      call(askTool(prompts), tadpole, params);
    const words = { question: "Which sources?", reasoning: "To start." };

    await expect(ask({ to: "tadpole", topic: tadpole.topicId ?? "", ...words })).rejects.toThrow(
      /That is you/,
    );
    await expect(ask({ to: "designer_toad", topic: tadpole.topicId ?? "", ...words })).rejects.toThrow(
      /hasn't started/,
    );
    await expect(ask({ to: "tadpole", ...words })).rejects.toThrow(/takes its topic's id/);
    await expect(ask({ to: "toad_sage", topic: tadpole.topicId ?? "", ...words })).rejects.toThrow(
      /one toad_sage for every topic/,
    );
  });

  test("a chat asks only the chats that run, since another would never answer", () => {
    const parameters = askTool(prompts).parameters;
    const words = { question: "Which sources?", reasoning: "To start." };

    for (const to of ["ero_sennin", "wise_toad", "visual_toad"]) {
      expect(() => checkValue(parameters, { to, ...words }, "The call to ask")).toThrow(
        'must be one of "toad_sage", "curriculum", "tadpole", "designer_toad"',
      );
    }
    expect(checkValue(parameters, { to: "curriculum", ...words }, "The call to ask").to).toBe("curriculum");
  });

  test("only the chat asked answers, and only a question", async () => {
    const [asker, other] = [await newTadpole(), await newTadpole()];
    const question = written(
      await call(askTool(prompts), asker, {
        to: "toad_sage",
        question: "Which sources?",
        reasoning: "To start.",
      }),
    );

    await expect(
      call(answerTool(prompts), other, { question: question.id, answer: "Mine." }),
    ).rejects.toThrow(/asked of another chat/);
    await expect(
      call(answerTool(prompts), other, { question: randomUUID(), answer: "Mine." }),
    ).rejects.toThrow(/There is no question/);
  });
});

describe("reading records", () => {
  test("read_record reads the latest version, or the one named, with who wrote it and when", async () => {
    const tadpole = await newTadpole();
    const first = await createRecord(db, QuestionRecord, {
      kind: "question",
      author: { kind: "owner" },
      body: { to: { role: "toad_sage" }, question: "Which sources?", reasoning: "To start." },
    });
    const retired = await changeRecord(db, QuestionRecord, {
      from: refOf(first),
      status: "retired",
      author: { kind: "code", component: "test" },
      reason: "Asked twice.",
      body: first.body,
    });

    const latest = await call(readRecordTool(prompts), tadpole, { id: first.id });
    const named = await call(readRecordTool(prompts), tadpole, { id: first.id, version: 1 });

    expect(latest.value).toBe(
      [
        `Question (question ${first.id} version 2)`,
        "From the owner, to toad_sage",
        "Question: Which sources?",
        "Why it asks: To start.",
        "Status: retired",
        "Why version 2: Asked twice.",
        `Written ${indiaTime(new Date(retired.writtenAt))}, India time, by code (test).`,
      ].join("\n"),
    );
    expect(latest.dataSeen).toEqual([refOf(retired)]);
    expect(named.value).toContain(`version 1)`);
    expect(named.value).not.toContain("Status:");
    expect(named.value).toContain("by the owner.");
    await expect(call(readRecordTool(prompts), tadpole, { id: randomUUID() })).rejects.toThrow(
      /There is no record/,
    );
  });

  test("read_record_history reads every version, oldest first", async () => {
    const tadpole = await newTadpole();
    const first = await createRecord(db, QuestionRecord, {
      kind: "question",
      author: chatAuthor(tadpole),
      body: { to: { role: "toad_sage" }, question: "Which sources?", reasoning: "To start." },
    });
    const second = await changeRecord(db, QuestionRecord, {
      from: refOf(first),
      status: "retired",
      author: { kind: "owner" },
      reason: "Asked twice.",
      body: first.body,
    });

    const history = await call(readRecordHistoryTool(prompts), tadpole, { id: first.id });

    expect(history.value).toMatch(
      new RegExp(
        `version 1\\)[^]*by tadpole of topic ${tadpole.topicId}\\.\\n\\nQuestion \\(question ${first.id} version 2\\)[^]*by the owner\\.$`,
      ),
    );
    expect(history.dataSeen).toEqual([refOf(first), refOf(second)]);
  });

  test("list_records gives a line for the latest version of each record of a kind", async () => {
    const tadpole = await newTadpole();
    const helper = await newHelperChat(db, await openChat(db, "toad_sage"), "helper");
    const long = `Should the corpus cover ${"the async runtimes ".repeat(12)}?`;
    const active = await createRecord(db, QuestionRecord, {
      kind: "question",
      author: chatAuthor(helper),
      body: { to: { role: "tadpole", topic: tadpole.topicId ?? "" }, question: long, reasoning: "Scope." },
    });
    const first = await createRecord(db, QuestionRecord, {
      kind: "question",
      author: chatAuthor(tadpole),
      body: { to: { role: "toad_sage" }, question: "Which sources?", reasoning: "To start." },
    });
    const retired = await changeRecord(db, QuestionRecord, {
      from: refOf(first),
      status: "retired",
      author: chatAuthor(tadpole),
      reason: "Asked twice.",
      body: first.body,
    });

    const all = await call(listRecordsTool(prompts), tadpole, { kind: "question" });
    const onlyRetired = await call(listRecordsTool(prompts), tadpole, {
      kind: "question",
      status: "retired",
    });

    const line = text(all)
      .split("\n")
      .find((entry) => entry.includes(active.id));
    expect(line).toMatch(
      new RegExp(
        `^- question ${active.id} version 1 \\(active\\), by a helper of toad_sage, ${indiaTime(new Date(active.writtenAt))}\\. To tadpole of topic ${tadpole.topicId}: Should the corpus cover the async runtimes .*\\.\\.\\.$`,
      ),
    );
    expect(line?.length).toBeLessThan(long.length + 150);
    expect(all.value).toContain(`- question ${first.id} version 2 (retired), by tadpole of topic`);
    expect(all.value).not.toContain(`${first.id} version 1`);
    expect(onlyRetired.value).toContain(retired.id);
    expect(onlyRetired.value).not.toContain(active.id);
    expect(all.dataSeen).toContainEqual(refOf(retired));
  });

  test("AskAI's records aren't there for any other chat", async () => {
    const tadpole = await newTadpole();
    const summaryOf = (chat: Chat) =>
      createRecord(db, CompactionSummaryRecord, {
        kind: "compaction_summary",
        author: chatAuthor(chat),
        body: {
          chatId: chat.id,
          throughRun: randomUUID(),
          soFar: "Talked it through.",
          learnings: [],
          feedback: [],
          dos: [],
          donts: [],
          nextSteps: [],
        },
      });
    const readers = await summaryOf(await newAskChat());
    const tadpoles = await summaryOf(tadpole);

    const listed = await call(listRecordsTool(prompts), tadpole, { kind: "compaction_summary" });

    expect(listed.value).toContain(tadpoles.id);
    expect(listed.value).not.toContain(readers.id);
    await expect(call(readRecordTool(prompts), tadpole, { id: readers.id })).rejects.toThrow(
      `There is no record ${readers.id}.`,
    );
    await expect(call(readRecordHistoryTool(prompts), tadpole, { id: readers.id })).rejects.toThrow(
      `There is no record ${readers.id}.`,
    );
  });

  test("an empty list says so", () => {
    expect(
      prompts.render("tool-results/listed.njk", { kind: "answer", status: "disputed", records: [] }),
    ).toBe("There are no answer records with status disputed.");
  });
});

describe("every chat's tools", () => {
  test("a main chat reads, asks and answers; a helper only reads", async () => {
    const tadpole = await newTadpole();
    const helper = await newHelperChat(db, tadpole, "helper");
    const names = (chat: Chat) => everyChatTools(prompts, chat).map((tool) => tool.name);

    expect(names(tadpole)).toEqual(["read_record", "read_record_history", "list_records", "ask", "answer"]);
    expect(names(helper)).toEqual(["read_record", "read_record_history", "list_records"]);
  });
});
