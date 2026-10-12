import type { AgentEvent, StreamFn, ThinkingLevel } from "@spoin/pi-agent";
import type { Api, Model } from "@spoin/pi-ai";
import type { Db } from "../db/client.ts";
import type { Prompts } from "../prompts.ts";
import type { Chat, Run } from "./chats.ts";
import { writeSummaryTool } from "./compacting.ts";
import {
  COMPACTION_SETTINGS,
  type CompactionSettings,
  compactionLimit,
  contextMessages,
  contextTokens,
  summaryInForce,
} from "./compaction.ts";
import { openingMessageFor, systemPromptFor } from "./instructions.ts";
import { runChat } from "./run-chat.ts";
import type { RunTrigger } from "./schemas.ts";
import type { HarnessTool } from "./tools.ts";

export interface WakeChatInput {
  db: Db;
  prompts: Prompts;
  chat: Chat;
  model: Model<Api>;
  thinkingLevel: ThinkingLevel;
  triggers: RunTrigger[];
  apiKey: string;
  /** The chat's tools. */
  tools: HarnessTool[];
  /** Those of its tools a compaction run stores with: none that start or decide anything. write_summary is added. */
  compactionTools: HarnessTool[];
  /** When the chat compacts; the defaults unless given. */
  compaction?: CompactionSettings;
  /** How the model is called, given each run. Tests pass a stand-in. */
  streamFn: (run: Run) => StreamFn;
  /** Stops the run going, and wakes no more. */
  signal?: AbortSignal;
  /** Hears every event of every run once it's stored, with the run it's from. */
  onEvent?: (event: AgentEvent, run: Run) => void;
}

/** A chat whose context is bigger than its model's window can neither run nor compact on that model. */
export class ContextOverflowError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ContextOverflowError";
  }
}

/**
 * Wakes a chat (Trotter's `wake-chat.ts`, ADR 0014): if its context has reached the limit, it
 * compacts first, then it runs. A run that reaches the limit pauses at its next step boundary; the
 * chat compacts, and a continuation run carries it on. Returns every run, in order.
 */
export async function wakeChat(input: WakeChatInput): Promise<Run[]> {
  const limit = compactionLimit(input.model, input.compaction ?? COMPACTION_SETTINGS);
  const runs: Run[] = [];
  let pauseAtTokens: number | undefined = limit;
  if ((await currentContextTokens(input)) >= limit) {
    const compaction = await compact(input);
    runs.push(compaction.run);
    pauseAtTokens = await pauseAfter(input, compaction.wroteSummary, limit);
  }
  if (input.signal?.aborted) return runs;
  let run = await runOnce(input, input.triggers, input.tools, pauseAtTokens);
  runs.push(run);
  while (run.status === "paused" && !input.signal?.aborted) {
    const compaction = await compact(input);
    runs.push(compaction.run);
    const pauseAt = await pauseAfter(input, compaction.wroteSummary, limit);
    run = await runOnce(input, continuationOf(run), input.tools, pauseAt);
    runs.push(run);
  }
  return runs;
}

/** A run of the chat with these tools; it pauses at `pauseAtTokens` when given. */
async function runOnce(
  input: WakeChatInput,
  triggers: RunTrigger[],
  tools: HarnessTool[],
  pauseAtTokens: number | undefined,
): Promise<Run> {
  const { db, prompts, chat, model } = input;
  checkFitsWindow(model, chat, await currentContextTokens(input));
  return runChat({
    db,
    chat,
    model,
    thinkingLevel: input.thinkingLevel,
    triggers,
    systemPrompt: await systemPromptFor(db, prompts, chat),
    prompt: await openingMessageFor(db, prompts, chat, triggers, new Date()),
    tools,
    apiKey: input.apiKey,
    streamFn: input.streamFn,
    signal: input.signal,
    onEvent: input.onEvent,
    pauseAtTokens,
  });
}

/** A compaction run: the chat saves what isn't stored, then writes a summary that covers this run, unless it fails to. */
async function compact(input: WakeChatInput): Promise<{ run: Run; wroteSummary: boolean }> {
  const trigger: RunTrigger = { kind: "compaction", contextTokens: await currentContextTokens(input) };
  const tools = [...input.compactionTools, writeSummaryTool(input.prompts)];
  const run = await runOnce(input, [trigger], tools, undefined);
  const summary = await summaryInForce(input.db, input.chat);
  return { run, wroteSummary: summary?.body.throughRun === run.id };
}

/**
 * The run after a compaction pauses at the limit only if the compaction left it room. After one
 * that wrote no summary, or one that left the context at half the limit or more (its instructions
 * alone fill that much), pausing would only compact again and again, so the run goes ahead.
 */
async function pauseAfter(
  input: WakeChatInput,
  wroteSummary: boolean,
  limit: number,
): Promise<number | undefined> {
  if (!wroteSummary) return undefined;
  if ((await currentContextTokens(input)) >= limit / 2) return undefined;
  return limit;
}

/** What wakes the run that carries on a paused one: the paused run, and what woke it. */
function continuationOf(paused: Run): RunTrigger[] {
  const woke = paused.triggers.filter((trigger) => trigger.kind !== "continuation");
  return [{ kind: "continuation", run: paused.id }, ...woke];
}

async function currentContextTokens(input: WakeChatInput): Promise<number> {
  const systemPrompt = await systemPromptFor(input.db, input.prompts, input.chat);
  return contextTokens(await contextMessages(input.db, input.chat), systemPrompt);
}

function checkFitsWindow(model: Model<Api>, chat: Chat, tokens: number): void {
  if (tokens < model.contextWindow) return;
  throw new ContextOverflowError(
    `Chat ${chat.id}'s context is about ${tokens} tokens, more than ${model.id}'s window of ${model.contextWindow}. It can neither run nor compact on this model: wake it on a model with a bigger window.`,
  );
}
