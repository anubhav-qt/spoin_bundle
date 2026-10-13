import { and, asc, count, eq, exists, notExists, sql } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import { generationJob, harnessRecord, routedJob, routedRecord, subtopic } from "../db/schema.ts";
import { QUEUE_ORDER } from "../jobs/order.ts";
import { type Chat, openChat, openChatAt, openTopicChat, readChat } from "./chats.ts";
import { readAnyRecord, readRecord, refOf } from "./records.ts";
import {
  type AnyRecord,
  BriefRecord,
  HandoverRecord,
  isRecordKind,
  QuestionRecord,
  type RecordRef,
  type ReviewRecord,
  type VerdictsRecord,
  type WakeTrigger,
} from "./schemas.ts";
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

/** How many topics are written at once (task 0045). */
export const TADPOLES_AT_ONCE = 4;

/**
 * Starts the tadpoles of the next topics in the queue (task 0045): while fewer than four generate
 * jobs are running, the first pending job in queue order whose name toad_sage has taken in is
 * marked running, and its tadpole is woken with it. The job completes when its topic goes live.
 */
export async function startTadpoles(db: Db, now: Date): Promise<void> {
  await db.transaction(async (tx) => {
    // One scheduler at a time counts the running jobs, so two can't both take the last place.
    await tx.execute(sql`SELECT pg_advisory_xact_lock(hashtext('spoin:start-tadpoles'))`);
    const [running] = await tx
      .select({ jobs: count() })
      .from(generationJob)
      .where(and(eq(generationJob.kind, "generate"), eq(generationJob.status, "running")));
    const free = TADPOLES_AT_ONCE - (running?.jobs ?? 0);
    if (free <= 0) return;
    const takenIn = tx
      .select({ id: harnessRecord.id })
      .from(harnessRecord)
      .where(
        and(
          eq(harnessRecord.kind, "intake"),
          sql`${harnessRecord.body} ->> 'topic' = ${generationJob.topicId}::text`,
        ),
      );
    const next = await tx
      .select({ id: generationJob.id, topicId: generationJob.topicId })
      .from(generationJob)
      .where(and(eq(generationJob.kind, "generate"), eq(generationJob.status, "pending"), exists(takenIn)))
      .orderBy(...QUEUE_ORDER)
      .limit(free);
    for (const job of next) {
      await tx
        .update(generationJob)
        .set({ status: "running", attempts: sql`${generationJob.attempts} + 1` })
        .where(eq(generationJob.id, job.id));
      const tadpole = await openTopicChat(tx, "tadpole", job.topicId);
      await queueWake(tx, { chatId: tadpole.id, trigger: { kind: "job", job: job.id }, dueAt: now });
    }
  });
}

/** The chats a record is for, woken as soon as it's written, each once. */
async function readersOf(tx: Tx, record: AnyRecord): Promise<Chat[]> {
  const readers: Chat[] = [];
  if (record.kind === "question") readers.push(await openChatAt(tx, record.body.to));
  if (record.kind === "answer") readers.push(...(await askerOf(tx, record.body.question)));
  if (record.kind === "brief") readers.push(await readChat(tx, record.body.helper));
  if (record.kind === "report") readers.push(...(await mainChatOf(tx, record.body.brief)));
  if (record.kind === "handover") readers.push(await openChat(tx, "toad_sage"));
  if (record.kind === "review") readers.push(...(await reviewReaders(tx, record)));
  if (record.kind === "gate") readers.push(await readChat(tx, record.body.to));
  if (record.kind === "verdicts") readers.push(...(await verdictReaders(tx, record)));
  if (record.kind === "art") readers.push(await readChat(tx, record.body.writer));
  // The rest are read rather than woken for: a compaction summary is in its own chat's instructions,
  // and maps, drafts, audits and plans are what the chats that wrote them work from.
  return [...new Map(readers.map((chat) => [chat.id, chat])).values()];
}

/** The main chat of the helper a brief was for. By the brief, not the author, so a report code writes for a helper wakes it too. */
async function mainChatOf(tx: Tx, briefRef: RecordRef): Promise<Chat[]> {
  const brief = await readRecord(tx, BriefRecord, briefRef);
  const helper = await readChat(tx, brief.body.helper);
  if (!helper.parentId) return [];
  return [await readChat(tx, helper.parentId)];
}

/**
 * The chat that handed the work over. Once toad_sage says go on, the next stage starts: past the
 * closing report the curriculum chat writes the topic's curriculum, and past the curriculum the
 * topic's tadpole writes its cards.
 */
async function reviewReaders(tx: Tx, review: ReviewRecord): Promise<Chat[]> {
  const handover = await readRecord(tx, HandoverRecord, { ...review.body.handover, version: 1 });
  const readers: Chat[] = [];
  if (handover.author.kind === "chat") readers.push(await readChat(tx, handover.author.chatId));
  if (review.body.verdict === "go_on" && handover.body.kind === "closing_report") {
    readers.push(await openChat(tx, "curriculum"));
  }
  if (review.body.verdict === "go_on" && handover.body.kind === "curriculum") {
    readers.push(await openTopicChat(tx, "tadpole", handover.body.topic));
  }
  return readers;
}

/** The writer, and designer_toad for the cards pass 2 accepted, which now need their art. */
async function verdictReaders(tx: Tx, verdicts: VerdictsRecord): Promise<Chat[]> {
  const readers = [await readChat(tx, verdicts.body.writer)];
  if (verdicts.body.stage === "pass2" && verdicts.body.accepted.length > 0) {
    const [tier] = await tx
      .select({ topicId: subtopic.topicId })
      .from(subtopic)
      .where(eq(subtopic.id, verdicts.body.subtopic));
    if (tier) readers.push(await openTopicChat(tx, "designer_toad", tier.topicId));
  }
  return readers;
}

/** The chat that asked a question, if a chat did: whoever wrote its first version, since a later one may be another's change. */
async function askerOf(tx: Tx, question: RecordRef): Promise<Chat[]> {
  const asked = await readRecord(tx, QuestionRecord, { ...question, version: 1 });
  if (asked.author.kind !== "chat") return [];
  return [await readChat(tx, asked.author.chatId)];
}
