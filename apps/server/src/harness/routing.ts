import { and, asc, eq, notExists } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import { generationJob, harnessRecord, routedJob, routedRecord } from "../db/schema.ts";
import { QUEUE_ORDER } from "../jobs/order.ts";
import { type Chat, openChat, openChatAt, readChat } from "./chats.ts";
import { readAnyRecord, readRecord, refOf } from "./records.ts";
import { type AnyRecord, isRecordKind, QuestionRecord, type RecordRef, type WakeTrigger } from "./schemas.ts";
import { queueWake } from "./wakes.ts";

/**
 * Which chats a record wakes, and when (Trotter's `routing.ts`, ADR 0027). A record wakes the chats
 * it's for once, when it's first written; a later version of it (a change, a retirement, an undo)
 * wakes no one. Each record is marked routed by its id in the same transaction as its wakes. A
 * topic name queued for writing wakes toad_sage the same way, by its generate job (task 0045).
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

/** Queues a toad_sage wake for each name waiting in the queue that it hasn't been woken for, in queue order. */
export async function routeNewJobs(db: Db, now: Date): Promise<void> {
  await db.transaction(async (tx) => {
    const unrouted = await tx
      .select({ id: generationJob.id })
      .from(generationJob)
      .where(
        and(
          eq(generationJob.kind, "generate"),
          eq(generationJob.status, "pending"),
          notExists(tx.select().from(routedJob).where(eq(routedJob.jobId, generationJob.id))),
        ),
      )
      .orderBy(...QUEUE_ORDER);
    if (unrouted.length === 0) return;
    const toadSage = await openChat(tx, "toad_sage");
    for (const job of unrouted) {
      await queueWake(tx, { chatId: toadSage.id, trigger: { kind: "job", job: job.id }, dueAt: now });
      await tx.insert(routedJob).values({ jobId: job.id });
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

/** The chat that asked a question, if a chat did: whoever wrote its first version, since a later one may be another's change. */
async function askerOf(tx: Tx, question: RecordRef): Promise<Chat[]> {
  const asked = await readRecord(tx, QuestionRecord, { ...question, version: 1 });
  if (asked.author.kind !== "chat") return [];
  return [await readChat(tx, asked.author.chatId)];
}
