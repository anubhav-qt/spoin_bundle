import { type JobKind, JobStatus, type JobStatusOut } from "@spoin/shared";
import { asc, desc, eq, sql } from "drizzle-orm";
import type { Db } from "../db/client.ts";
import { generationJob, jobRuns, topic } from "../db/schema.ts";
import { iso, isoOrNull } from "../lib/wire.ts";

/*
 * The job status page (task 0045): each background job's last success and last error
 * from `job_runs` (breader's pattern), the generate and repair queues counted by status,
 * and every failed job with its error.
 */

const KINDS: JobKind[] = ["generate", "repair"];

export async function jobStatus(db: Db): Promise<JobStatusOut> {
  const runs = await db.select().from(jobRuns).orderBy(asc(jobRuns.name));

  const counted = await db
    .select({ kind: generationJob.kind, status: generationJob.status, n: sql<number>`count(*)::int` })
    .from(generationJob)
    .groupBy(generationJob.kind, generationJob.status);
  const queues = KINDS.map((kind) => {
    const of = (status: string) => counted.find((r) => r.kind === kind && r.status === status)?.n ?? 0;
    return {
      kind,
      ...(Object.fromEntries(JobStatus.options.map((s) => [s, of(s)])) as Record<JobStatus, number>),
    };
  });

  const failed = await db
    .select({ job: generationJob, topicName: topic.canonicalName })
    .from(generationJob)
    .innerJoin(topic, eq(topic.id, generationJob.topicId))
    .where(eq(generationJob.status, "failed"))
    .orderBy(desc(generationJob.updatedAt));

  return {
    runs: runs.map((r) => ({
      name: r.name,
      last_ok_at: isoOrNull(r.lastOkAt),
      last_error: r.lastError,
      last_error_at: isoOrNull(r.lastErrorAt),
      detail: r.detail ?? null,
    })),
    queues,
    failed: failed.map(({ job, topicName }) => ({
      job_id: job.id,
      kind: job.kind as JobKind,
      topic_id: job.topicId,
      topic_name: topicName,
      card_id: job.cardId,
      attempts: job.attempts,
      last_error: job.lastError,
      failed_at: iso(job.updatedAt),
    })),
  };
}
