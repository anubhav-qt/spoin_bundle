import type { RunStatus, SINGLE_CHAT_ROLES, TOPIC_CHAT_ROLES } from "@spoin/shared/enums";
import { and, asc, eq, gte } from "drizzle-orm";
import { Type } from "typebox";
import type { Db, Tx } from "../db/client.ts";
import { chat, chatRun } from "../db/schema.ts";
import { pgCode, UNIQUE_VIOLATION } from "../lib/errors.ts";
import { checkValue } from "./check.ts";
import { StoreError } from "./records.ts";
import { type ChatAddress, RunTrigger } from "./schemas.ts";

/**
 * The chats and their runs (Trotter's ADR 0024, task 0045): one each of toad_sage, the curriculum
 * chat, ero_sennin and wise_toad; a tadpole, designer_toad and visual_toad per topic; a helper per
 * task. A chat runs once at a time, which the database enforces.
 */

type Conn = Db | Tx;
export type Chat = typeof chat.$inferSelect;
export type Run = Omit<typeof chatRun.$inferSelect, "triggers"> & { triggers: RunTrigger[] };

/** The chat already has a run going. */
export class ChatBusyError extends StoreError {
  constructor(message: string) {
    super(message);
    this.name = "ChatBusyError";
  }
}

/** toad_sage, the curriculum chat, ero_sennin or wise_toad, made the first time it's needed. */
export async function openChat(db: Conn, role: (typeof SINGLE_CHAT_ROLES)[number]): Promise<Chat> {
  await db.insert(chat).values({ role }).onConflictDoNothing();
  const [found] = await db.select().from(chat).where(eq(chat.role, role));
  if (!found) throw new StoreError(`The ${role} chat could not be made.`);
  return found;
}

/** A topic's tadpole, designer_toad or visual_toad, made the first time it's needed. */
export async function openTopicChat(
  db: Conn,
  role: (typeof TOPIC_CHAT_ROLES)[number],
  topicId: string,
): Promise<Chat> {
  await db.insert(chat).values({ role, topicId }).onConflictDoNothing();
  const [found] = await db
    .select()
    .from(chat)
    .where(and(eq(chat.role, role), eq(chat.topicId, topicId)));
  if (!found) throw new StoreError(`The ${role} chat of topic ${topicId} could not be made.`);
  return found;
}

/** The chat an address names, made the first time it's needed. */
export function openChatAt(db: Conn, address: ChatAddress): Promise<Chat> {
  return "topic" in address ? openTopicChat(db, address.role, address.topic) : openChat(db, address.role);
}

/** The AskAI chat of a reader's thread, made on its first turn. */
export async function openAskChat(db: Conn, askConversationId: string): Promise<Chat> {
  await db.insert(chat).values({ role: "ask_ai", askConversationId }).onConflictDoNothing();
  const [found] = await db.select().from(chat).where(eq(chat.askConversationId, askConversationId));
  if (!found) throw new StoreError(`The AskAI chat of thread ${askConversationId} could not be made.`);
  return found;
}

/** A new helper under the chat that starts it. A helper never starts helpers of its own. */
export async function newHelperChat(db: Conn, parent: Chat): Promise<Chat> {
  if (parent.role === "helper") throw new StoreError("A helper can't start helpers of its own.");
  const [helper] = await db.insert(chat).values({ role: "helper", parentId: parent.id }).returning();
  if (!helper) throw new StoreError(`A helper of chat ${parent.id} could not be made.`);
  return helper;
}

export async function readChat(db: Conn, id: string): Promise<Chat> {
  const [found] = await db.select().from(chat).where(eq(chat.id, id));
  if (!found) throw new StoreError(`There is no chat ${id}.`);
  return found;
}

export interface NewRun {
  chatId: string;
  model: string;
  triggers: RunTrigger[];
  systemPrompt: string;
}

/** How a run ended, when the harness ends it. */
export type RunEnd =
  | { status: "done" }
  | { status: "stopped" }
  | { status: "paused" }
  | { status: "failed"; error: string };

const Triggers = Type.Array(RunTrigger, { minItems: 1 });

/** Starts a run of a chat. A chat runs once at a time: while it has a run going, this throws ChatBusyError. */
export async function startRun(db: Conn, newRun: NewRun): Promise<Run> {
  const triggers = checkValue(Triggers, newRun.triggers, `What woke chat ${newRun.chatId}`);
  await readChat(db, newRun.chatId);
  try {
    const [run] = await db
      .insert(chatRun)
      .values({ chatId: newRun.chatId, model: newRun.model, triggers, systemPrompt: newRun.systemPrompt })
      .returning();
    if (!run) throw new StoreError(`A run of chat ${newRun.chatId} could not be started.`);
    return { ...run, triggers };
  } catch (error) {
    if (pgCode(error) === UNIQUE_VIOLATION) {
      throw new ChatBusyError(`Chat ${newRun.chatId} already has a run going.`);
    }
    throw error;
  }
}

/** Ends a run that is going. A run ends once. */
export async function endRun(db: Conn, runId: string, end: RunEnd): Promise<Run> {
  const [ended] = await db
    .update(chatRun)
    .set({ status: end.status, endedAt: new Date(), error: end.status === "failed" ? end.error : null })
    .where(and(eq(chatRun.id, runId), eq(chatRun.status, "running")))
    .returning();
  if (!ended) {
    const run = await readRun(db, runId);
    throw new StoreError(`Run ${runId} already ended: ${run.status}.`);
  }
  return asRun(ended);
}

/**
 * Ends every run still going as interrupted. The worker calls this when it starts: it is the only
 * process that runs chats, so a run still going then was cut off when it last stopped.
 */
export async function markInterruptedRuns(db: Conn): Promise<Run[]> {
  const rows = await db
    .update(chatRun)
    .set({ status: "interrupted", endedAt: new Date() })
    .where(eq(chatRun.status, "running"))
    .returning();
  return rows.map(asRun);
}

export async function readRun(db: Conn, id: string): Promise<Run> {
  const [found] = await db.select().from(chatRun).where(eq(chatRun.id, id));
  if (!found) throw new StoreError(`There is no run ${id}.`);
  return asRun(found);
}

/** A chat's runs, oldest first. */
export async function listRuns(db: Conn, chatId: string): Promise<Run[]> {
  const rows = await db
    .select()
    .from(chatRun)
    .where(eq(chatRun.chatId, chatId))
    .orderBy(asc(chatRun.startedAt));
  return rows.map(asRun);
}

/** Every chat's runs that started at or after `since`, oldest first; with a status, only those. */
export async function listRunsSince(db: Conn, since: Date, status?: RunStatus): Promise<Run[]> {
  const rows = await db
    .select()
    .from(chatRun)
    .where(and(gte(chatRun.startedAt, since), status ? eq(chatRun.status, status) : undefined))
    .orderBy(asc(chatRun.startedAt));
  return rows.map(asRun);
}

function asRun(row: typeof chatRun.$inferSelect): Run {
  return { ...row, triggers: checkValue(Triggers, row.triggers, `The triggers of run ${row.id}`) };
}
