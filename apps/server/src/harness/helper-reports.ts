import type { HelperTask } from "@spoin/shared/enums";
import { and, desc, eq, inArray, notExists, sql } from "drizzle-orm";
import { alias } from "drizzle-orm/pg-core";
import type { Db, Tx } from "../db/client.ts";
import { chat, harnessRecord, wake } from "../db/schema.ts";
import { type Chat, readChat } from "./chats.ts";
import { createRecord, readLatestRecord, refOf } from "./records.ts";
import { BriefRecord, ReportRecord } from "./schemas.ts";
import { queueWake } from "./wakes.ts";

/*
 * A helper's brief and its report (task 0045). The main chat waits for the report, so a helper
 * that ends without one would leave it waiting for good: a document writer whose last answer came
 * back empty did, in the first live run. The scheduler wakes such a helper again on its brief,
 * where it carries on from its transcript, and after RUNS_TO_REPORT runs code reports for it.
 */

type Conn = Db | Tx;

/**
 * The helpers that work alone from their brief to their report. A tier writer isn't one: it ends
 * turns waiting for its pass-1 helper's verdicts. Nor are the corrector and verifier, whose
 * verdicts are their reports.
 */
const SOLO_TASKS: HelperTask[] = ["helper", "document_writer", "curriculum_writer"];

/** How many runs a helper has to report in before code reports for it. */
export const RUNS_TO_REPORT = 3;

/** The brief a helper is working on: the latest one written for it. */
export async function briefOf(db: Conn, helper: Chat): Promise<BriefRecord | undefined> {
  const [found] = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(
      and(
        eq(harnessRecord.kind, "brief"),
        eq(harnessRecord.version, 1),
        sql`${harnessRecord.body} ->> 'helper' = ${helper.id}`,
      ),
    )
    .orderBy(desc(harnessRecord.seq))
    .limit(1);
  if (!found) return undefined;
  return readLatestRecord(db, BriefRecord, "brief", found.id);
}

/**
 * Wakes each solo helper that has run, has nothing waiting and hasn't reported, on its brief
 * again; or, once it has had its runs or its wake was given up, writes its report for it, which
 * wakes the main chat as any report does.
 */
export async function settleStalledHelpers(db: Db, now: Date): Promise<void> {
  for (const stalled of await stalledHelpers(db)) {
    const helper = await readChat(db, stalled.chatId);
    const brief = await briefOf(db, helper);
    if (!brief) continue;
    if (stalled.givenUp > 0 || stalled.done >= RUNS_TO_REPORT) {
      await reportFor(db, brief, stalled.done + stalled.givenUp);
    } else {
      await queueWake(db, {
        chatId: helper.id,
        trigger: { kind: "record", record: refOf(brief) },
        dueAt: now,
      });
    }
  }
}

interface Stalled {
  chatId: string;
  done: number;
  givenUp: number;
}

async function stalledHelpers(db: Db): Promise<Stalled[]> {
  const report = alias(harnessRecord, "report");
  const brief = alias(harnessRecord, "brief");
  const pending = sql<number>`count(*) filter (where ${wake.status} in ('waiting', 'taken'))`.mapWith(Number);
  const done = sql<number>`count(*) filter (where ${wake.status} = 'done')`.mapWith(Number);
  const givenUp = sql<number>`count(*) filter (where ${wake.status} = 'given_up')`.mapWith(Number);
  const reported = db
    .select({ id: report.id })
    .from(report)
    .innerJoin(brief, eq(brief.id, sql`(${report.body} -> 'brief' ->> 'id')::uuid`))
    .where(
      and(
        eq(report.kind, "report"),
        eq(brief.kind, "brief"),
        sql`${brief.body} ->> 'helper' = ${chat.id}::text`,
      ),
    );
  const rows = await db
    .select({ chatId: chat.id, pending, done, givenUp })
    .from(chat)
    .innerJoin(wake, eq(wake.chatId, chat.id))
    .where(and(eq(chat.role, "helper"), inArray(chat.task, SOLO_TASKS), notExists(reported)))
    .groupBy(chat.id);
  return rows.filter((row) => row.pending === 0 && row.done + row.givenUp > 0);
}

async function reportFor(db: Db, brief: BriefRecord, runs: number): Promise<void> {
  const summary = `This helper ended ${runs} times without reporting, so code reports for it. Nothing it was asked for is confirmed done: read what it stored before you start another helper on this brief or do the work yourself.`;
  await createRecord(db, ReportRecord, {
    kind: "report",
    author: { kind: "code", component: "scheduler" },
    body: { brief: refOf(brief), summary },
  });
}
