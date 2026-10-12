import { resolve } from "node:path";
import { type AssistantMessage, contentText, type JsonObject, type Message } from "@spoin/pi-ai";
import { Type } from "typebox";
import { describe, expect, test } from "vitest";
import { type Chat, openTopicChat, type Run, startRun } from "../src/harness/chats.ts";
import { writeSummaryTool } from "../src/harness/compacting.ts";
import {
  type CompactionSettings,
  contextMessages,
  findSummary,
  summaryInForce,
} from "../src/harness/compaction.ts";
import { createRecord, refOf, revertRecord } from "../src/harness/records.ts";
import { CLOSED, CompactionSummaryRecord, Text, versionedRecord } from "../src/harness/schemas.ts";
import type { HarnessTool } from "../src/harness/tools.ts";
import { readTranscript } from "../src/harness/transcript.ts";
import { ContextOverflowError, wakeChat } from "../src/harness/wake-chat.ts";
import { loadPrompts, PROMPTS_DIRECTORY } from "../src/prompts.ts";
import { makeTopic } from "./fixtures.ts";
import { deps } from "./helpers.ts";
import { counted, reply, scriptedModel, TEST_MODEL } from "./scripted-model.ts";

/*
 * Compaction (task 0045, Phase 9): Trotter's `compaction.test.ts` on Postgres. The tadpole's own
 * instructions come later with the tadpole, so a stand-in template takes their place here.
 */

const { db } = deps;
const prompts = loadPrompts([resolve(import.meta.dirname, "fixtures/prompts"), PROMPTS_DIRECTORY]);
const MORNING = [{ kind: "schedule" as const, schedule: "every morning" }];
/** Low enough that a scripted answer's own count crosses it. */
const SMALL_LIMIT: CompactionSettings = { atTokens: 4_000, atWindowShare: 0.6 };

const SUMMARY = {
  soFar: "Read three sources on the borrow checker; drafted the coverage note.",
  learnings: ["The Rust book's chapter 4 is the clearest source on ownership."],
  feedback: [],
  dos: ["Cite the edition of every source."],
  donts: ["Don't quote forum answers as facts."],
  nextSteps: ["Send the coverage note to toad_sage."],
};

const Note = versionedRecord("note", Type.Object({ text: Text }, CLOSED));
const NoteArguments = Type.Object({ text: Text }, CLOSED);

const noteTool: HarnessTool<typeof NoteArguments> = {
  name: "write_note",
  label: "Write a note",
  description: "Stores a note.",
  parameters: NoteArguments,
  kind: "change",
  async execute(params, context) {
    const note = await createRecord(context.db, Note, { kind: "note", author: context.author, body: params });
    const ref = refOf(note);
    return { value: { stored: ref }, dataSeen: [], recordsWritten: [ref] };
  },
};

const text = (words: string): AssistantMessage => reply([{ type: "text", text: words }]);
const calls = (id: string, name: string, args: JsonObject): AssistantMessage =>
  reply([{ type: "toolCall", id, name, arguments: args }], "toolUse");

function wake(chat: Chat, script: AssistantMessage[], model = TEST_MODEL, compaction = SMALL_LIMIT) {
  const scripted = scriptedModel(script);
  const runs = wakeChat({
    db,
    prompts,
    chat,
    model,
    thinkingLevel: "off",
    triggers: MORNING,
    apiKey: "test-key",
    tools: [noteTool],
    compactionTools: [noteTool],
    compaction,
    streamFn: () => scripted.streamFn,
  });
  return { runs, requests: scripted.requests };
}

async function newChat(): Promise<Chat> {
  const { topic } = await makeTopic();
  return openTopicChat(db, "tadpole", topic.id);
}

/** A wake whose one answer leaves the chat's context past the limit. */
async function fillChat(chat: Chat): Promise<Run[]> {
  return wake(chat, [counted(text("Two sources to read tomorrow."), 5_000)]).runs;
}

function lastText(messages: Message[] | undefined): string {
  const last = messages?.at(-1);
  if (last?.role !== "user") throw new Error("The last message isn't the opening message.");
  return contentText(last.content);
}

describe("compaction", () => {
  test("a chat whose context reached the limit compacts before its run, then reads only its summary and what follows", async () => {
    const chat = await newChat();
    await fillChat(chat);

    const { runs, requests } = wake(chat, [
      calls("call-1", "write_summary", SUMMARY),
      text("Summary written."),
      text("Reading on."),
    ]);

    const [compaction, run] = await runs;
    expect(compaction?.triggers).toEqual([{ kind: "compaction", contextTokens: 5_000 }]);
    expect(lastText(requests[0])).toMatch(
      /Your chat has grown to about 5000 tokens, its limit, so it compacts now\./,
    );
    expect(run?.status).toBe("done");
    expect((await summaryInForce(db, chat))?.body.throughRun).toBe(compaction?.id);
    const [instructions, opening] = requests[2] ?? [];
    expect(requests[2]).toHaveLength(2);
    if (instructions?.role !== "system") throw new Error("The first message isn't the instructions.");
    expect(contentText(instructions.content)).toMatch(/## What you remember from earlier/);
    expect(contentText(instructions.content)).toMatch(/So far: Read three sources on the borrow checker/);
    expect(lastText(opening ? [opening] : [])).toMatch(
      /India time\. You were woken by:\n\nYour schedule: every morning\./,
    );
  });

  test("a run that fills the chat pauses at its next step boundary, compacts, and a new run carries it on", async () => {
    const chat = await newChat();

    const { runs, requests } = wake(chat, [
      counted(calls("call-1", "write_note", { text: "Ownership first." }), 5_000),
      calls("call-2", "write_summary", SUMMARY),
      text("Summary written."),
      text("Carrying on."),
    ]);

    const [paused, compaction, continuation] = await runs;
    expect([paused?.status, compaction?.status, continuation?.status]).toEqual(["paused", "done", "done"]);
    expect(compaction?.triggers[0]?.kind).toBe("compaction");
    expect(continuation?.triggers).toEqual([{ kind: "continuation", run: paused?.id }, ...MORNING]);
    expect(requests[3]).toHaveLength(2);
    const opening = lastText(requests[3]);
    expect(opening).toContain(`Your run ${paused?.id} paused when your chat reached its limit`);
    expect(opening).toMatch(/Before it paused, it stored: note [0-9a-f-]{36} version 1\./);
    expect(opening).toMatch(/Your schedule: every morning\./);
  });

  test("a compaction that writes no summary leaves the chat as it was, and the run goes ahead without pausing", async () => {
    const chat = await newChat();
    await fillChat(chat);

    const { runs, requests } = wake(chat, [
      text("Nothing to save."),
      counted(calls("call-1", "write_note", { text: "Still reading." }), 9_000),
      text("Still reading."),
    ]);

    expect((await runs).map((run) => [run.triggers[0]?.kind, run.status])).toEqual([
      ["compaction", "done"],
      ["schedule", "done"],
    ]);
    expect(await summaryInForce(db, chat)).toBeUndefined();
    expect(requests[1]?.some((message) => message.role === "assistant")).toBe(true);
  });

  test("undoing a summary takes the chat back to the earlier summary and the point it covers", async () => {
    const chat = await newChat();
    await fillChat(chat);
    const [firstCompaction, afterFirst] = await wake(chat, [
      calls("call-1", "write_summary", SUMMARY),
      text("Summary written."),
      counted(text("Reading on."), 6_000),
    ]).runs;
    await wake(chat, [
      calls("call-2", "write_summary", { ...SUMMARY, soFar: "Sent the coverage note." }),
      text("Summary written."),
      text("Waiting for the review."),
    ]).runs;
    const second = await findSummary(db, chat);
    expect(second?.version).toBe(2);
    if (!second) return;

    await revertRecord(db, CompactionSummaryRecord, {
      from: refOf(second),
      to: 1,
      author: { kind: "owner" },
      reason: "The second summary dropped the plan.",
    });

    expect((await summaryInForce(db, chat))?.body.throughRun).toBe(firstCompaction?.id);
    const firstAfterIt = (await readTranscript(db, chat.id)).find((entry) => entry.runId === afterFirst?.id);
    expect((await contextMessages(db, chat))[0]).toEqual(firstAfterIt?.message);
  });

  test("a summary longer than the limit is refused, so the model shortens it", async () => {
    const chat = await newChat();
    const run = await startRun(db, {
      chatId: chat.id,
      model: TEST_MODEL.id,
      triggers: MORNING,
      systemPrompt: "",
    });
    const context = {
      db,
      chat,
      run,
      author: { kind: "chat" as const, chatId: chat.id, runId: run.id, model: TEST_MODEL.id },
      signal: new AbortController().signal,
    };

    await expect(
      writeSummaryTool(prompts).execute({ ...SUMMARY, soFar: "x".repeat(10_000) }, context),
    ).rejects.toThrow(/keep it under 2000/);
    expect(await findSummary(db, chat)).toBeUndefined();
  });

  test("a chat whose context is bigger than its model's window neither runs nor compacts", async () => {
    const chat = await newChat();
    await fillChat(chat);

    await expect(
      wake(chat, [text("Never asked.")], { ...TEST_MODEL, contextWindow: 4_500 }).runs,
    ).rejects.toThrow(ContextOverflowError);
  });

  test("after a compaction that leaves no room under the limit, the run goes ahead instead of compacting again", async () => {
    const chat = await newChat();
    await fillChat(chat);
    // The instructions with the summary in them are over half of this.
    const tight = { atTokens: 200, atWindowShare: 0.6 };

    const { runs } = wake(
      chat,
      [
        calls("call-1", "write_summary", SUMMARY),
        text("Summary written."),
        counted(calls("call-2", "write_note", { text: "Still reading." }), 9_000),
        text("Still reading."),
      ],
      TEST_MODEL,
      tight,
    );

    expect((await runs).map((run) => [run.triggers[0]?.kind, run.status])).toEqual([
      ["compaction", "done"],
      ["schedule", "done"],
    ]);
  });
});
