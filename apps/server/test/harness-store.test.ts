import { sql } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import {
  ChatBusyError,
  endRun,
  markInterruptedRuns,
  newHelperChat,
  openChat,
  openChatAt,
  openTopicChat,
  readRun,
  startRun,
} from "../src/harness/chats.ts";
import { SchemaError } from "../src/harness/check.ts";
import {
  changeRecord,
  createRecord,
  listLatestRecords,
  RecordConflictError,
  readAnyRecord,
  readLatestRecord,
  readRecordHistory,
  refOf,
  revertRecord,
  StoreError,
} from "../src/harness/records.ts";
import { type Author, QuestionRecord } from "../src/harness/schemas.ts";
import {
  appendActionLogEntry,
  appendMessage,
  lastSeqOfRun,
  readActionLog,
  readTranscript,
} from "../src/harness/transcript.ts";
import {
  chatsWithDueWakes,
  dropWake,
  dueWakes,
  failWake,
  finishWake,
  queueWake,
  readSchedulerMark,
  releaseTakenWakes,
  returnWake,
  saveSchedulerMark,
  takeWake,
} from "../src/harness/wakes.ts";
import { makeTopic } from "./fixtures.ts";
import { deps } from "./helpers.ts";

/*
 * The harness's store (task 0045, Phase 9): Trotter's records, chats, runs, transcript, action log
 * and wake queue, on Postgres.
 */

const { db } = deps;
const owner: Author = { kind: "owner" };
const code: Author = { kind: "code", component: "test" };

async function aQuestion(question = "Is the coverage note enough?") {
  const topic = await makeTopic();
  return createRecord(db, QuestionRecord, {
    kind: "question",
    author: owner,
    body: { to: { role: "tadpole", topic: topic.topic.id }, question, reasoning: "It names no sources." },
  });
}

const user = (text: string, timestamp = Date.now()) => ({ role: "user" as const, content: text, timestamp });

describe("records", () => {
  test("a change is the next version, saying why, and every version reads back", async () => {
    const first = await aQuestion();
    expect(first.version).toBe(1);
    const second = await changeRecord(db, QuestionRecord, {
      from: refOf(first),
      status: "active",
      author: code,
      reason: "Sharper.",
      body: { ...first.body, question: "Which sources does it name?" },
    });
    expect(second).toMatchObject({ id: first.id, version: 2, reason: "Sharper." });
    expect((await readLatestRecord(db, QuestionRecord, "question", first.id)).body.question).toBe(
      "Which sources does it name?",
    );
    expect((await readRecordHistory(db, QuestionRecord, "question", first.id)).map((r) => r.version)).toEqual(
      [1, 2],
    );
    expect(await readAnyRecord(db, refOf(first))).toEqual(first);
  });

  test("a writer who read an older version stores nothing and is told to read again", async () => {
    const first = await aQuestion();
    const change = { status: "active" as const, author: code, reason: "Again.", body: first.body };
    await changeRecord(db, QuestionRecord, { ...change, from: refOf(first) });
    await expect(changeRecord(db, QuestionRecord, { ...change, from: refOf(first) })).rejects.toThrow(
      RecordConflictError,
    );
    expect(await readRecordHistory(db, QuestionRecord, "question", first.id)).toHaveLength(2);
  });

  test("an undo puts back an earlier version's body and status as the next version", async () => {
    const first = await aQuestion("First?");
    const retired = await changeRecord(db, QuestionRecord, {
      from: refOf(first),
      status: "retired",
      author: code,
      reason: "Answered elsewhere.",
      body: { ...first.body, question: "Second?" },
    });
    await expect(
      revertRecord(db, QuestionRecord, { from: refOf(retired), to: 2, author: owner, reason: "No." }),
    ).rejects.toThrow(/earlier version/);
    const undone = await revertRecord(db, QuestionRecord, {
      from: refOf(retired),
      to: 1,
      author: owner,
      reason: "Wrongly retired.",
    });
    expect(undone).toMatchObject({
      version: 3,
      status: "active",
      revertsTo: 1,
      body: { question: "First?" },
    });
  });

  test("a body that doesn't match its kind's schema is refused with every problem, and nothing is stored", async () => {
    const before = await listLatestRecords(db, QuestionRecord, "question");
    const bad = createRecord(db, QuestionRecord, {
      kind: "question",
      author: owner,
      body: { to: { role: "tadpole" }, question: "", extra: 1 },
    });
    await expect(bad).rejects.toThrow(SchemaError);
    await expect(bad).rejects.toThrow(/unexpected field "extra"/);
    expect(await listLatestRecords(db, QuestionRecord, "question")).toHaveLength(before.length);
  });

  test("a reference to a kind that doesn't exist says which do", async () => {
    await expect(readAnyRecord(db, { kind: "memo", id: crypto.randomUUID(), version: 1 })).rejects.toThrow(
      /no kind of record called memo. The kinds are: question, answer, compaction_summary/,
    );
  });

  test("the database refuses to change or delete a stored version, the transcript or the action log", async () => {
    const first = await aQuestion();
    // The row triggers fire only on a row, so each table gets one.
    const chat = await openChat(db, "ero_sennin");
    const run = await startRun(db, {
      chatId: chat.id,
      model: "m",
      systemPrompt: "s",
      triggers: [{ kind: "schedule", schedule: "test" }],
    });
    await appendMessage(db, run, user("one"));
    await appendActionLogEntry(db, {
      runId: run.id,
      toolCallId: "call_1",
      tool: "read_record",
      arguments: {},
      reasoning: "",
      result: { ok: true, value: null },
      dataSeen: [],
      recordsWritten: [],
    });
    await endRun(db, run.id, { status: "done" });
    // drizzle wraps the error; Postgres's own is its cause.
    const refused = {
      cause: expect.objectContaining({ message: expect.stringMatching(/only ever added to/) }),
    };
    await expect(
      db.execute(sql`UPDATE harness_record SET status = 'retired' WHERE id = ${first.id}`),
    ).rejects.toMatchObject(refused);
    await expect(db.execute(sql`DELETE FROM harness_record WHERE id = ${first.id}`)).rejects.toMatchObject(
      refused,
    );
    await expect(db.execute(sql`UPDATE chat_message SET seq = seq + 1`)).rejects.toMatchObject(refused);
    await expect(db.execute(sql`TRUNCATE chat_message`)).rejects.toMatchObject(refused);
    await expect(db.execute(sql`DELETE FROM action_log`)).rejects.toMatchObject(refused);
  });
});

describe("chats", () => {
  test("there is one toad_sage, and one tadpole per topic", async () => {
    const sage = await openChat(db, "toad_sage");
    expect((await openChat(db, "toad_sage")).id).toBe(sage.id);
    const { topic } = await makeTopic();
    const tadpole = await openChatAt(db, { role: "tadpole", topic: topic.id });
    expect((await openTopicChat(db, "tadpole", topic.id)).id).toBe(tadpole.id);
    expect((await openTopicChat(db, "designer_toad", topic.id)).id).not.toBe(tadpole.id);
  });

  test("a helper belongs to the chat that started it, and starts none of its own", async () => {
    const sage = await openChat(db, "toad_sage");
    const helper = await newHelperChat(db, sage);
    expect(helper).toMatchObject({ role: "helper", parentId: sage.id });
    await expect(newHelperChat(db, helper)).rejects.toThrow(/can't start helpers/);
  });

  test("the database refuses a tadpole without a topic", async () => {
    await expect(db.execute(sql`INSERT INTO chat (role) VALUES ('tadpole')`)).rejects.toMatchObject({
      cause: expect.objectContaining({ constraint: "ck_chat_topic" }),
    });
  });
});

describe("runs and the transcript", () => {
  test("a chat runs once at a time, and a run ends once", async () => {
    const { topic } = await makeTopic();
    const chat = await openTopicChat(db, "tadpole", topic.id);
    const start = {
      chatId: chat.id,
      model: "gemini",
      systemPrompt: "You write.",
      triggers: [{ kind: "schedule" as const, schedule: "test" }],
    };
    const run = await startRun(db, start);
    await expect(startRun(db, start)).rejects.toThrow(ChatBusyError);
    const ended = await endRun(db, run.id, { status: "failed", error: "The model never answered." });
    expect(ended).toMatchObject({ status: "failed", error: "The model never answered." });
    await expect(endRun(db, run.id, { status: "done" })).rejects.toThrow(/already ended: failed/);
    expect((await startRun(db, start)).status).toBe("running");
  });

  test("a run starts only from triggers that check", async () => {
    const chat = await openChat(db, "wise_toad");
    await expect(
      startRun(db, { chatId: chat.id, model: "m", systemPrompt: "s", triggers: [] }),
    ).rejects.toThrow(SchemaError);
  });

  test("messages go on the end of the chat's transcript, across its runs", async () => {
    const { topic } = await makeTopic();
    const chat = await openTopicChat(db, "visual_toad", topic.id);
    const triggers = [{ kind: "schedule" as const, schedule: "test" }];
    const first = await startRun(db, { chatId: chat.id, model: "m", systemPrompt: "s", triggers });
    await appendMessage(db, first, user("one"));
    await appendMessage(db, first, user("two"));
    await endRun(db, first.id, { status: "done" });
    const second = await startRun(db, { chatId: chat.id, model: "m", systemPrompt: "s", triggers });
    await appendMessage(db, second, user("three"));
    expect((await readTranscript(db, chat.id)).map((e) => [e.seq, e.message.content])).toEqual([
      [1, "one"],
      [2, "two"],
      [3, "three"],
    ]);
    expect(await lastSeqOfRun(db, first)).toBe(2);
    expect((await readTranscript(db, chat.id, 2)).map((e) => e.runId)).toEqual([second.id]);
    await expect(appendMessage(db, second, { role: "system", content: "x" } as never)).rejects.toThrow(
      SchemaError,
    );
  });

  test("every tool call is logged with what it read and wrote", async () => {
    const chat = await openChat(db, "ero_sennin");
    const run = await startRun(db, {
      chatId: chat.id,
      model: "m",
      systemPrompt: "s",
      triggers: [{ kind: "schedule", schedule: "test" }],
    });
    const question = await aQuestion();
    await appendActionLogEntry(db, {
      runId: run.id,
      toolCallId: "call_1",
      tool: "read_record",
      arguments: { id: question.id },
      reasoning: "I need the question.",
      result: { ok: true, value: "the question" },
      dataSeen: [refOf(question)],
      recordsWritten: [],
    });
    const [entry] = await readActionLog(db, run.id);
    expect(entry).toMatchObject({ tool: "read_record", dataSeen: [refOf(question)] });
    await endRun(db, run.id, { status: "done" });
  });

  test("runs still going when the worker starts were cut off", async () => {
    const chat = await openChat(db, "curriculum");
    const run = await startRun(db, {
      chatId: chat.id,
      model: "m",
      systemPrompt: "s",
      triggers: [{ kind: "schedule", schedule: "test" }],
    });
    await markInterruptedRuns(db);
    expect((await readRun(db, run.id)).status).toBe("interrupted");
  });
});

describe("the wake queue", () => {
  test("a chat's due wakes come in the order they came due; later ones wait", async () => {
    const { topic } = await makeTopic();
    const chat = await openTopicChat(db, "designer_toad", topic.id);
    const now = new Date();
    const at = (s: number) => new Date(now.getTime() + s * 1000);
    const schedule = (name: string) => ({ kind: "schedule" as const, schedule: name });
    await queueWake(db, { chatId: chat.id, trigger: schedule("second"), dueAt: at(-10) });
    await queueWake(db, { chatId: chat.id, trigger: schedule("first"), dueAt: at(-20) });
    await queueWake(db, { chatId: chat.id, trigger: schedule("later"), dueAt: at(60) });
    expect(await chatsWithDueWakes(db, now)).toContain(chat.id);
    const due = await dueWakes(db, chat.id, now);
    expect(due.map((w) => w.trigger)).toEqual([schedule("first"), schedule("second")]);
  });

  test("a wake is taken, then done, failed and retried, given up, or returned", async () => {
    const { topic } = await makeTopic();
    const chat = await openTopicChat(db, "tadpole", topic.id);
    const queue = () =>
      queueWake(db, { chatId: chat.id, trigger: { kind: "schedule", schedule: "test" }, dueAt: new Date() });

    const done = await finishWake(db, await takeWake(db, await queue()));
    expect(done.status).toBe("done");
    await expect(finishWake(db, done)).rejects.toThrow(/is done, not taken/);

    const retryAt = new Date(Date.now() + 15 * 60_000);
    const retried = await failWake(db, await takeWake(db, await queue()), "The proxy is down.", retryAt);
    expect(retried).toMatchObject({
      status: "waiting",
      tries: 1,
      error: "The proxy is down.",
      dueAt: retryAt,
    });
    const givenUp = await failWake(db, await takeWake(db, retried), "Still down.");
    expect(givenUp).toMatchObject({ status: "given_up", tries: 2 });

    const returned = await returnWake(db, await takeWake(db, await queue()));
    expect(returned).toMatchObject({ status: "waiting", tries: 0 });
    expect((await dropWake(db, returned)).status).toBe("dropped");

    const cutOff = await takeWake(db, await queue());
    const released = await releaseTakenWakes(db);
    expect(released.map((w) => w.id)).toContain(cutOff.id);
  });

  test("a wake for a record checks its reference", async () => {
    const chat = await openChat(db, "toad_sage");
    await expect(
      queueWake(db, {
        chatId: chat.id,
        trigger: { kind: "record", record: { kind: "question", id: "not-an-id", version: 1 } },
        dueAt: new Date(),
      }),
    ).rejects.toThrow(SchemaError);
  });

  test("the scheduler's marks are kept by name", async () => {
    expect(await readSchedulerMark(db, "test-mark")).toBeUndefined();
    await saveSchedulerMark(db, "test-mark", "1");
    await saveSchedulerMark(db, "test-mark", "2");
    expect(await readSchedulerMark(db, "test-mark")).toBe("2");
  });
});

test("the store's errors are StoreErrors", () => {
  expect(new RecordConflictError("x")).toBeInstanceOf(StoreError);
  expect(new ChatBusyError("x")).toBeInstanceOf(StoreError);
});
