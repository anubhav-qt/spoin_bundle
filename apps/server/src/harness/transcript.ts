import type { AssistantMessage, ToolResultMessage, UserMessage } from "@spoin/pi-ai";
import { and, asc, eq, gt, max, sql } from "drizzle-orm";
import { type Static, Type } from "typebox";
import type { Db, Tx } from "../db/client.ts";
import { actionLog, chatMessage } from "../db/schema.ts";
import type { Run } from "./chats.ts";
import { checkValue } from "./check.ts";
import { StoreError } from "./records.ts";
import { ActionResult, RecordRef } from "./schemas.ts";

/**
 * Every chat's transcript, kept whole for as long as the chat lives (Trotter's ADR 0014, 0024):
 * compaction only shortens what the model reads. The system prompt isn't part of it; each run
 * keeps its own. And the action log, one entry per tool call.
 */

type Conn = Db | Tx;

export type TranscriptMessage = UserMessage | AssistantMessage | ToolResultMessage;

export interface TranscriptEntry {
  seq: number;
  runId: string;
  message: TranscriptMessage;
}

/** pi's message, kept as pi wrote it; only the fields the store relies on are checked. */
const StoredMessage = Type.Object({
  role: Type.Enum(["user", "assistant", "toolResult"]),
  timestamp: Type.Number(),
});

/**
 * Adds a message to the end of its chat's transcript. The next number is taken in the insert
 * itself; only the chat's one running run writes to it.
 */
export async function appendMessage(
  db: Conn,
  run: Run,
  message: TranscriptMessage,
): Promise<TranscriptEntry> {
  checkValue(StoredMessage, message, `A message of run ${run.id}`);
  const next = sql`(SELECT coalesce(max(${chatMessage.seq}), 0) + 1 FROM ${chatMessage} WHERE ${chatMessage.chatId} = ${run.chatId})`;
  const [row] = await db
    .insert(chatMessage)
    .values({ chatId: run.chatId, seq: next, runId: run.id, message })
    .returning({ seq: chatMessage.seq });
  if (!row) throw new StoreError(`A message of run ${run.id} could not be stored.`);
  return { seq: row.seq, runId: run.id, message };
}

/** A chat's transcript in order, from just after `afterSeq`: 0 for all of it. */
export async function readTranscript(db: Conn, chatId: string, afterSeq = 0): Promise<TranscriptEntry[]> {
  const rows = await db
    .select()
    .from(chatMessage)
    .where(and(eq(chatMessage.chatId, chatId), gt(chatMessage.seq, afterSeq)))
    .orderBy(asc(chatMessage.seq));
  return rows.map((row) => {
    checkValue(StoredMessage, row.message, `Message ${row.seq} of chat ${chatId}`);
    // Checked for what the store relies on; the rest is pi's, stored as pi wrote it.
    return { seq: row.seq, runId: row.runId, message: row.message as TranscriptMessage };
  });
}

/** The last message a run added to its chat's transcript. */
export async function lastSeqOfRun(db: Conn, run: Pick<Run, "id" | "chatId">): Promise<number> {
  const [row] = await db
    .select({ seq: max(chatMessage.seq) })
    .from(chatMessage)
    .where(and(eq(chatMessage.chatId, run.chatId), eq(chatMessage.runId, run.id)));
  if (row?.seq == null) throw new StoreError(`Run ${run.id} added nothing to its chat's transcript.`);
  return row.seq;
}

/** Enough to judge a tool call later: what was called, why, what came back, what the chat read and wrote. */
export const ActionLogEntry = Type.Object(
  {
    runId: Type.String({ format: "uuid" }),
    toolCallId: Type.String({ minLength: 1, description: "The call's id in the transcript" }),
    tool: Type.String({ minLength: 1 }),
    arguments: Type.Unknown(),
    reasoning: Type.String({ description: "The model's own words before the call; can be empty" }),
    result: ActionResult,
    dataSeen: Type.Array(RecordRef),
    recordsWritten: Type.Array(RecordRef),
  },
  { additionalProperties: false },
);
export type ActionLogEntry = Static<typeof ActionLogEntry>;

export async function appendActionLogEntry(db: Conn, entry: ActionLogEntry): Promise<void> {
  const checked = checkValue(ActionLogEntry, entry, `The action log entry for call ${entry.toolCallId}`);
  await db.insert(actionLog).values({ ...checked, arguments: checked.arguments ?? {} });
}

/** An entry as stored, with when its call finished. */
export type StoredActionLogEntry = ActionLogEntry & { id: string; at: Date };

/** A run's tool calls, in the order they finished. */
export async function readActionLog(db: Conn, runId: string): Promise<StoredActionLogEntry[]> {
  const rows = await db.select().from(actionLog).where(eq(actionLog.runId, runId)).orderBy(asc(actionLog.at));
  return rows.map(({ id, at, ...entry }) => ({
    id,
    at,
    ...checkValue(ActionLogEntry, entry, `Action log entry ${id}`),
  }));
}
