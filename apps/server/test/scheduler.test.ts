import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { type AssistantMessage, contentText, type Message } from "@spoin/pi-ai";
import type { WakeStatus } from "@spoin/shared/enums";
import { inArray } from "drizzle-orm";
import { Type } from "typebox";
import { beforeEach, describe, expect, test } from "vitest";
import { wake as wakeTable } from "../src/db/schema.ts";
import { type Chat, listRuns, openChat, openTopicChat } from "../src/harness/chats.ts";
import { changeRecord, createRecord, refOf } from "../src/harness/records.ts";
import { routeNewRecords } from "../src/harness/routing.ts";
import {
  createScheduler,
  MAX_TRIES,
  RETRY_AFTER_MS,
  runScheduler,
  type SchedulerEvent,
  type SchedulerInput,
} from "../src/harness/scheduler.ts";
import {
  AnswerRecord,
  type Author,
  CLOSED,
  CompactionSummaryRecord,
  QuestionRecord,
  Text,
  versionedRecord,
} from "../src/harness/schemas.ts";
import { listWakes, queueWake } from "../src/harness/wakes.ts";
import { loadPrompts, PROMPTS_DIRECTORY } from "../src/prompts.ts";
import { makeTopic } from "./fixtures.ts";
import { deps } from "./helpers.ts";
import { reply, scriptedModel, TEST_MODEL } from "./scripted-model.ts";

/*
 * The scheduler (task 0045, Phase 9): Trotter's `scheduler.test.ts` on Postgres, without the
 * trader chats' plans and schedules, and with every chat that has a wake due running at once.
 */

const { db } = deps;
const prompts = loadPrompts([resolve(import.meta.dirname, "fixtures/prompts"), PROMPTS_DIRECTORY]);
const MORNING = { kind: "schedule" as const, schedule: "every morning" };
/** Monday 12 October 2026, 11:30 in India. */
const MONDAY_MORNING = new Date("2026-10-12T06:00:00Z");

const Note = versionedRecord("note", Type.Object({ text: Text }, CLOSED));

beforeEach(async () => {
  // Each test sees only its own wakes: the records other tests left are routed, and every wake still to run is dropped.
  await routeNewRecords(db, new Date());
  await db
    .update(wakeTable)
    .set({ status: "dropped" })
    .where(inArray(wakeTable.status, ["waiting", "taken"]));
});

function chatAuthor(chat: Chat): Author {
  return { kind: "chat", chatId: chat.id, runId: randomUUID(), model: TEST_MODEL.id };
}

const text = (words: string): AssistantMessage => reply([{ type: "text", text: words }]);

function minutesAfter(moment: Date, minutes: number): Date {
  return new Date(moment.getTime() + minutes * 60_000);
}

async function newTadpole(): Promise<Chat> {
  const { topic } = await makeTopic();
  return openTopicChat(db, "tadpole", topic.id);
}

/** The chats the waiting wakes are for, by id, with the kind of each one's trigger. */
async function waiting(): Promise<{ chatId: string; trigger: string }[]> {
  return (await listWakes(db, "waiting")).map((wake) => ({
    chatId: wake.chatId,
    trigger: wake.trigger.kind === "record" ? wake.trigger.record.kind : wake.trigger.schedule,
  }));
}

/** The wakes with this status for these chats: other tests' finished wakes stay in the table. */
async function wakesOf(status: WakeStatus, ...chats: Chat[]) {
  const ids = new Set(chats.map((chat) => chat.id));
  return (await listWakes(db, status)).filter((wake) => ids.has(wake.chatId));
}

function lastText(messages: Message[] | undefined): string {
  const last = messages?.at(-1);
  if (last?.role !== "user") throw new Error("The last message isn't the opening message.");
  return contentText(last.content);
}

/** A scheduler's input on a scripted model. */
function inputFor(script: AssistantMessage[], clock: () => Date) {
  const scripted = scriptedModel(script);
  const events: SchedulerEvent[] = [];
  const input: SchedulerInput = {
    db,
    prompts,
    setUp: () => ({
      model: TEST_MODEL,
      thinkingLevel: "off",
      apiKey: "test-key",
      tools: [],
      compactionTools: [],
      streamFn: () => scripted.streamFn,
    }),
    clock,
    onEvent: (event) => events.push(event),
  };
  return { input, events, requests: scripted.requests };
}

/** A scheduler on a scripted model, at a time the test moves on. */
function schedulerFor(script: AssistantMessage[]) {
  const clock = { now: MONDAY_MORNING };
  const { input, events, requests } = inputFor(script, () => clock.now);
  return { scheduler: createScheduler(input), clock, events, requests };
}

function woke(events: SchedulerEvent[]): string[] {
  return events.flatMap((event) => (event.type === "woke" ? [event.chat.id] : []));
}

describe("routing", () => {
  test("a question wakes the chat it asks, and the answer wakes the chat that asked", async () => {
    const tadpole = await newTadpole();
    const question = await createRecord(db, QuestionRecord, {
      kind: "question",
      author: chatAuthor(tadpole),
      body: {
        to: { role: "toad_sage" },
        question: "Is the coverage note enough?",
        reasoning: "It's my first.",
      },
    });

    await routeNewRecords(db, MONDAY_MORNING);
    const toadSage = await openChat(db, "toad_sage");
    expect(await waiting()).toEqual([{ chatId: toadSage.id, trigger: "question" }]);

    await createRecord(db, AnswerRecord, {
      kind: "answer",
      author: chatAuthor(toadSage),
      body: { question: refOf(question), answer: "Not yet: it names no sources." },
    });
    await routeNewRecords(db, MONDAY_MORNING);

    expect(await waiting()).toEqual([
      { chatId: toadSage.id, trigger: "question" },
      { chatId: tadpole.id, trigger: "answer" },
    ]);
  });

  test("an answer to a question the owner asked, a summary, and a kind no chat reads wake no one", async () => {
    const tadpole = await newTadpole();
    const question = await createRecord(db, QuestionRecord, {
      kind: "question",
      author: { kind: "owner" },
      body: {
        to: { role: "tadpole", topic: tadpole.topicId ?? "" },
        question: "Why?",
        reasoning: "Curious.",
      },
    });
    await routeNewRecords(db, MONDAY_MORNING);
    await createRecord(db, AnswerRecord, {
      kind: "answer",
      author: chatAuthor(tadpole),
      body: { question: refOf(question), answer: "Because." },
    });
    await createRecord(db, CompactionSummaryRecord, {
      kind: "compaction_summary",
      author: chatAuthor(tadpole),
      body: {
        chatId: tadpole.id,
        throughRun: randomUUID(),
        soFar: "Read one source.",
        learnings: [],
        feedback: [],
        dos: [],
        donts: [],
        nextSteps: [],
      },
    });
    await createRecord(db, Note, { kind: "note", author: chatAuthor(tadpole), body: { text: "A note." } });

    await routeNewRecords(db, MONDAY_MORNING);

    expect(await waiting()).toEqual([{ chatId: tadpole.id, trigger: "question" }]);
  });

  test("a record wakes its chats once, and a later version of it wakes no one", async () => {
    const tadpole = await newTadpole();
    const body = { to: { role: "toad_sage" as const }, question: "Which sources?", reasoning: "To start." };
    const question = await createRecord(db, QuestionRecord, {
      kind: "question",
      author: chatAuthor(tadpole),
      body,
    });

    await routeNewRecords(db, MONDAY_MORNING);
    await changeRecord(db, QuestionRecord, {
      from: refOf(question),
      status: "retired",
      author: { kind: "owner" },
      reason: "Asked twice.",
      body,
    });
    await routeNewRecords(db, MONDAY_MORNING);
    await routeNewRecords(db, MONDAY_MORNING);

    expect(await listWakes(db, "waiting")).toHaveLength(1);
  });

  test("a record that commits after a later one is still routed", async () => {
    const [early, late] = [await newTadpole(), await newTadpole()];
    const ask = (chat: Chat) =>
      ({
        kind: "question",
        author: chatAuthor(chat),
        body: {
          to: { role: "tadpole", topic: chat.topicId ?? "" },
          question: "Which sources?",
          reasoning: "To start.",
        },
      }) as const;

    await db.transaction(async (tx) => {
      // Numbered first, committed last.
      await createRecord(tx, QuestionRecord, ask(early));
      await createRecord(db, QuestionRecord, ask(late));
      await routeNewRecords(db, MONDAY_MORNING);
    });
    await routeNewRecords(db, MONDAY_MORNING);

    expect(await waiting()).toEqual([
      { chatId: late.id, trigger: "question" },
      { chatId: early.id, trigger: "question" },
    ]);
  });
});

describe("the scheduler", () => {
  test("a chat wakes once with every wake due for it, and they're done when its run is", async () => {
    const tadpole = await newTadpole();
    const { scheduler, events, requests } = schedulerFor([text("Nothing to do.")]);
    const anHour = { kind: "schedule" as const, schedule: "an hour" };
    await queueWake(db, { chatId: tadpole.id, trigger: MORNING, dueAt: minutesAfter(MONDAY_MORNING, -60) });
    await queueWake(db, { chatId: tadpole.id, trigger: anHour, dueAt: minutesAfter(MONDAY_MORNING, -15) });
    await queueWake(db, { chatId: tadpole.id, trigger: MORNING, dueAt: minutesAfter(MONDAY_MORNING, 60) });

    await scheduler.tick();
    await scheduler.idle();

    expect(woke(events)).toEqual([tadpole.id]);
    const [run] = await listRuns(db, tadpole.id);
    expect(run?.triggers).toEqual([MORNING, anHour]);
    expect(lastText(requests[0])).toMatch(/Your schedule: every morning\.\n\nYour schedule: an hour\./);
    expect(await wakesOf("done", tadpole)).toHaveLength(2);
    expect(await wakesOf("waiting", tadpole)).toHaveLength(1);
  });

  test("a question routed in a tick wakes the chat it asks in the same tick", async () => {
    const [asker, asked] = [await newTadpole(), await newTadpole()];
    await createRecord(db, QuestionRecord, {
      kind: "question",
      author: chatAuthor(asker),
      body: {
        to: { role: "tadpole", topic: asked.topicId ?? "" },
        question: "Which sources?",
        reasoning: "To start.",
      },
    });
    const { scheduler, events, requests } = schedulerFor([text("I don't know yet.")]);

    await scheduler.tick();
    await scheduler.idle();

    expect(woke(events)).toEqual([asked.id]);
    expect(lastText(requests[0])).toMatch(/A question for you\./);
  });

  test("a wake whose run failed is tried again later, and given up after its last try", async () => {
    const tadpole = await newTadpole();
    const { scheduler, clock, events } = schedulerFor([]);
    await queueWake(db, { chatId: tadpole.id, trigger: MORNING, dueAt: MONDAY_MORNING });
    const retryMinutes = RETRY_AFTER_MS / 60_000;

    for (let attempt = 1; attempt <= MAX_TRIES; attempt++) {
      await scheduler.tick();
      await scheduler.idle();
      clock.now = minutesAfter(clock.now, retryMinutes - 1);
      await scheduler.tick();
      await scheduler.idle();
      clock.now = minutesAfter(clock.now, 2);
    }

    expect(woke(events)).toHaveLength(MAX_TRIES);
    const [givenUp] = await wakesOf("given_up", tadpole);
    expect(givenUp?.tries).toBe(MAX_TRIES);
    expect(givenUp?.error).toBe("The script has no more replies.");
  });

  test("every chat with a wake due runs at once", async () => {
    const chats = [await newTadpole(), await newTadpole(), await newTadpole()];
    const { scheduler, events } = schedulerFor([text("Done."), text("Done."), text("Done.")]);
    for (const chat of chats)
      await queueWake(db, { chatId: chat.id, trigger: MORNING, dueAt: MONDAY_MORNING });

    await scheduler.tick();
    expect(new Set(woke(events))).toEqual(new Set(chats.map((chat) => chat.id)));
    await scheduler.idle();

    expect(await wakesOf("done", ...chats)).toHaveLength(3);
  });

  test("a wake that comes while its chat runs waits for the chat's next run", async () => {
    const tadpole = await newTadpole();
    const { scheduler, events } = schedulerFor([text("Done."), text("Done again.")]);
    await queueWake(db, { chatId: tadpole.id, trigger: MORNING, dueAt: MONDAY_MORNING });

    await scheduler.tick();
    await queueWake(db, { chatId: tadpole.id, trigger: MORNING, dueAt: MONDAY_MORNING });
    await scheduler.tick();
    expect(woke(events)).toEqual([tadpole.id]);
    await scheduler.idle();
    await scheduler.tick();
    await scheduler.idle();

    expect(woke(events)).toEqual([tadpole.id, tadpole.id]);
    expect(await wakesOf("done", tadpole)).toHaveLength(2);
  });

  test("a chat stopped before it finished wakes again on the same wakes, with no try used", async () => {
    const tadpole = await newTadpole();
    const { scheduler } = schedulerFor([reply([], "aborted")]);
    const wake = await queueWake(db, { chatId: tadpole.id, trigger: MORNING, dueAt: MONDAY_MORNING });

    await scheduler.tick();
    await scheduler.idle();

    expect(await listWakes(db, "waiting")).toEqual([wake]);
    expect((await listRuns(db, tadpole.id))[0]?.status).toBe("stopped");
  });

  test("the harness's scheduler wakes what's due as soon as it starts, and stops when told to", async () => {
    const tadpole = await newTadpole();
    await queueWake(db, { chatId: tadpole.id, trigger: MORNING, dueAt: MONDAY_MORNING });
    const stop = new AbortController();
    const { input } = inputFor([text("Nothing to do.")], () => MONDAY_MORNING);

    await runScheduler({
      ...input,
      signal: stop.signal,
      onEvent: (event) => {
        if (event.type === "settled") stop.abort();
      },
    });

    expect(await wakesOf("done", tadpole)).toHaveLength(1);
  });
});
