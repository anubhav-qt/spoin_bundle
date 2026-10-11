import { randomUUID } from "node:crypto";
import type { Embedder } from "@spoin/frog/embeddings";
import { normalizeTopicText } from "@spoin/frog/normalize";
import { corpusVersion } from "@spoin/frog/retrieval";
import { curriculum, curriculumSubtopic } from "@spoin/frog/schema";
import type { Difficulty } from "@spoin/shared/enums";
import { and, asc, eq, inArray, notInArray } from "drizzle-orm";
import type { Db, Tx, UniverseDb } from "../db/client.ts";
import { subtopic, topic, topicAlias } from "../db/schema.ts";
import { slugify } from "../topics/slug.ts";

/*
 * The deterministic projection: the corpus's curriculum tables onto the app's topics and
 * subtopics (docs/architecture/authored-curriculum.md §8). No model call at any step.
 *
 *   for each curriculum:
 *     upsert the topic         matched on slug(topic_name)
 *     for each subtopic x tier:
 *       upsert a subtopic      matched on (topic, title, difficulty), carrying that
 *                              tier's declared grounding
 *     remove the subtopics no longer in the file
 *   stamp the topic with the corpus version it was projected against
 *
 * The file is the truth and the database follows it: a dropped subtopic is dropped, and
 * its cards go with it (`card.subtopic_id` cascades). That is what makes a curriculum
 * editable by editing the file and projecting again.
 */

export interface ProjectionReport {
  curricula: number;
  topicsCreated: number;
  topicsUpdated: number;
  subtopicsUpserted: number;
  subtopicsRemoved: number;
}

export const projectionSummary = (r: ProjectionReport): string =>
  `curricula=${r.curricula} topics_created=${r.topicsCreated} topics_updated=${r.topicsUpdated} subtopics_upserted=${r.subtopicsUpserted} subtopics_removed=${r.subtopicsRemoved}`;

/** A tier's plan as the curriculum ingester stored it: the contract has already checked its shape. */
interface TierPlan {
  target_cards: number;
  card_types: Record<string, number>;
  grounding?: string[];
}

/** Python's `round`, half to even, so a coverage threshold lands where it always did. */
function roundHalfEven(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff !== 0.5) return Math.round(x);
  return floor % 2 === 0 ? floor : floor + 1;
}

/** The coverage threshold: completion is defined against this, not `target_cards` (ADR-0007). */
export const minCards = (targetCards: number, fraction: number): number =>
  Math.max(1, roundHalfEven(targetCards * fraction));

/**
 * Project every curriculum. One write transaction, committed once: a crash part-way
 * leaves the app on the previous curricula rather than half on the new ones.
 */
export async function projectCurricula(ctx: {
  db: Db;
  universe: UniverseDb;
  embedder: Embedder;
  minCardsFraction: number;
}): Promise<ProjectionReport> {
  const report: ProjectionReport = {
    curricula: 0,
    topicsCreated: 0,
    topicsUpdated: 0,
    subtopicsUpserted: 0,
    subtopicsRemoved: 0,
  };
  const version = await corpusVersion(ctx.universe);
  const curricula = await ctx.universe.select().from(curriculum).orderBy(asc(curriculum.topicName));
  const units = curricula.length
    ? await ctx.universe
        .select()
        .from(curriculumSubtopic)
        .where(
          inArray(
            curriculumSubtopic.curriculumId,
            curricula.map((c) => c.id),
          ),
        )
        .orderBy(asc(curriculumSubtopic.ordinal))
    : [];

  await ctx.db.transaction(async (tx) => {
    for (const c of curricula) {
      await projectOne(
        tx,
        ctx,
        c,
        units.filter((u) => u.curriculumId === c.id),
        version,
        report,
      );
    }
  });
  report.curricula = curricula.length;
  return report;
}

async function projectOne(
  tx: Tx,
  ctx: { embedder: Embedder; minCardsFraction: number },
  c: typeof curriculum.$inferSelect,
  units: (typeof curriculumSubtopic.$inferSelect)[],
  version: string,
  report: ProjectionReport,
): Promise<void> {
  const normalized = normalizeTopicText(c.topicName);
  // A topic is resolvable only with an embedding and an alias (ADR-0025's matching).
  // Re-embedded every run so a renamed topic stays findable; the embedder is local and
  // unmetered, so "no model call" holds where it matters: no LLM, deterministic.
  const [embedding] = await ctx.embedder.embedPassage([normalized]);
  const fields = {
    canonicalName: c.topicName,
    description: c.description,
    scope: c.scope,
    curriculumGeneratedAt: new Date(),
    curriculumCorpusVersion: version,
    embedding: embedding ?? null,
    embeddingModel: embedding ? ctx.embedder.modelName : null,
  };

  const slug = slugify(c.topicName);
  const [existing] = await tx.select({ id: topic.id }).from(topic).where(eq(topic.slug, slug));
  let topicId: string;
  if (existing) {
    topicId = existing.id;
    await tx.update(topic).set(fields).where(eq(topic.id, topicId));
    report.topicsUpdated += 1;
  } else {
    const [created] = await tx
      .insert(topic)
      .values({ slug, ...fields })
      .returning({ id: topic.id });
    topicId = (created as { id: string }).id;
    report.topicsCreated += 1;
  }
  await tx
    .insert(topicAlias)
    .values({ normalizedText: normalized, rawText: c.topicName, topicId, decidedBy: "projection" })
    .onConflictDoNothing({ target: topicAlias.normalizedText });

  const kept: string[] = [];
  for (const [position, unit] of units.entries()) {
    const plans = unit.tiers as Record<string, TierPlan>;
    const tiers = Object.keys(plans) as Difficulty[];
    const existingByTier = new Map<Difficulty, { id: string; subtopicGroupId: string }>();
    for (const difficulty of tiers) {
      const [row] = await tx
        .select({ id: subtopic.id, subtopicGroupId: subtopic.subtopicGroupId })
        .from(subtopic)
        .where(
          and(
            eq(subtopic.topicId, topicId),
            eq(subtopic.title, unit.title),
            eq(subtopic.difficulty, difficulty),
          ),
        );
      if (row) existingByTier.set(difficulty, row);
    }
    // The tiers of one concept share a group id; adopting an existing tier's keeps an
    // edit from forking a second group for the same concept.
    const groupId = [...existingByTier.values()][0]?.subtopicGroupId ?? randomUUID();

    for (const difficulty of tiers) {
      const plan = plans[difficulty] as TierPlan;
      const values = {
        description: unit.description,
        targetCards: plan.target_cards,
        minCards: minCards(plan.target_cards, ctx.minCardsFraction),
        cardTypeQuotas: Object.keys(plan.card_types).length ? plan.card_types : null,
        // Carried verbatim, never resolved to chunk ids here: re-ingestion rebuilds a
        // document's chunks, so stored ids would rot. Retrieval resolves them late.
        groundingRefs: plan.grounding?.length ? plan.grounding : null,
        position,
      };
      const row = existingByTier.get(difficulty);
      if (row) {
        await tx.update(subtopic).set(values).where(eq(subtopic.id, row.id));
        kept.push(row.id);
      } else {
        const [created] = await tx
          .insert(subtopic)
          .values({ topicId, title: unit.title, difficulty, subtopicGroupId: groupId, ...values })
          .returning({ id: subtopic.id });
        kept.push((created as { id: string }).id);
      }
      report.subtopicsUpserted += 1;
    }
  }

  const stale = await tx
    .delete(subtopic)
    .where(and(eq(subtopic.topicId, topicId), kept.length ? notInArray(subtopic.id, kept) : undefined))
    .returning({ id: subtopic.id });
  report.subtopicsRemoved += stale.length;
}
