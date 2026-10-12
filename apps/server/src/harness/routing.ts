import { and, asc, eq, notExists } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import { harnessRecord, routedRecord } from "../db/schema.ts";
import { type Chat, openChatAt, readChat } from "./chats.ts";
import { readAnyRecord, readRecord, refOf } from "./records.ts";
import { type AnyRecord, isRecordKind, QuestionRecord, type RecordRef, type WakeTrigger } from "./schemas.ts";
import { queueWake } from "./wakes.ts";

/**
 * Which chats a record wakes, and when (Trotter's `routing.ts`, ADR 0027). A record wakes the chats
 * it's for once, when it's first written; a later version of it (a change, a retirement, an undo)
 * wakes no one. Each record is marked routed by its id in the same transaction as its wakes.
 */

/** Queues a wake for each chat that a record not yet routed is for. */
export async function routeNewRecords(db: Db, now: Date): Promise<void> {
  await db.transaction(async (tx) => {
    const unrouted = await tx
      .select({ kind: harnessRecord.kind, id: harnessRecord.id, version: harnessRecord.version })
      .from(harnessRecord)
      .where(
        and(
          eq(harnessRecord.version, 1),
          notExists(tx.select().from(routedRecord).where(eq(routedRecord.recordId, harnessRecord.id))),
        ),
      )
      .orderBy(asc(harnessRecord.seq));
    for (const first of unrouted) {
      // A kind no chat reads, such as one a test made up, wakes no one.
      if (isRecordKind(first.kind)) {
        const record = await readAnyRecord(tx, first);
        const trigger: WakeTrigger = { kind: "record", record: refOf(record) };
        for (const chat of await readersOf(tx, record)) {
          await queueWake(tx, { chatId: chat.id, trigger, dueAt: now });
        }
      }
      await tx.insert(routedRecord).values({ recordId: first.id });
    }
  });
}

/** The chats a record is for, woken as soon as it's written, each once. */
async function readersOf(tx: Tx, record: AnyRecord): Promise<Chat[]> {
  const readers: Chat[] = [];
  if (record.kind === "question") readers.push(await openChatAt(tx, record.body.to));
  if (record.kind === "answer") readers.push(...(await askerOf(tx, record.body.question)));
  // The rest are read rather than woken for: a compaction summary is in its own chat's instructions.
  return [...new Map(readers.map((chat) => [chat.id, chat])).values()];
}

/** The chat that asked a question, if a chat did. */
async function askerOf(tx: Tx, question: RecordRef): Promise<Chat[]> {
  const asked = await readRecord(tx, QuestionRecord, question);
  if (asked.author.kind !== "chat") return [];
  return [await readChat(tx, asked.author.chatId)];
}
