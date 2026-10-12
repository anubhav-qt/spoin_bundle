import { setTimeout as sleep } from "node:timers/promises";
import type { StreamFn, ThinkingLevel } from "@spoin/pi-agent";
import type { Api, Model } from "@spoin/pi-ai";
import type { Db } from "../db/client.ts";
import type { Prompts } from "../prompts.ts";
import { type Chat, type Run, readChat } from "./chats.ts";
import type { CompactionSettings } from "./compaction.ts";
import { routeNewRecords } from "./routing.ts";
import type { HarnessTool } from "./tools.ts";
import { wakeChat } from "./wake-chat.ts";
import {
  chatsWithDueWakes,
  dueWakes,
  failWake,
  finishWake,
  returnWake,
  takeWake,
  type Wake,
} from "./wakes.ts";

/**
 * The scheduler (Trotter's `scheduler.ts`, ADR 0027): it routes each new record to the chats it's
 * for, and wakes each chat once with every wake due for it. Every chat with a wake due runs at once,
 * with no limit (task 0045).
 */

/** How often it looks for what's due, besides whenever a chat finishes. */
export const TICK_MS = 30_000;
/** A wake whose run failed is tried again this much later... */
export const RETRY_AFTER_MS = 15 * 60_000;
/** ...up to this many tries in all, then given up. */
export const MAX_TRIES = 3;

/** How a chat runs: its role's model, its tools, and how its model is called. */
export interface ChatSetUp {
  model: Model<Api>;
  thinkingLevel: ThinkingLevel;
  apiKey: string;
  tools: HarnessTool[];
  /** Those of its tools a compaction run stores with. */
  compactionTools: HarnessTool[];
  /** How the model is called, given each run. Tests pass a stand-in. */
  streamFn: (run: Run) => StreamFn;
}

export interface SchedulerInput {
  db: Db;
  prompts: Prompts;
  /** How each chat runs, by its role. */
  setUp: (chat: Chat) => ChatSetUp | Promise<ChatSetUp>;
  /** When chats compact; the defaults unless given. */
  compaction?: CompactionSettings;
  /** Stops the chats running, and wakes no more. */
  signal?: AbortSignal;
  /** The time now. Tests set it. */
  clock?: () => Date;
  /** Hears each chat wake and settle, and anything that went wrong. */
  onEvent?: (event: SchedulerEvent) => void;
}

/**
 * How a chat's runs went for its wakes:
 * - done: a run on them finished;
 * - failed: the last run failed, or the chat couldn't run at all;
 * - stopped: the harness stopped it, so they wait for its next start.
 */
export type Outcome = { kind: "done" } | { kind: "stopped" } | { kind: "failed"; error: string };

export type SchedulerEvent =
  | { type: "woke"; chat: Chat; wakes: Wake[] }
  | { type: "settled"; chat: Chat; runs: Run[]; outcome: Outcome; wakes: Wake[] }
  | { type: "error"; error: string };

export interface Scheduler {
  /** Routes new records and wakes every chat with wakes due. Ticks run one after another. */
  tick(): Promise<void>;
  /** Resolves once every chat woken so far has finished and its wakes are settled. */
  idle(): Promise<void>;
  /** Resolves when any chat running now finishes; never while none is. */
  nextFinish(): Promise<void>;
}

export function createScheduler(input: SchedulerInput): Scheduler {
  // The chats running now, each until its wakes are settled.
  const running = new Map<string, Promise<void>>();
  // Trotter's tick never overlaps another, being synchronous; on Postgres each waits for the last.
  let ticking: Promise<void> = Promise.resolve();
  return {
    tick: () => {
      ticking = ticking.then(() => tick(input, running));
      return ticking;
    },
    idle: async () => {
      await Promise.all(running.values());
    },
    nextFinish: async () => {
      await Promise.race(running.values());
    },
  };
}

/** Runs the scheduler until `signal` aborts, then waits for the chats running to stop and settle. */
export async function runScheduler(input: SchedulerInput): Promise<void> {
  const scheduler = createScheduler(input);
  while (!input.signal?.aborted) {
    await scheduler.tick();
    await nap(TICK_MS, scheduler.nextFinish(), input.signal);
  }
  await scheduler.idle();
}

async function tick(input: SchedulerInput, running: Map<string, Promise<void>>): Promise<void> {
  if (input.signal?.aborted) return;
  const now = nowOf(input);
  try {
    await routeNewRecords(input.db, now);
    await wakeDueChats(input, running, now);
  } catch (error) {
    // One bad look shouldn't stop the harness: say what went wrong, and look again next tick.
    report(input, { type: "error", error: messageOf(error) });
  }
}

async function wakeDueChats(
  input: SchedulerInput,
  running: Map<string, Promise<void>>,
  now: Date,
): Promise<void> {
  for (const chatId of await chatsWithDueWakes(input.db, now)) {
    if (running.has(chatId)) continue;
    const chat = await readChat(input.db, chatId);
    const wakes = await takeDueWakes(input.db, chatId, now);
    if (wakes.length === 0) continue;
    const finished = runOnWakes(input, chat, wakes).finally(() => running.delete(chatId));
    running.set(chatId, finished);
  }
}

function takeDueWakes(db: Db, chatId: string, now: Date): Promise<Wake[]> {
  return db.transaction(async (tx) => {
    const taken: Wake[] = [];
    for (const wake of await dueWakes(tx, chatId, now)) taken.push(await takeWake(tx, wake));
    return taken;
  });
}

/** Wakes the chat on its wakes, then settles them by how its runs went. */
async function runOnWakes(input: SchedulerInput, chat: Chat, wakes: Wake[]): Promise<void> {
  report(input, { type: "woke", chat, wakes });
  let runs: Run[] = [];
  let outcome: Outcome;
  try {
    runs = await wakeChat({
      ...(await input.setUp(chat)),
      db: input.db,
      prompts: input.prompts,
      chat,
      triggers: wakes.map((wake) => wake.trigger),
      compaction: input.compaction,
      signal: input.signal,
    });
    outcome = outcomeOf(runs);
  } catch (error) {
    // The chat couldn't run at all (its context too big for the model, say): a failed try like any other.
    outcome = { kind: "failed", error: messageOf(error) };
  }
  try {
    const settled = await settle(input.db, wakes, outcome, nowOf(input));
    report(input, { type: "settled", chat, runs, outcome, wakes: settled });
  } catch (error) {
    // Left taken, the wakes go back to waiting when the harness next starts.
    report(input, { type: "error", error: messageOf(error) });
  }
}

/** Done once a run on the wakes finished; failed if the last run failed; otherwise the harness stopped it. */
function outcomeOf(runs: Run[]): Outcome {
  const last = runs.at(-1);
  if (!last) return { kind: "stopped" };
  if (last.status === "failed")
    return { kind: "failed", error: last.error ?? "The run failed without saying why." };
  const compacting = last.triggers[0]?.kind === "compaction";
  if (last.status === "done" && !compacting) return { kind: "done" };
  return { kind: "stopped" };
}

function settle(db: Db, wakes: Wake[], outcome: Outcome, now: Date): Promise<Wake[]> {
  return db.transaction(async (tx) => {
    const settled: Wake[] = [];
    for (const wake of wakes) {
      if (outcome.kind === "done") settled.push(await finishWake(tx, wake));
      else if (outcome.kind === "stopped") settled.push(await returnWake(tx, wake));
      else settled.push(await failWake(tx, wake, outcome.error, retryTimeOf(wake, now)));
    }
    return settled;
  });
}

/** When to try a wake again after a failed run, or undefined once it has had all its tries. */
function retryTimeOf(wake: Wake, now: Date): Date | undefined {
  if (wake.tries + 1 >= MAX_TRIES) return undefined;
  return new Date(now.getTime() + RETRY_AFTER_MS);
}

/** Waits `ms`, or less if `early` resolves or `signal` aborts first. */
async function nap(ms: number, early: Promise<void>, signal: AbortSignal | undefined): Promise<void> {
  const woken = new AbortController();
  const wake = () => woken.abort();
  void early.then(wake);
  signal?.addEventListener("abort", wake, { once: true });
  try {
    await sleep(ms, undefined, { signal: woken.signal });
  } catch (error) {
    // Cut short on purpose, to look again sooner or to stop. Anything else is a real failure.
    if (!woken.signal.aborted) throw error;
  } finally {
    signal?.removeEventListener("abort", wake);
  }
}

function nowOf(input: SchedulerInput): Date {
  return input.clock ? input.clock() : new Date();
}

function report(input: SchedulerInput, event: SchedulerEvent): void {
  input.onEvent?.(event);
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
