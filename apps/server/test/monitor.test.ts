import { sql } from "drizzle-orm";
import { afterAll, describe, expect, test } from "vitest";
import { askConversation } from "../src/db/schema.ts";
import { endRun, newHelperChat, openAskChat, openTopicChat, startRun } from "../src/harness/chats.ts";
import { appendActionLogEntry, appendMessage } from "../src/harness/transcript.ts";
import { queueWake } from "../src/harness/wakes.ts";
import { connectMonitor, readChat, readRunPrompt, readState } from "../src/monitor/queries.ts";
import { testEnv } from "./env.ts";
import { makeTopic } from "./fixtures.ts";
import { deps, signedUp, userIdOf } from "./helpers.ts";

/*
 * The run monitor (task 0045) shows every chat of the pipeline with what it is doing, its helpers
 * under it, and never AskAI's chats. It only reads: its connection refuses a write.
 */

const { db } = deps;
const monitor = connectMonitor(testEnv.DATABASE_URL ?? "");
afterAll(() => monitor.pool.end());

const schedule = { kind: "schedule" as const, schedule: "test" };
const triggers = [schedule];

describe("the run monitor", () => {
  test("shows a running chat, its helper and a woken chat, and hides AskAI", async () => {
    const { topic } = await makeTopic();
    const tadpole = await openTopicChat(db, "tadpole", topic.id);
    const writer = await newHelperChat(db, tadpole, "document_writer");
    const designer = await openTopicChat(db, "designer_toad", topic.id);
    const run = await startRun(db, {
      chatId: tadpole.id,
      model: "m",
      systemPrompt: "the instructions",
      triggers,
    });
    await appendMessage(db, run, { role: "user", content: "map the topic", timestamp: Date.now() });
    await appendActionLogEntry(db, {
      runId: run.id,
      toolCallId: "call_1",
      tool: "write_map",
      arguments: {},
      reasoning: "",
      result: { ok: true, value: null },
      dataSeen: [],
      recordsWritten: [],
    });
    await queueWake(db, { chatId: designer.id, trigger: schedule, dueAt: new Date(Date.now() + 60_000) });

    const userId = await userIdOf(await signedUp());
    const [thread] = await db
      .insert(askConversation)
      .values({ userId, topicId: topic.id })
      .returning({ id: askConversation.id });
    if (!thread) throw new Error("No thread.");
    const ask = await openAskChat(db, thread.id);
    const askRun = await startRun(db, { chatId: ask.id, model: "m", systemPrompt: "s", triggers });

    const state = await readState(monitor.db);
    const byId = new Map(state.chats.map((chat) => [chat.id, chat]));
    expect(byId.get(tadpole.id)).toMatchObject({
      role: "tadpole",
      topic: topic.canonicalName,
      runStatus: "running",
      messages: 1,
      lastTool: "write_map",
    });
    expect(byId.get(writer.id)).toMatchObject({
      role: "helper",
      task: "document_writer",
      parentId: tadpole.id,
    });
    expect(byId.get(designer.id)).toMatchObject({ waiting: 1, runStatus: null });
    expect(state.chats.some((chat) => chat.role === "ask_ai")).toBe(false);
    expect(state.topics.map((one) => one.id)).toContain(topic.id);

    const detail = await readChat(monitor.db, tadpole.id, 0, 0);
    expect(detail?.messages.map((row) => row.seq)).toEqual([1]);
    expect(detail?.runs.map((row) => row.status)).toEqual(["running"]);
    expect((await readChat(monitor.db, tadpole.id, 1, 0))?.messages).toEqual([]);
    expect(await readRunPrompt(monitor.db, run.id)).toBe("the instructions");

    expect(await readChat(monitor.db, ask.id, 0, 0)).toBeUndefined();
    expect(await readRunPrompt(monitor.db, askRun.id)).toBeUndefined();
    expect(await readChat(monitor.db, "not-a-chat", 0, 0)).toBeUndefined();

    await endRun(db, run.id, { status: "done" });
    await endRun(db, askRun.id, { status: "done" });
  });

  test("can't write", async () => {
    await expect(monitor.db.execute(sql`INSERT INTO chat (role) VALUES ('toad_sage')`)).rejects.toMatchObject(
      {
        cause: expect.objectContaining({ message: expect.stringMatching(/read-only transaction/) }),
      },
    );
  });
});
