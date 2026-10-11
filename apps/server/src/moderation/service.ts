import type { RepairCardOut, RepairEnqueuedOut, RepairQueueItemOut } from "@spoin/shared";
import type { CardReportReason, RepairMode } from "@spoin/shared/enums";
import { and, asc, desc, eq, inArray, isNotNull, isNull, max, notInArray } from "drizzle-orm";
import type { Db, Tx } from "../db/client.ts";
import { card, cardRepair, cardReport, generationJob } from "../db/schema.ts";
import { HttpError, pgCode, UNIQUE_VIOLATION } from "../lib/errors.ts";
import { iso } from "../lib/wire.ts";

/*
 * ADR-0076: report a card, and the operator triage that follows. Any signed-in reader
 * may report, guests included: a report costs nothing and needs no durable account.
 * The queue and its actions are the admin surface. In Phase 9 the `repair` job is
 * routed to the frog of the card's topic (ADR-0106).
 */

type Card = typeof card.$inferSelect;
type Repair = typeof cardRepair.$inferSelect;

const TERMINAL = ["done", "failed"] as const;

/** Repair work yields to a real reader waiting on a new topic: below the generate default of 0. */
const REPAIR_JOB_PRIORITY = -10;

/** Idempotent per reader and card: a second report updates the first. Only a live card can be reported. */
export async function reportCard(
  db: Db | Tx,
  userId: string,
  cardId: string,
  reason: CardReportReason,
  note: string | null,
) {
  const [c] = await db.select({ status: card.status }).from(card).where(eq(card.id, cardId));
  if (c?.status !== "active") throw new HttpError(404, "No such card");
  await db
    .insert(cardReport)
    .values({ cardId, userId, reason, note })
    .onConflictDoUpdate({
      target: [cardReport.cardId, cardReport.userId],
      set: { reason, note, resolvedAt: null },
    });
}

/**
 * Resolves every open report on a card. The two writers of `resolved_at` are the
 * delete action here and the repair landing, so both come through this.
 */
export async function markCardReportsResolved(db: Db | Tx, cardId: string) {
  await db
    .update(cardReport)
    .set({ resolvedAt: new Date() })
    .where(and(eq(cardReport.cardId, cardId), isNull(cardReport.resolvedAt)));
}

const cardOut = (c: Card): RepairCardOut => ({
  card_id: c.id,
  version: c.version,
  title: c.title,
  canonical_title: c.canonicalTitle,
  summary: c.summary,
  body: c.body,
  archetype: c.archetype,
  visual_id: c.visualId,
  visual_slots: c.visualSlots,
});

const attemptOut = (r: Repair | undefined) =>
  r ? { mode: r.mode, status: r.status, error: r.error, created_at: iso(r.createdAt) } : null;

/**
 * Two kinds of entry, newest activity first: `open`, a card with unresolved reports
 * awaiting triage; and `resolved`, a repair that landed (or failed), shown before and
 * after until the operator dismisses it.
 */
export async function listQueue(db: Db): Promise<RepairQueueItemOut[]> {
  const openIds = (
    await db
      .select({ cardId: cardReport.cardId })
      .from(cardReport)
      .where(isNull(cardReport.resolvedAt))
      .groupBy(cardReport.cardId)
      .orderBy(desc(max(cardReport.createdAt)))
  ).map((r) => r.cardId);

  const resolved = await db
    .select()
    .from(cardRepair)
    .where(
      and(
        inArray(cardRepair.status, [...TERMINAL]),
        isNull(cardRepair.dismissedAt),
        openIds.length ? notInArray(cardRepair.cardId, openIds) : undefined,
      ),
    )
    .orderBy(desc(cardRepair.createdAt));

  const want = [
    ...new Set([
      ...openIds,
      ...resolved.map((r) => r.cardId),
      ...resolved.flatMap((r) => (r.resultCardId ? [r.resultCardId] : [])),
    ]),
  ];
  if (want.length === 0) return [];
  const cards = new Map((await db.select().from(card).where(inArray(card.id, want))).map((c) => [c.id, c]));

  const reports = new Map<string, (typeof cardReport.$inferSelect)[]>();
  if (openIds.length) {
    const rows = await db
      .select()
      .from(cardReport)
      .where(and(inArray(cardReport.cardId, openIds), isNull(cardReport.resolvedAt)))
      .orderBy(asc(cardReport.createdAt));
    for (const r of rows) reports.set(r.cardId, [...(reports.get(r.cardId) ?? []), r]);
  }

  const latest = new Map<string, Repair>();
  const repairs = await db
    .select()
    .from(cardRepair)
    .where(inArray(cardRepair.cardId, want))
    .orderBy(desc(cardRepair.createdAt));
  for (const r of repairs) if (!latest.has(r.cardId)) latest.set(r.cardId, r);

  const out: RepairQueueItemOut[] = [];
  const seen = new Set<string>();
  for (const id of openIds) {
    const c = cards.get(id);
    if (!c) continue;
    seen.add(id);
    const open = reports.get(id) ?? [];
    out.push({
      card_id: c.id,
      topic_id: c.topicId,
      family_id: c.familyId,
      difficulty: c.difficulty,
      before: cardOut(c),
      after: null,
      report_count: open.length,
      reports: open.map((r) => ({ reason: r.reason, note: r.note, created_at: iso(r.createdAt) })),
      latest_repair: attemptOut(latest.get(id)),
      state: "open",
    });
  }
  for (const r of resolved) {
    const before = cards.get(r.cardId);
    if (seen.has(r.cardId) || !before) continue;
    seen.add(r.cardId);
    const after = r.resultCardId ? cards.get(r.resultCardId) : undefined;
    out.push({
      card_id: r.cardId,
      topic_id: before.topicId,
      family_id: before.familyId,
      difficulty: before.difficulty,
      before: cardOut(before),
      after: after ? cardOut(after) : null,
      report_count: 0,
      reports: [],
      latest_repair: attemptOut(r),
      state: "resolved",
    });
  }
  return out;
}

const dismissRepairs = (tx: Db | Tx, cardId: string) =>
  tx
    .update(cardRepair)
    .set({ dismissedAt: new Date() })
    .where(
      and(
        eq(cardRepair.cardId, cardId),
        inArray(cardRepair.status, [...TERMINAL]),
        isNull(cardRepair.dismissedAt),
      ),
    );

async function requireActiveCard(tx: Db | Tx, cardId: string): Promise<Card> {
  const [c] = await tx.select().from(card).where(eq(card.id, cardId));
  if (c?.status !== "active") throw new HttpError(404, "No such card, or it is not active");
  return c;
}

/** Pulls the card from every feed, resolves its reports, and clears it from the queue. No model, no job. */
export const deleteCard = (db: Db, cardId: string): Promise<RepairEnqueuedOut> =>
  db.transaction(async (tx) => {
    await requireActiveCard(tx, cardId);
    await tx.update(card).set({ status: "retired" }).where(eq(card.id, cardId));
    await markCardReportsResolved(tx, cardId);
    await dismissRepairs(tx, cardId);
    return { card_id: cardId, action: "deleted", job_id: null };
  });

/** Accepts the repair: its before/after entry leaves the queue and the new version stays live. */
export async function dismiss(db: Db, cardId: string): Promise<RepairEnqueuedOut> {
  await dismissRepairs(db, cardId);
  return { card_id: cardId, action: "dismissed", job_id: null };
}

/**
 * Undoes a landed repair: the original goes back live and the repaired version is
 * superseded, kept in the table so the revert is itself reversible. `cardId` is the
 * original (`before`) card, the id every other action takes.
 */
export const revert = (db: Db, cardId: string): Promise<RepairEnqueuedOut> =>
  db.transaction(async (tx) => {
    const [repair] = await tx
      .select()
      .from(cardRepair)
      .where(
        and(eq(cardRepair.cardId, cardId), eq(cardRepair.status, "done"), isNotNull(cardRepair.resultCardId)),
      )
      .orderBy(desc(cardRepair.createdAt))
      .limit(1);
    if (!repair?.resultCardId) throw new HttpError(404, "No landed repair to revert for this card");
    const pair = await tx
      .select({ id: card.id })
      .from(card)
      .where(inArray(card.id, [cardId, repair.resultCardId]));
    if (pair.length !== 2) throw new HttpError(404, "Repair cards missing");

    // The repaired row goes first, so one-active-per-family is never briefly violated.
    await tx.update(card).set({ status: "superseded" }).where(eq(card.id, repair.resultCardId));
    await tx.update(card).set({ status: "active" }).where(eq(card.id, cardId));
    await tx
      .update(cardRepair)
      .set({ error: "reverted by operator", dismissedAt: new Date() })
      .where(eq(cardRepair.id, repair.id));
    return { card_id: cardId, action: "reverted", job_id: null };
  });

/** One outstanding repair per card; the partial unique index settles a race the check misses. */
async function enqueueRepair(
  db: Db,
  cardId: string,
  mode: RepairMode,
  guidance: string | null,
  image: Buffer | null,
): Promise<string> {
  const conflict = () => new HttpError(409, "A repair is already queued for this card");
  try {
    return await db.transaction(async (tx) => {
      const c = await requireActiveCard(tx, cardId);
      const [outstanding] = await tx
        .select({ id: generationJob.id })
        .from(generationJob)
        .where(
          and(
            eq(generationJob.kind, "repair"),
            eq(generationJob.cardId, cardId),
            inArray(generationJob.status, ["pending", "running"]),
          ),
        );
      if (outstanding) throw conflict();
      const [job] = await tx
        .insert(generationJob)
        .values({
          kind: "repair",
          topicId: c.topicId,
          cardId,
          status: "pending",
          priority: REPAIR_JOB_PRIORITY,
        })
        .returning({ id: generationJob.id });
      if (!job) throw new Error("generation job insert returned nothing");
      await tx.insert(cardRepair).values({ cardId, jobId: job.id, mode, guidance, sourceImage: image });
      return job.id;
    });
  } catch (e) {
    if (pgCode(e) === UNIQUE_VIOLATION) throw conflict();
    throw e;
  }
}

/** Structure only, from the rendered card; `guidance` lets the repair change prose too (ADR-0076). */
export async function enqueueFix(
  db: Db,
  cardId: string,
  image: Buffer,
  guidance: string | null,
): Promise<RepairEnqueuedOut> {
  const jobId = await enqueueRepair(db, cardId, "fix", guidance, image);
  return { card_id: cardId, action: "fix_enqueued", job_id: jobId };
}

/** From scratch to `instructions`, through the normal quality gate; the image is optional. */
export async function enqueueRemake(
  db: Db,
  cardId: string,
  instructions: string,
  image: Buffer | null,
): Promise<RepairEnqueuedOut> {
  const jobId = await enqueueRepair(db, cardId, "remake", instructions, image);
  return { card_id: cardId, action: "remake_enqueued", job_id: jobId };
}
