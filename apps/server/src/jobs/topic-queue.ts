import type { QueuedTopicOut } from "@spoin/shared";
import { and, eq, gt, inArray, notExists, sql } from "drizzle-orm";
import { alias } from "drizzle-orm/pg-core";
import type { Deps } from "../context.ts";
import type { Db, Tx } from "../db/client.ts";
import { feedPlan, generationJob, subtopic, topic, userTopic } from "../db/schema.ts";
import { HttpError, pgCode, UNIQUE_VIOLATION } from "../lib/errors.ts";
import { iso } from "../lib/wire.ts";
import { nameProblem, resolve } from "../topics/request.ts";
import { OWNER_PRIORITY, QUEUE_ORDER, reprioritize } from "./order.ts";

/*
 * The topic queue page (task 0045): every topic that is not live yet, with its generate
 * job, the owner's and readers' alike. The owner adds topics, moves waiting ones through
 * the queue, retries failed ones and cancels the ones not being written. Every action
 * answers with the whole queue, so the page shows what the worker will actually do.
 */

const newer = alias(generationJob, "newer");

/** Running first, then the waiting jobs in the order they will run, then the failed ones. */
export async function listQueue(db: Db): Promise<QueuedTopicOut[]> {
  const requesters = sql<number>`(
    select count(*)::int from ${userTopic}
    where ${userTopic.topicId} = ${generationJob.topicId} and ${userTopic.isCustom}
  )`;
  const rows = await db
    .select({ job: generationJob, name: topic.canonicalName, slug: topic.slug, requesters })
    .from(generationJob)
    .innerJoin(topic, eq(topic.id, generationJob.topicId))
    .where(
      and(
        eq(generationJob.kind, "generate"),
        inArray(generationJob.status, ["pending", "running", "failed"]),
        // A topic's status is its latest generate job's, as the reader's own list has it.
        notExists(
          db
            .select({ one: sql`1` })
            .from(newer)
            .where(
              and(
                eq(newer.topicId, generationJob.topicId),
                eq(newer.kind, "generate"),
                gt(newer.createdAt, generationJob.createdAt),
              ),
            ),
        ),
      ),
    )
    .orderBy(
      sql`case ${generationJob.status} when 'running' then 0 when 'pending' then 1 else 2 end`,
      ...QUEUE_ORDER,
    );
  return rows.map(({ job, name, slug, requesters: n }) => ({
    job_id: job.id,
    topic_id: job.topicId,
    name,
    slug,
    status: job.status as QueuedTopicOut["status"],
    priority: job.priority,
    attempts: job.attempts,
    last_error: job.lastError,
    requesters: n,
    created_at: iso(job.createdAt),
  }));
}

/** A reader's request without the subscription: a pending topic, its alias and its job. */
export async function addTopic(
  ctx: Pick<Deps, "db" | "env">,
  name: string,
  description: string,
): Promise<QueuedTopicOut[]> {
  const problem = nameProblem(ctx, name);
  if (problem) throw new HttpError(422, problem);
  await ctx.db.transaction(async (tx) => {
    const { topic: t, created } = await resolve(tx, name, description, {
      priority: OWNER_PRIORITY,
      decidedBy: "admin",
    });
    if (!created) throw new HttpError(409, `Already a topic: ${t.canonicalName}`);
  });
  return listQueue(ctx.db);
}

async function generateJob(db: Db | Tx, jobId: string) {
  const [job] = await db
    .select()
    .from(generationJob)
    .where(and(eq(generationJob.id, jobId), eq(generationJob.kind, "generate")));
  if (!job) throw new HttpError(404, "No such job in the topic queue");
  return job;
}

/**
 * Puts a waiting job just ahead of another, or last. The waiting jobs are locked while
 * their priorities change, so a concurrent move or claim sees the order before or after,
 * never half of it.
 */
export async function moveJob(db: Db, jobId: string, beforeId: string | null): Promise<QueuedTopicOut[]> {
  await db.transaction(async (tx) => {
    const waiting = await tx
      .select({ id: generationJob.id, priority: generationJob.priority })
      .from(generationJob)
      .where(and(eq(generationJob.kind, "generate"), eq(generationJob.status, "pending")))
      .orderBy(...QUEUE_ORDER)
      .for("update");
    if (!waiting.some((j) => j.id === jobId)) {
      const job = await generateJob(tx, jobId);
      throw new HttpError(409, `Only a waiting job can move; this one is ${job.status}`);
    }
    if (beforeId !== null && !waiting.some((j) => j.id === beforeId))
      throw new HttpError(409, "The job it was dropped before is no longer waiting; reload the queue");
    for (const [id, priority] of reprioritize(waiting, jobId, beforeId))
      await tx.update(generationJob).set({ priority }).where(eq(generationJob.id, id));
  });
  return listQueue(db);
}

/** A failed job waits again, keeping its priority, its attempts and its last error. */
export async function retryJob(db: Db, jobId: string): Promise<QueuedTopicOut[]> {
  let retried: { id: string }[];
  try {
    retried = await db
      .update(generationJob)
      .set({ status: "pending", completedAt: null })
      .where(
        and(
          eq(generationJob.id, jobId),
          eq(generationJob.kind, "generate"),
          eq(generationJob.status, "failed"),
        ),
      )
      .returning({ id: generationJob.id });
  } catch (e) {
    if (pgCode(e) === UNIQUE_VIOLATION) throw new HttpError(409, "This topic already has a job waiting");
    throw e;
  }
  if (retried.length === 0) {
    const job = await generateJob(db, jobId);
    throw new HttpError(409, `Only a failed job can be retried; this one is ${job.status}`);
  }
  return listQueue(db);
}

/**
 * Cancels a topic that is not live and not being written: the placeholder goes, and with
 * it (by cascade) its aliases, its jobs and its requesters' subscriptions. Their feed
 * plans are dropped, since a plan names the topics it was built from.
 */
export async function cancelTopic(db: Db, jobId: string): Promise<QueuedTopicOut[]> {
  await db.transaction(async (tx) => {
    // Locked, so a worker cannot claim it between this check and the delete.
    const [job] = await tx
      .select()
      .from(generationJob)
      .where(and(eq(generationJob.id, jobId), eq(generationJob.kind, "generate")))
      .for("update");
    if (!job) throw new HttpError(404, "No such job in the topic queue");
    if (job.status === "running")
      throw new HttpError(409, "This topic is being written and can't be cancelled now");
    if (job.status === "completed")
      throw new HttpError(409, "This topic's job has finished; it is not in the queue");
    const [content] = await tx
      .select({ id: subtopic.id })
      .from(subtopic)
      .where(eq(subtopic.topicId, job.topicId))
      .limit(1);
    if (content) throw new HttpError(409, "This topic already has content, so it can't be cancelled");

    const followers = await tx
      .select({ userId: userTopic.userId })
      .from(userTopic)
      .where(eq(userTopic.topicId, job.topicId));
    await tx.delete(topic).where(eq(topic.id, job.topicId));
    if (followers.length > 0)
      await tx.delete(feedPlan).where(
        inArray(
          feedPlan.userId,
          followers.map((f) => f.userId),
        ),
      );
  });
  return listQueue(db);
}
