import type { WakeStatus } from "@spoin/shared/enums";
import { and, asc, eq, lte, min, sql } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import { schedulerMark, wake } from "../db/schema.ts";
import { readChat } from "./chats.ts";
import { checkValue } from "./check.ts";
import { StoreError } from "./records.ts";
import { WakeTrigger } from "./schemas.ts";

/**
 * The wake queue (Trotter's ADR 0027, task 0045): each wake is one reason to wake one chat, due at
 * a time. The scheduler takes every wake due for a chat at once, runs the chat on them, then
 * settles them.
 */

type Conn = Db | Tx;
export type Wake = Omit<typeof wake.$inferSelect, "trigger"> & { trigger: WakeTrigger };

export interface NewWake {
  chatId: string;
  trigger: WakeTrigger;
  dueAt: Date;
}

export async function queueWake(db: Conn, newWake: NewWake): Promise<Wake> {
  const trigger = checkValue(WakeTrigger, newWake.trigger, `A wake for chat ${newWake.chatId}`);
  await readChat(db, newWake.chatId);
  const [queued] = await db
    .insert(wake)
    .values({ chatId: newWake.chatId, trigger, dueAt: newWake.dueAt })
    .returning();
  if (!queued) throw new StoreError(`A wake for chat ${newWake.chatId} could not be queued.`);
  return asWake(queued);
}

/** The chats with a wake waiting that is due by `now`, the one that came due first first. */
export async function chatsWithDueWakes(db: Conn, now: Date): Promise<string[]> {
  const firstDue = min(wake.dueAt);
  const rows = await db
    .select({ chatId: wake.chatId, firstDue })
    .from(wake)
    .where(and(eq(wake.status, "waiting"), lte(wake.dueAt, now)))
    .groupBy(wake.chatId)
    .orderBy(asc(firstDue));
  return rows.map((row) => row.chatId);
}

/** A chat's wakes waiting that are due by `now`, in the order they came due. */
export async function dueWakes(db: Conn, chatId: string, now: Date): Promise<Wake[]> {
  const rows = await db
    .select()
    .from(wake)
    .where(and(eq(wake.chatId, chatId), eq(wake.status, "waiting"), lte(wake.dueAt, now)))
    .orderBy(asc(wake.dueAt), asc(wake.createdAt));
  return rows.map(asWake);
}

/** Every wake with this status, in the order they're due. */
export async function listWakes(db: Conn, status: WakeStatus): Promise<Wake[]> {
  const rows = await db
    .select()
    .from(wake)
    .where(eq(wake.status, status))
    .orderBy(asc(wake.dueAt), asc(wake.createdAt));
  return rows.map(asWake);
}

/** Its chat is about to run on it. */
export const takeWake = (db: Conn, taken: Wake) => moveWake(db, taken, "waiting", { status: "taken" });

/** A run of its chat finished with it. */
export const finishWake = (db: Conn, taken: Wake) => moveWake(db, taken, "taken", { status: "done" });

/** Its chat stopped before finishing, so it waits again, due as before, without using a try. */
export const returnWake = (db: Conn, taken: Wake) => moveWake(db, taken, "taken", { status: "waiting" });

/** The run on it failed: it waits again until `retryAt`, or, with no `retryAt`, it's given up. */
export function failWake(db: Conn, taken: Wake, error: string, retryAt?: Date): Promise<Wake> {
  const tries = taken.tries + 1;
  if (!retryAt) return moveWake(db, taken, "taken", { status: "given_up", tries, error });
  return moveWake(db, taken, "taken", { status: "waiting", dueAt: retryAt, tries, error });
}

/** What it was for no longer stands, so it never wakes its chat. */
export const dropWake = (db: Conn, waiting: Wake) => moveWake(db, waiting, "waiting", { status: "dropped" });

/**
 * Puts every taken wake back to waiting. The worker calls this when it starts, with
 * markInterruptedRuns: a wake still taken then was cut off with its run.
 */
export async function releaseTakenWakes(db: Conn): Promise<Wake[]> {
  const rows = await db.update(wake).set({ status: "waiting" }).where(eq(wake.status, "taken")).returning();
  return rows.map(asWake);
}

/** How far the scheduler has got under this name, or undefined before it has got anywhere. */
export async function readSchedulerMark(db: Conn, name: string): Promise<string | undefined> {
  const [row] = await db.select().from(schedulerMark).where(eq(schedulerMark.name, name));
  return row?.value;
}

export async function saveSchedulerMark(db: Conn, name: string, value: string): Promise<void> {
  await db
    .insert(schedulerMark)
    .values({ name, value })
    .onConflictDoUpdate({ target: schedulerMark.name, set: { value: sql`excluded.value` } });
}

/** Moves a wake on from the status it must have now. */
async function moveWake(
  db: Conn,
  moving: Wake,
  from: WakeStatus,
  changes: Partial<Pick<Wake, "status" | "dueAt" | "tries" | "error">>,
): Promise<Wake> {
  const [moved] = await db
    .update(wake)
    .set(changes)
    .where(and(eq(wake.id, moving.id), eq(wake.status, from)))
    .returning();
  if (!moved) {
    const [stored] = await db.select({ status: wake.status }).from(wake).where(eq(wake.id, moving.id));
    if (!stored) throw new StoreError(`There is no wake ${moving.id}.`);
    throw new StoreError(`Wake ${moving.id} is ${stored.status}, not ${from}.`);
  }
  return asWake(moved);
}

function asWake(row: typeof wake.$inferSelect): Wake {
  return { ...row, trigger: checkValue(WakeTrigger, row.trigger, `The trigger of wake ${row.id}`) };
}
