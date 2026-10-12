import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import type { StreamFn } from "@spoin/pi-agent";
import {
  type AssistantMessage,
  type AssistantMessageEventStream,
  contentText,
  createAssistantMessageEventStream,
  type JsonObject,
  type Message,
} from "@spoin/pi-ai";
import type { AskEventOut } from "@spoin/shared";
import { eq, sql } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import type { AskTurn } from "../src/ask/chat.ts";
import { type HarnessAskChatOptions, harnessAskChat } from "../src/ask/harness-chat.ts";
import { answer, reset } from "../src/ask/service.ts";
import { type TopicTools, topicTools } from "../src/ask/tools.ts";
import {
  actionLog,
  appUser,
  askConversation,
  chat,
  chatMessage,
  chatRun,
  modelCall,
} from "../src/db/schema.ts";
import { type Chat, listRuns, openTopicChat, readChat } from "../src/harness/chats.ts";
import { createRecord, refOf } from "../src/harness/records.ts";
import { CompactionSummaryRecord } from "../src/harness/schemas.ts";
import { readActionLog, readTranscript } from "../src/harness/transcript.ts";
import { recordTo } from "../src/models/calls.ts";
import { loadPrompts, PROMPTS_DIRECTORY } from "../src/prompts.ts";
import { makeTopic } from "./fixtures.ts";
import { deps, signedUp, userIdOf } from "./helpers.ts";
import { reply, scriptedModel, TEST_MODEL } from "./scripted-model.ts";

/*
 * AskAI's chat on the harness (task 0045, Phase 9): a reader's thread is an `ask_ai` chat and each
 * turn a run of it, everything it writes streamed as it's written, against the real database with
 * a scripted model. Deleting a reader deletes their AskAI chats, and nothing else of the harness.
 */

const { db } = deps;
const prompts = loadPrompts([resolve(import.meta.dirname, "fixtures/prompts"), PROMPTS_DIRECTORY]);

const text = (words: string): AssistantMessage => reply([{ type: "text", text: words }]);
const calls = (id: string, name: string, args: JsonObject, words = ""): AssistantMessage =>
  reply(
    [
      ...(words ? [{ type: "text" as const, text: words }] : []),
      { type: "toolCall", id, name, arguments: args },
    ],
    "toolUse",
  );

/** An answer written a few words at a time, as Gemini streams one. */
function typed(parts: string[]): AssistantMessageEventStream {
  const stream = createAssistantMessageEventStream();
  const message = text(parts.join(""));
  const partial = { ...message, content: [] };
  stream.push({ type: "start", partial });
  stream.push({ type: "text_start", contentIndex: 0, partial });
  for (const delta of parts) stream.push({ type: "text_delta", contentIndex: 0, delta, partial });
  stream.push({ type: "text_end", contentIndex: 0, content: parts.join(""), partial });
  stream.push({ type: "done", reason: "stop", message });
  stream.end();
  return stream;
}

function chatOn(streamFn: StreamFn, overrides: Partial<HarnessAskChatOptions> = {}) {
  return harnessAskChat({
    db,
    prompts,
    model: async () => TEST_MODEL,
    thinkingLevel: "off",
    apiKey: "test-key",
    streamFn: () => streamFn,
    ...overrides,
  });
}

/** A reader with a thread on a new topic, and that topic's tools. */
async function thread() {
  const made = await makeTopic();
  const userId = await userIdOf(await signedUp());
  const [conversation] = await db
    .insert(askConversation)
    .values({ userId, topicId: made.topic.id })
    .returning({ id: askConversation.id });
  if (!conversation) throw new Error("No thread.");
  const tools = topicTools(deps, made.topic.id, { searchLimit: 3 });
  const turn = (question: string, overrides: Partial<AskTurn> = {}): AskTurn => ({
    conversationId: conversation.id,
    question,
    card: null,
    tools,
    ...overrides,
  });
  return { ...made, userId, conversationId: conversation.id, tools, turn };
}

async function askChatOf(conversationId: string): Promise<Chat> {
  const [found] = await db.select().from(chat).where(eq(chat.askConversationId, conversationId));
  if (!found) throw new Error("No AskAI chat.");
  return found;
}

async function collect(chunks: AsyncIterable<string>): Promise<string[]> {
  const all: string[] = [];
  for await (const chunk of chunks) all.push(chunk);
  return all;
}

function opening(messages: Message[] | undefined): string {
  const last = messages?.at(-1);
  if (last?.role !== "user") throw new Error("The last message isn't the reader's.");
  return contentText(last.content);
}

describe("AskAI's chat", () => {
  test("a turn is a run of the thread's own chat, and its answer streams as it's written", async () => {
    const { topic, conversationId, turn } = await thread();
    const requests: Message[][] = [];
    const streamFn: StreamFn = (_model, context) => {
      requests.push([...context.messages]);
      return typed(["Ownership ", "moves ", "values."]);
    };

    const chunks = await collect(chatOn(streamFn).turn(turn("What is ownership?")));

    expect(chunks).toEqual(["Ownership ", "moves ", "values."]);
    const askChat = await askChatOf(conversationId);
    expect(askChat.role).toBe("ask_ai");
    const [run] = await listRuns(db, askChat.id);
    expect(run?.triggers).toEqual([{ kind: "reader", question: "What is ownership?", card: null }]);
    expect(run?.status).toBe("done");
    expect(run?.systemPrompt).toContain(`You answer a reader's questions about ${topic.canonicalName}.`);
    expect(opening(requests[0])).toMatch(/The reader asks: What is ownership\?/);
  });

  test("the chat reads the topic through its tools, and each message it writes is a paragraph", async () => {
    const { conversationId, turn, cards } = await thread();
    const scripted = scriptedModel([
      calls("call-1", "read", { card_ids: [cards[0]?.id ?? ""] }, "Let me read the card."),
      text("It says so."),
    ]);

    const chunks = await collect(chatOn(scripted.streamFn).turn(turn("What does the first card say?")));

    expect(chunks.join("")).toBe("Let me read the card.\n\nIt says so.");
    const [run] = await listRuns(db, (await askChatOf(conversationId)).id);
    const [entry] = await readActionLog(db, run?.id ?? "");
    expect(entry).toMatchObject({ tool: "read", reasoning: "Let me read the card.", result: { ok: true } });
  });

  test("a tool that fails for any other reason than a wrong call gives the chat one short line", async () => {
    const { conversationId, turn, tools } = await thread();
    const broken: TopicTools = {
      ...tools,
      search: async () => {
        throw new Error("connection to the database lost");
      },
    };
    const scripted = scriptedModel([calls("call-1", "search", { query: "ownership" }), text("No luck.")]);

    await collect(chatOn(scripted.streamFn).turn(turn("Anything on ownership?", { tools: broken })));

    const [run] = await listRuns(db, (await askChatOf(conversationId)).id);
    const [entry] = await readActionLog(db, run?.id ?? "");
    expect(entry?.result).toEqual({
      ok: false,
      error: "search failed. Call it again, or answer from what you have.",
    });
  });

  test("the card the reader is on is in their message", async () => {
    const { turn, cards } = await thread();
    const [card] = cards;
    if (!card) throw new Error("No card.");
    const scripted = scriptedModel([text("That card is about ownership.")]);

    await collect(
      chatOn(scripted.streamFn).turn(turn("What is this about?", { card: { ...card, body: card.body } })),
    );

    expect(opening(scripted.requests[0])).toContain(`They are on the card "${card.title}".`);
  });

  test("the chat remembers the thread so far, so the server never sends it again", async () => {
    const { turn } = await thread();
    const scripted = scriptedModel([text("Ownership moves values."), text("Borrowing lends them.")]);
    const askAi = chatOn(scripted.streamFn);

    await collect(askAi.turn(turn("What is ownership?")));
    await collect(askAi.turn(turn("And borrowing?")));

    const second = scripted.requests[1] ?? [];
    expect(second.map((message) => message.role)).toEqual(["system", "user", "assistant", "user"]);
    expect(opening(second)).toMatch(/The reader asks: And borrowing\?/);
  });

  test("a turn whose model fails throws, so the server says it failed", async () => {
    const { turn } = await thread();
    const scripted = scriptedModel([]);

    await expect(collect(chatOn(scripted.streamFn).turn(turn("What is ownership?")))).rejects.toThrow(
      "The script has no more replies.",
    );
  });

  test("a refused turn is the server's, and the next turn runs on the same chat", async () => {
    const { topic, userId, conversationId } = await thread();
    const scripted = scriptedModel([text("OFF_TOPIC"), text("Ownership moves values.")]);
    const askChat = chatOn(scripted.streamFn);
    const ask = async (question: string) => {
      const events: AskEventOut[] = [];
      const asked = { id: topic.id, name: topic.canonicalName };
      for await (const event of answer({ ...deps, askChat }, userId, asked, question, null))
        events.push(event);
      return events;
    };

    expect((await ask("What's the weather?")).map((event) => event.event)).toEqual(["off_topic"]);
    expect((await ask("What is ownership?")).map((event) => event.event)).toEqual(["delta", "done"]);
    expect(await listRuns(db, (await askChatOf(conversationId)).id)).toHaveLength(2);
  });

  test("starting over gives the reader a new chat", async () => {
    const { topic, userId, conversationId, turn } = await thread();
    const scripted = scriptedModel([text("One."), text("Two.")]);
    const askAi = chatOn(scripted.streamFn);
    await collect(askAi.turn(turn("First?")));

    await reset(db, userId, topic.id);
    const [fresh] = await db
      .insert(askConversation)
      .values({ userId, topicId: topic.id })
      .returning({ id: askConversation.id });
    await collect(askAi.turn(turn("Again?", { conversationId: fresh?.id ?? "" })));

    expect((await askChatOf(fresh?.id ?? "")).id).not.toBe((await askChatOf(conversationId)).id);
    expect(scripted.requests[1]?.map((message) => message.role)).toEqual(["system", "user"]);
  });
});

describe("deleting a reader", () => {
  test("deletes their AskAI chats with their runs, transcript, action log and summaries, and keeps the calls' rows", async () => {
    const { userId, conversationId, turn } = await thread();
    const scripted = scriptedModel([calls("call-1", "outline", {}), text("Here's the outline.")]);
    await collect(chatOn(scripted.streamFn).turn(turn("What's in this topic?")));
    const askChat = await askChatOf(conversationId);
    const [run] = await listRuns(db, askChat.id);
    if (!run) throw new Error("No run.");
    const summary = await createRecord(db, CompactionSummaryRecord, {
      kind: "compaction_summary",
      author: { kind: "chat", chatId: askChat.id, runId: run.id, model: TEST_MODEL.id },
      body: {
        chatId: askChat.id,
        throughRun: run.id,
        soFar: "The reader asked what's in the topic.",
        learnings: [],
        feedback: [],
        dos: [],
        donts: [],
        nextSteps: [],
      },
    });
    recordTo(db, run.id)(TEST_MODEL, {
      message: text("Here's the outline."),
      startedAt: new Date(),
      firstTokenMs: 1,
      totalMs: 2,
      failure: null,
      reason: null,
      abandoned: false,
    });
    await expect
      .poll(async () => (await db.select().from(modelCall).where(eq(modelCall.runId, run.id))).length)
      .toBe(1);

    await db.delete(appUser).where(eq(appUser.id, userId));

    expect(await db.select().from(chat).where(eq(chat.id, askChat.id))).toEqual([]);
    expect(await db.select().from(chatRun).where(eq(chatRun.chatId, askChat.id))).toEqual([]);
    expect(await db.select().from(chatMessage).where(eq(chatMessage.chatId, askChat.id))).toEqual([]);
    expect(await db.select().from(actionLog).where(eq(actionLog.runId, run.id))).toEqual([]);
    const summaries = await db.execute(sql`SELECT 1 FROM harness_record WHERE id = ${summary.id}`);
    expect(summaries.rows).toEqual([]);
    const [kept] = await db
      .select()
      .from(modelCall)
      .where(sql`${modelCall.model} = ${TEST_MODEL.id} AND ${modelCall.runId} IS NULL`);
    expect(kept).toBeDefined();
    expect(refOf(summary).kind).toBe("compaction_summary");
  });

  test("leaves every other chat's runs, transcript and action log as they were", async () => {
    const { topic } = await makeTopic();
    const tadpole = await openTopicChat(db, "tadpole", topic.id);
    const { conversationId, turn } = await thread();
    await collect(chatOn(scriptedModel([text("Hello.")]).streamFn).turn(turn("Hi?")));
    const askChat = await askChatOf(conversationId);
    const [run] = await listRuns(db, askChat.id);

    await expect(db.delete(chat).where(eq(chat.id, tadpole.id))).rejects.toMatchObject({
      cause: expect.objectContaining({
        message: expect.stringMatching(/Only an AskAI chat is ever deleted/),
      }),
    });
    await expect(db.delete(chatRun).where(eq(chatRun.id, run?.id ?? randomUUID()))).rejects.toMatchObject({
      cause: expect.objectContaining({ message: expect.stringMatching(/deleted only with its AskAI chat/) }),
    });
    await expect(db.delete(chatMessage).where(eq(chatMessage.chatId, askChat.id))).rejects.toMatchObject({
      cause: expect.objectContaining({ message: expect.stringMatching(/only ever added to/) }),
    });
    expect(await readChat(db, tadpole.id)).toEqual(tadpole);
    expect(await readTranscript(db, askChat.id)).toHaveLength(2);
  });
});
