import type { StreamFn } from "@spoin/pi-agent";
import { contentText, type Message } from "@spoin/pi-ai";
import { Type } from "typebox";
import { describe, expect, test } from "vitest";
import { openTopicChat } from "../src/harness/chats.ts";
import { createRecord, readRecord } from "../src/harness/records.ts";
import { type RunChatInput, runChat } from "../src/harness/run-chat.ts";
import { CLOSED, Text, versionedRecord } from "../src/harness/schemas.ts";
import type { HarnessTool } from "../src/harness/tools.ts";
import { readActionLog, readTranscript } from "../src/harness/transcript.ts";
import { makeTopic } from "./fixtures.ts";
import { deps } from "./helpers.ts";
import { counted, reply, scriptedModel, streamOf, TEST_MODEL } from "./scripted-model.ts";

/*
 * One run of a harness chat (task 0045, Phase 9): Trotter's `run-chat.test.ts` on Postgres, with
 * Seelie's tool calls (reads at once, changes in order) and the pause for compaction.
 */

const { db } = deps;

const Note = versionedRecord("note", Type.Object({ text: Text }, CLOSED));
const NoteArguments = Type.Object({ text: Text }, CLOSED);

/** A change for tests: it stores a note and says which record it wrote. */
function noteTool(
  calls: { count: number } = { count: 0 },
  events: string[] = [],
): HarnessTool<typeof NoteArguments> {
  return {
    name: "write_note",
    label: "Write a note",
    description: "Stores a note.",
    parameters: NoteArguments,
    kind: "change",
    async execute(params, context) {
      calls.count++;
      events.push(`start ${params.text}`);
      await new Promise((resolve) => setTimeout(resolve, 15));
      const note = await createRecord(context.db, Note, {
        kind: "note",
        author: context.author,
        body: params,
      });
      events.push(`end ${params.text}`);
      const ref = { kind: note.kind, id: note.id, version: note.version };
      return { value: { stored: ref }, dataSeen: [], recordsWritten: [ref] };
    },
  };
}

const PageArguments = Type.Object({ url: Text }, CLOSED);

/** A read for tests: it takes a while, like a page fetch. */
function pageTool(events: string[]): HarnessTool<typeof PageArguments> {
  return {
    name: "read_page",
    label: "Read a page",
    description: "Reads a page.",
    parameters: PageArguments,
    kind: "read",
    async execute(params) {
      events.push(`start ${params.url}`);
      await new Promise((resolve) => setTimeout(resolve, 30));
      events.push(`end ${params.url}`);
      return { value: `The page at ${params.url}.`, dataSeen: [], recordsWritten: [] };
    },
  };
}

async function setUp(streamFn: StreamFn, tools: HarnessTool[] = []): Promise<RunChatInput> {
  const { topic } = await makeTopic();
  return {
    db,
    chat: await openTopicChat(db, "tadpole", topic.id),
    model: TEST_MODEL,
    thinkingLevel: "off",
    triggers: [{ kind: "schedule", schedule: "every morning" }],
    systemPrompt: "You research this topic.",
    prompt: "It's morning.",
    tools,
    apiKey: "test-key",
    streamFn: () => streamFn,
  };
}

function textsOf(messages: readonly Message[]): string[] {
  return messages.map((message) => {
    if (message.role === "assistant") {
      return `${message.role}: ${contentText(message.content.filter((block) => block.type === "text"))}`;
    }
    return `${message.role}: ${contentText(message.content)}`;
  });
}

const transcriptOf = async (input: RunChatInput) =>
  (await readTranscript(db, input.chat.id)).map((entry) => entry.message);

describe("a run", () => {
  test("stores the whole exchange, keeps what the chat was told, and ends done", async () => {
    const model = scriptedModel([reply([{ type: "text", text: "Nothing new today." }])]);
    const input = await setUp(model.streamFn);

    const run = await runChat(input);

    expect(run.status).toBe("done");
    expect(run.systemPrompt).toBe("You research this topic.");
    expect(textsOf(await transcriptOf(input))).toEqual([
      "user: It's morning.",
      "assistant: Nothing new today.",
    ]);
    expect(textsOf(model.requests[0] ?? [])).toEqual([
      "system: You research this topic.",
      "user: It's morning.",
    ]);
  });

  test("logs every tool call with its arguments, the reasoning before it, its result and what it wrote", async () => {
    const model = scriptedModel([
      reply(
        [
          { type: "thinking", thinking: "The source says so." },
          { type: "text", text: "Writing it down." },
          { type: "toolCall", id: "call-1", name: "write_note", arguments: { text: "Cited" } },
        ],
        "toolUse",
      ),
      reply([{ type: "text", text: "Noted." }]),
    ]);
    const input = await setUp(model.streamFn, [noteTool()]);

    const run = await runChat(input);

    const [entry] = await readActionLog(db, run.id);
    expect(entry).toMatchObject({
      tool: "write_note",
      toolCallId: "call-1",
      arguments: { text: "Cited" },
      reasoning: "The source says so.\n\nWriting it down.",
      result: { ok: true },
    });
    const [written] = entry?.recordsWritten ?? [];
    if (!written) throw new Error("the call wrote nothing");
    const note = await readRecord(db, Note, written);
    expect(note.author).toEqual({ kind: "chat", chatId: input.chat.id, runId: run.id, model: TEST_MODEL.id });
    expect((await transcriptOf(input)).map((message) => message.role)).toEqual([
      "user",
      "assistant",
      "toolResult",
      "assistant",
    ]);
  });

  test("never runs a call whose arguments don't match, and gives the model every problem back", async () => {
    const calls = { count: 0 };
    const model = scriptedModel([
      reply(
        [{ type: "toolCall", id: "call-1", name: "write_note", arguments: { text: 5, mood: "sure" } }],
        "toolUse",
      ),
      reply([{ type: "text", text: "I'll fix it." }]),
    ]);
    const input = await setUp(model.streamFn, [noteTool(calls)]);

    const run = await runChat(input);

    expect(calls.count).toBe(0);
    const [entry] = await readActionLog(db, run.id);
    const toldModel = textsOf(model.requests[1] ?? []).at(-1) ?? "";
    for (const problem of ["text: must be string", 'unexpected field "mood"']) {
      expect(entry?.result).toMatchObject({ ok: false, error: expect.stringContaining(problem) });
      expect(toldModel).toContain(problem);
    }
  });

  test("runs a reply's reads at once and its changes one at a time, in the order asked", async () => {
    const events: string[] = [];
    const call = (id: string, name: string, args: Record<string, string>) => ({
      type: "toolCall" as const,
      id,
      name,
      arguments: args,
    });
    const model = scriptedModel([
      reply(
        [
          call("call-1", "read_page", { url: "a" }),
          call("call-2", "write_note", { text: "1" }),
          call("call-3", "read_page", { url: "b" }),
          call("call-4", "write_note", { text: "2" }),
        ],
        "toolUse",
      ),
      reply([{ type: "text", text: "Done." }]),
    ]);
    const input = await setUp(model.streamFn, [pageTool(events), noteTool({ count: 0 }, events)]);

    await runChat(input);

    const at = (event: string) => events.indexOf(event);
    expect(at("start b")).toBeLessThan(at("end a"));
    expect(at("start 1")).toBeLessThan(at("end a"));
    expect(at("end 1")).toBeLessThan(at("start 2"));
    // The model reads the results in the order it asked, however they finished.
    const results = (await transcriptOf(input)).filter((message) => message.role === "toolResult");
    expect(results.map((message) => message.toolCallId)).toEqual(["call-1", "call-2", "call-3", "call-4"]);
  });

  test("carries on from the chat's transcript in the next run", async () => {
    const first = scriptedModel([reply([{ type: "text", text: "Two sources to read tomorrow." }])]);
    const input = await setUp(first.streamFn);
    await runChat(input);
    const second = scriptedModel([reply([{ type: "text", text: "Read them." }])]);

    await runChat({ ...input, prompt: "It's the next morning.", streamFn: () => second.streamFn });

    expect(textsOf(second.requests[0] ?? [])).toEqual([
      "system: You research this topic.",
      "user: It's morning.",
      "assistant: Two sources to read tomorrow.",
      "user: It's the next morning.",
    ]);
  });

  test("ends failed on a model error, with the error kept", async () => {
    const model = scriptedModel([reply([], "error", "Gemini turned the call away.")]);
    const run = await runChat(await setUp(model.streamFn));

    expect(run).toMatchObject({ status: "failed", error: "Gemini turned the call away." });
  });

  test("ends stopped when it's stopped, and the stop reaches the model call", async () => {
    const controller = new AbortController();
    const streamFn: StreamFn = (_model, _context, options) => {
      controller.abort();
      return streamOf(reply([], options?.signal?.aborted ? "aborted" : "stop"));
    };
    const input = await setUp(streamFn);

    const run = await runChat({ ...input, signal: controller.signal });

    expect(run.status).toBe("stopped");
  });

  test("pauses at the step after its chat's context reaches the limit, so the chat can compact", async () => {
    const model = scriptedModel([
      counted(
        reply(
          [{ type: "toolCall", id: "call-1", name: "write_note", arguments: { text: "Cited" } }],
          "toolUse",
        ),
        5_000,
      ),
      reply([{ type: "text", text: "Going on." }]),
    ]);
    const input = await setUp(model.streamFn, [noteTool()]);

    const run = await runChat({ ...input, pauseAtTokens: 4_000 });

    expect(run.status).toBe("paused");
    expect(model.requests).toHaveLength(1);
    expect(await readActionLog(db, run.id)).toHaveLength(1);
  });
});
