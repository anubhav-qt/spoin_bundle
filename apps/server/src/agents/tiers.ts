import { randomUUID } from "node:crypto";
import { cosine } from "@spoin/frog/embeddings";
import { resolveGrounding } from "@spoin/frog/retrieval";
import { chunk, document } from "@spoin/frog/schema";
import { type Difficulty, difficultyRank } from "@spoin/shared/enums";
import { and, asc, eq, inArray, ne, sql } from "drizzle-orm";
import { type Static, Type } from "typebox";
import { classifyArchetype } from "../cards/archetype.ts";
import type { Db, Tx } from "../db/client.ts";
import { card, generationJob, harnessRecord, question, rejectedCard, subtopic, topic } from "../db/schema.ts";
import { openTopicChat } from "../harness/chats.ts";
import { briefOf } from "../harness/helper-reports.ts";
import { latestJob } from "../harness/intake.ts";
import { recordsStored } from "../harness/outputs.ts";
import { changeRecord, createRecord, readLatestRecord, refOf } from "../harness/records.ts";
import {
  type Author,
  BriefRecord,
  CARD_TYPES,
  CardPlanRecord,
  CLOSED,
  GateRecord,
  Id,
  Text,
} from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError } from "../harness/tools.ts";
import type { AgentDeps } from "./context.ts";
import { startHelper } from "./helpers.ts";

/*
 * A topic's cards and questions (harness-tools.md, task 0045), after its curriculum is projected.
 * Code runs the tier: it starts a writer per tier once the tier's lower tiers are live, sends each
 * draft through pass 1 and pass 2, and puts the tier's cards live once it reaches its target and
 * designer_toad has drawn each one's art. Only then does the writer write the tier's questions (the
 * owner's rule: no call spent on a question before its card is in the feed), which go live as pass
 * 2 passes them. What must be true is checked in code; a draft that fails a check is never stored.
 */

type Conn = Db | Tx;
export type Tier = typeof subtopic.$inferSelect;
type CardRow = typeof card.$inferSelect;

/**
 * Where a card is in the gate, kept in its `gen_meta` until it goes live: in pass 1, past it,
 * given to a pass-2 verifier, accepted.
 */
export type CardStage = "correcting" | "corrected" | "verifying" | "accepted";

/** The two kinds of art a card can carry: a gag (ADR-0079, ADR-0099), or a small informative drawing. */
export const ART_KINDS = ["gag", "informative"] as const;

export type ArtKind = (typeof ART_KINDS)[number];

/**
 * Every tier's mix of cards (the owner, 2026-10-13, replacing the old canon's quota table): half
 * are ascii cards carrying art, 30% of the tier gags and 20% small informative drawings; 20% are
 * mermaid flowcharts, 20% prose, of which a code subject may make any part code cards, and 10% myth
 * against fact. No photographs until they are sourced.
 */
export const CARD_MIX = { ascii: 0.5, diagram: 0.2, prose: 0.2, comparison: 0.1 };

/** The art an ascii card carries, by kind, as shares of the whole tier. */
export const ART_SHARES: Record<ArtKind, number> = { gag: 0.3, informative: 0.2 };

/**
 * A tier's cards by type, each its share of the target rounded so they add up to it: the largest
 * remainders get the cards left over, the first type first on a tie.
 */
export function cardMix(targetCards: number): Record<keyof typeof CARD_MIX, number> {
  const types = Object.keys(CARD_MIX) as (keyof typeof CARD_MIX)[];
  const mix = { ascii: 0, diagram: 0, prose: 0, comparison: 0 };
  let left = targetCards;
  for (const type of types) {
    mix[type] = Math.floor(targetCards * CARD_MIX[type]);
    left -= mix[type];
  }
  const byRemainder = [...types].sort((a, b) => {
    const remainderA = targetCards * CARD_MIX[a] - mix[a];
    const remainderB = targetCards * CARD_MIX[b] - mix[b];
    return remainderB - remainderA;
  });
  for (const type of byRemainder) {
    if (left === 0) break;
    mix[type] += 1;
    left -= 1;
  }
  return mix;
}

/** How a tier's ascii cards split between gags and informative drawings, 30 to 20. */
export function artQuotas(asciiCards: number): Record<ArtKind, number> {
  const gag = Math.round((asciiCards * ART_SHARES.gag) / (ART_SHARES.gag + ART_SHARES.informative));
  return { gag, informative: asciiCards - gag };
}

/** What the writer asked designer_toad to draw on a card. */
export interface ArtRequest {
  kind: ArtKind;
  show: string;
  ideas: string;
}

/** What the writer said about a card beyond its text, and where the gate has it. */
export interface CardMeta {
  stage: CardStage;
  form: (typeof CARD_TYPES)[number];
  /** On an ascii card only; a card without it goes live without waiting for designer_toad. */
  art?: ArtRequest;
  writer: string;
  passages: number[];
  /** The pass-2 verifier given the card. */
  verifier?: string;
  /** Why pass 2 rejected it, for the writer. */
  feedback?: string;
}

/** Where a question is in the gate: with a pass-2 verifier, or passed and live. */
export type QuestionStage = "gated" | "passed";

/**
 * A topic's questions in all, from the old pipeline (persistence.py): its card target clamped to
 * 200 to 300, shared among its tiers by their targets. Each question is written from one card:
 * a topic of 750 cards has questions on at most 300 of them, and one of 125 has two on some.
 */
export const QUESTION_BUDGET = { min: 200, max: 300 };

/** The scopes taught without tiers (ADR-0106): their cards run easy to advanced in one pass. */
export const TIERLESS_SCOPES = ["survey", "one_shot"];

/**
 * Near-duplicates: two bodies or stems this close in meaning say the same thing. The old
 * pipeline's `card_duplicate_threshold` (`generation/dedup.py`).
 */
export const NEAR_DUPLICATE = 0.9;

/** A card's limits, enforced here rather than asked for (CLAUDE.md). */
export const LIMITS = { title: 120, canonicalTitle: 160, summary: 280, bodyMin: 200, bodyMax: 1800 };

/**
 * A body's prose outside its fences: the old gate's text-wall line. The prompt asks for 300 to 800,
 * and the old pipeline's cards ran long whenever only the prompt asked.
 */
export const PROSE_MAX = 1200;

/** Correction notes pass 1 has been seen to leave in a body, from the old gate. */
const EDITORIAL_NOTE = /\*Source Note|\*\*Key Correction|\*\*Correction:/i;

const FENCE = /```([^\n`]*)\n[\s\S]*?```/g;

/** A diagram card's flowchart. */
const FLOWCHART = /```mermaid\n\s*(flowchart|graph)\b/;

/** Colour in a flowchart: every one is drawn black on white (the owner's rule), so none is written in. */
const MERMAID_STYLING = /^\s*(style|classDef|class|linkStyle)\b|:::/m;

/** Mermaid's diagram types the web app renders (ADR-0067). */
const MERMAID_TYPES =
  /^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|stateDiagram-v2|erDiagram|timeline|mindmap|pie|gantt|journey|quadrantChart)\b/;

export function metaOf(row: CardRow): CardMeta {
  return row.genMeta as unknown as CardMeta;
}

export async function tierById(db: Conn, id: string): Promise<Tier> {
  const [found] = await db.select().from(subtopic).where(eq(subtopic.id, id));
  if (!found) throw new ToolError(`There is no subtopic ${id}.`);
  return found;
}

/** The tier a helper works on, from its brief. */
export async function tierOfHelper(context: ToolContext): Promise<Tier> {
  const brief = await briefOf(context.db, context.chat);
  if (!brief?.body.subtopic) throw new ToolError("Your brief names no tier.");
  return tierById(context.db, brief.body.subtopic);
}

/** Whether the helper's tier has had cards written, whatever became of them. */
export async function cardsWritten(context: ToolContext): Promise<boolean> {
  const tier = await tierOfHelper(context);
  const [row] = await context.db
    .select({ id: card.id })
    .from(card)
    .where(eq(card.subtopicId, tier.id))
    .limit(1);
  return row !== undefined;
}

/** Whether the helper's tier has had questions written, whatever became of them. */
export async function questionsWritten(context: ToolContext): Promise<boolean> {
  const tier = await tierOfHelper(context);
  const [row] = await context.db
    .select({ id: question.id })
    .from(question)
    .where(eq(question.subtopicId, tier.id))
    .limit(1);
  return row !== undefined;
}

/** Whether toad_sage said go on to an "insufficient evidence" for the tier: the one way it finishes short. */
export async function allowedShort(db: Conn, tierId: string): Promise<boolean> {
  const rows = await db.execute(sql`
    SELECT 1 FROM harness_record r
    JOIN harness_record h ON h.kind = 'handover' AND h.version = 1 AND h.id::text = r.body -> 'handover' ->> 'id'
    WHERE r.kind = 'review' AND r.body ->> 'verdict' = 'go_on'
      AND h.body ->> 'kind' = 'insufficient_evidence' AND h.body ->> 'subtopic' = ${tierId}
    LIMIT 1
  `);
  return rows.rows.length > 0;
}

export interface TierProgress {
  /** In pass 1 or pass 2. */
  inGate: number;
  /** Accepted by pass 2, not live yet. */
  accepted: number;
  withArt: number;
  /** Accepted cards with an art request and no art yet: what holds the tier back from going live. */
  awaitingArt: number;
  live: number;
  rejected: number;
  questions: { inGate: number; live: number; freeTextLive: number; rejected: number };
}

export async function tierProgress(db: Conn, tierId: string): Promise<TierProgress> {
  const cards = await db
    .select({ status: card.status, meta: card.genMeta, visualKind: card.visualKind })
    .from(card)
    .where(eq(card.subtopicId, tierId));
  const progress: TierProgress = {
    inGate: 0,
    accepted: 0,
    withArt: 0,
    awaitingArt: 0,
    live: 0,
    rejected: 0,
    questions: { inGate: 0, live: 0, freeTextLive: 0, rejected: 0 },
  };
  for (const row of cards) {
    const stage = (row.meta as { stage?: CardStage }).stage;
    if (row.status === "active") {
      progress.live += 1;
    } else if (row.status === "rejected") {
      progress.rejected += 1;
    } else if (stage === "accepted") {
      progress.accepted += 1;
      if (row.visualKind) {
        progress.withArt += 1;
      } else if ((row.meta as { art?: ArtRequest }).art) {
        progress.awaitingArt += 1;
      }
    } else {
      progress.inGate += 1;
    }
  }
  const questions = await db
    .select({ status: question.status, kind: question.kind })
    .from(question)
    .where(eq(question.subtopicId, tierId));
  for (const row of questions) {
    if (row.status === "rejected") {
      progress.questions.rejected += 1;
    } else if (row.status === "active") {
      progress.questions.live += 1;
      if (row.kind === "free_text") progress.questions.freeTextLive += 1;
    } else {
      progress.questions.inGate += 1;
    }
  }
  return progress;
}

/** How many questions the tier gets: its share of the topic's budget, by its card target. */
export async function questionTarget(db: Conn, tier: Tier): Promise<number> {
  const tiers = await db
    .select({ targetCards: subtopic.targetCards })
    .from(subtopic)
    .where(eq(subtopic.topicId, tier.topicId));
  let total = 0;
  for (const one of tiers) total += one.targetCards;
  const budget = Math.min(QUESTION_BUDGET.max, Math.max(QUESTION_BUDGET.min, total));
  return Math.max(1, Math.round((budget * tier.targetCards) / total));
}

/** Whether the tier's cards are live: its target reached, or toad_sage let it finish short, and nothing left in the gate. */
export async function cardsLive(db: Conn, tier: Tier): Promise<boolean> {
  const progress = await tierProgress(db, tier.id);
  if (progress.accepted > 0 || progress.inGate > 0) return false;
  if (progress.live >= tier.targetCards) return true;
  return progress.live > 0 && (await allowedShort(db, tier.id));
}

/** Whether the tier's quiz is complete: its share of the questions live, its one free-text question among them. */
export async function quizLive(db: Conn, tier: Tier): Promise<boolean> {
  const progress = await tierProgress(db, tier.id);
  if (progress.questions.freeTextLive === 0) return false;
  return progress.questions.live >= (await questionTarget(db, tier));
}

/** Whether the tier is written: its cards live, then its quiz. */
export async function tierFinished(db: Conn, tier: Tier): Promise<boolean> {
  if (!(await cardsLive(db, tier))) return false;
  return quizLive(db, tier);
}

/** Whether the topic is taught in one pass, with no tiers (ADR-0106). */
export async function isTierless(db: Conn, topicId: string): Promise<boolean> {
  const [found] = await db.select({ scope: topic.scope }).from(topic).where(eq(topic.id, topicId));
  if (!found) return false;
  return TIERLESS_SCOPES.includes(found.scope);
}

/** The tier's writer helper, if one was started. */
export async function writerOf(db: Conn, tierId: string): Promise<string | undefined> {
  const [found] = await db
    .select({ helper: sql<string>`${harnessRecord.body} ->> 'helper'` })
    .from(harnessRecord)
    .where(
      and(
        eq(harnessRecord.kind, "brief"),
        sql`${harnessRecord.body} ->> 'task' = 'tier_writer'`,
        sql`${harnessRecord.body} ->> 'subtopic' = ${tierId}`,
      ),
    )
    .limit(1);
  return found?.helper;
}

export function topicOfTadpole(context: ToolContext): string {
  if (!context.chat.topicId) throw new ToolError("Only a topic's tadpole runs its tiers.");
  return context.chat.topicId;
}

/** What code writes as it runs a topic's tiers. */
export const TIERS_AUTHOR: Author = { kind: "code", component: "tiers" };

/**
 * Starts a writer for each of the topic's tiers that has none and whose lower tiers' cards are
 * live: every first tier once the curriculum is published, and each higher tier as the tier below
 * it goes live. Each writer is the tadpole's helper.
 */
export async function startReadyTiers(tx: Tx, topicId: string): Promise<BriefRecord[]> {
  const tiers = await tx
    .select()
    .from(subtopic)
    .where(eq(subtopic.topicId, topicId))
    .orderBy(asc(subtopic.position), asc(subtopic.difficulty));
  const tadpole = await openTopicChat(tx, "tadpole", topicId);
  const briefs: BriefRecord[] = [];
  for (const tier of tiers) {
    if (await writerOf(tx, tier.id)) continue;
    if (!(await lowerTiersLive(tx, tier, tiers))) continue;
    const { brief } = await startHelper(tx, tadpole, TIERS_AUTHOR, {
      task: "tier_writer",
      brief: `Write the ${tier.difficulty} tier of "${tier.title}": its ${tier.targetCards} cards first, and its questions once they are live.`,
      topic: topicId,
      subtopic: tier.id,
    });
    briefs.push(brief);
  }
  return briefs;
}

async function lowerTiersLive(tx: Tx, tier: Tier, tiers: Tier[]): Promise<boolean> {
  for (const other of tiers) {
    if (other.subtopicGroupId !== tier.subtopicGroupId) continue;
    if (difficultyRank(other.difficulty) >= difficultyRank(tier.difficulty)) continue;
    if (!(await cardsLive(tx, other))) return false;
  }
  return true;
}

/**
 * Puts the tier's cards live once it has reached its target (or toad_sage let it finish short)
 * with nothing left in the gate and the art drawn on every accepted card that asked for it. Then
 * it briefs the writer on the tier's questions and starts the tiers this one unblocked. True if it
 * did.
 */
export async function putCardsLiveIfDone(tx: Tx, tier: Tier): Promise<boolean> {
  const progress = await tierProgress(tx, tier.id);
  if (progress.accepted === 0 || progress.inGate > 0) return false;
  if (progress.awaitingArt > 0) return false;
  const reached = progress.accepted + progress.live >= tier.targetCards;
  if (!reached && !(await allowedShort(tx, tier.id))) return false;
  await tx
    .update(card)
    .set({ status: "active" })
    .where(
      and(
        eq(card.subtopicId, tier.id),
        eq(card.status, "draft"),
        sql`${card.genMeta} ->> 'stage' = 'accepted'`,
      ),
    );
  const writer = await writerOf(tx, tier.id);
  if (writer) {
    const cards = progress.accepted + progress.live;
    const questions = await questionTarget(tx, tier);
    await createRecord(tx, BriefRecord, {
      kind: "brief",
      author: TIERS_AUTHOR,
      body: {
        helper: writer,
        task: "tier_writer",
        brief: `The tier's ${cards} cards are live. Write its ${questions} questions: each from one of its cards, one of them free text and the rest MCQs.`,
        topic: tier.topicId,
        path: null,
        subtopic: tier.id,
      },
    });
  }
  await startReadyTiers(tx, tier.topicId);
  return true;
}

/**
 * Starts a pass-2 verifier on cards past pass 1 or questions just written. Each verifier gets its
 * own batch, so two never share an item, and reads it fresh: its brief is code's, never the
 * writer's or pass 1's reasoning.
 */
export async function startVerifier(
  tx: Tx,
  tier: Tier,
  items: { cards: string[]; questions: string[] },
): Promise<BriefRecord> {
  const what: string[] = [];
  if (items.cards.length > 0) what.push(`${items.cards.length} cards`);
  if (items.questions.length > 0) what.push(`${items.questions.length} questions`);
  const tadpole = await openTopicChat(tx, "tadpole", tier.topicId);
  const started = await startHelper(tx, tadpole, TIERS_AUTHOR, {
    task: "verifier",
    brief: `Check the ${what.join(" and ")} of the ${tier.difficulty} tier of "${tier.title}" given you: read_survivors shows them.`,
    topic: tier.topicId,
    subtopic: tier.id,
  });
  const assigned = sql`jsonb_build_object('verifier', ${started.chat.id}::text)`;
  if (items.cards.length > 0) {
    await tx
      .update(card)
      .set({ genMeta: sql`${card.genMeta} || ${assigned} || '{"stage": "verifying"}'::jsonb` })
      .where(inArray(card.id, items.cards));
  }
  if (items.questions.length > 0) {
    await tx
      .update(question)
      .set({ genMeta: sql`${question.genMeta} || ${assigned}` })
      .where(inArray(question.id, items.questions));
  }
  return started.brief;
}

/** Completes the topic's job once every tier is written; true if it did. */
export async function finishTopicIfDone(tx: Tx, topicId: string): Promise<boolean> {
  const tiers = await tx.select().from(subtopic).where(eq(subtopic.topicId, topicId));
  for (const tier of tiers) {
    if (!(await tierFinished(tx, tier))) return false;
  }
  const job = await latestJob(tx, topicId);
  if (job?.status !== "running") return false;
  await tx
    .update(generationJob)
    .set({ status: "completed", completedAt: new Date() })
    .where(eq(generationJob.id, job.id));
  return true;
}

// -- the tadpole's -----------------------------------------------------------

export function listSubtopicsTool(deps: AgentDeps): HarnessTool {
  return {
    name: "list_subtopics",
    label: "List the topic's tiers",
    description: deps.prompts.render("tools/list-subtopics.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "read",
    async execute(_params, context) {
      const topicId = topicOfTadpole(context);
      const tiers = await context.db
        .select()
        .from(subtopic)
        .where(eq(subtopic.topicId, topicId))
        .orderBy(asc(subtopic.position), asc(subtopic.difficulty));
      const shown = [];
      for (const tier of tiers) {
        shown.push({
          ...tier,
          progress: await tierProgress(context.db, tier.id),
          questionTarget: await questionTarget(context.db, tier),
          writer: (await writerOf(context.db, tier.id)) ?? null,
          cardsLive: await cardsLive(context.db, tier),
          finished: await tierFinished(context.db, tier),
          short: await allowedShort(context.db, tier.id),
        });
      }
      return {
        value: deps.prompts.render("tool-results/subtopics.njk", { tiers: shown }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

// -- the tier writer's ---------------------------------------------------------

/** A tier's grounding sections, numbered from 1 in the order the curriculum names them. */
export async function groundingOf(
  deps: AgentDeps,
  tier: Tier,
): Promise<{ number: number; chunkId: string; path: string; heading: string | null; text: string }[]> {
  const refs = tier.groundingRefs ?? [];
  if (refs.length === 0) return [];
  const { chunkIds } = await resolveGrounding(deps.universe, refs);
  if (chunkIds.length === 0) return [];
  const rows = await deps.universe
    .select({ id: chunk.id, path: document.sourcePath, heading: chunk.heading, text: chunk.text })
    .from(chunk)
    .innerJoin(document, eq(document.id, chunk.documentId))
    .where(inArray(chunk.id, chunkIds));
  const byId = new Map(rows.map((row) => [row.id, row]));
  const passages = [];
  for (const id of chunkIds) {
    const row = byId.get(id);
    if (row)
      passages.push({
        number: passages.length + 1,
        chunkId: id,
        path: row.path,
        heading: row.heading,
        text: row.text,
      });
  }
  return passages;
}

export function readGroundingTool(deps: AgentDeps): HarnessTool {
  return {
    name: "read_grounding",
    label: "Read the tier's grounding",
    description: deps.prompts.render("tools/read-grounding.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "read",
    async execute(_params, context) {
      const tier = await tierOfHelper(context);
      const passages = await groundingOf(deps, tier);
      return {
        value: deps.prompts.render("tool-results/grounding.njk", { tier, passages }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

export function readCardsTool(deps: AgentDeps): HarnessTool {
  return {
    name: "read_cards",
    label: "Read the tier's cards",
    description: deps.prompts.render("tools/read-cards.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "read",
    async execute(_params, context) {
      const tier = await tierOfHelper(context);
      const cards = await context.db
        .select()
        .from(card)
        .where(and(eq(card.subtopicId, tier.id), ne(card.status, "rejected")))
        .orderBy(asc(card.createdAt));
      const rejected = await context.db
        .select({
          title: rejectedCard.canonicalTitle,
          stage: rejectedCard.stage,
          reason: rejectedCard.reason,
        })
        .from(rejectedCard)
        .where(eq(rejectedCard.subtopicId, tier.id))
        .orderBy(asc(rejectedCard.createdAt));
      const group = await context.db
        .select()
        .from(subtopic)
        .where(eq(subtopic.subtopicGroupId, tier.subtopicGroupId));
      const lowerIds = group
        .filter((other) => difficultyRank(other.difficulty) < difficultyRank(tier.difficulty))
        .map((other) => other.id);
      let lower: CardRow[] = [];
      if (lowerIds.length > 0) {
        lower = await context.db
          .select()
          .from(card)
          .where(and(inArray(card.subtopicId, lowerIds), eq(card.status, "active")));
      }
      const titles = await context.db
        .select({ title: card.title, canonicalTitle: card.canonicalTitle, difficulty: card.difficulty })
        .from(card)
        .where(and(eq(card.topicId, tier.topicId), ne(card.status, "rejected")));
      const questions = await context.db
        .select()
        .from(question)
        .where(and(eq(question.subtopicId, tier.id), ne(question.status, "rejected")));
      return {
        value: deps.prompts.render("tool-results/cards.njk", {
          tier,
          cards: cards.map((row) => ({ ...row, meta: metaOf(row) })),
          rejected,
          lower,
          titles,
          questions,
          progress: await tierProgress(context.db, tier.id),
          questionTarget: await questionTarget(context.db, tier),
          artQuotas: artQuotas(((tier.cardTypeQuotas ?? {}) as Record<string, number>).ascii ?? 0),
        }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

const PlanParameters = Type.Object(
  {
    briefs: Type.Array(
      Type.Object(
        {
          concept: Text,
          form: Type.Enum([...CARD_TYPES].filter((form) => form !== "image")),
          angle: Text,
        },
        CLOSED,
      ),
      { minItems: 1 },
    ),
  },
  CLOSED,
);

export function planCardsTool(deps: AgentDeps): HarnessTool<typeof PlanParameters> {
  return {
    name: "plan_cards",
    label: "Plan the tier's cards",
    description: deps.prompts.render("tools/plan-cards.njk", {}),
    parameters: PlanParameters,
    kind: "change",
    async execute(params, context) {
      const tier = await tierOfHelper(context);
      const body = { subtopic: tier.id, briefs: params.briefs };
      const [first] = await context.db
        .select({ id: harnessRecord.id })
        .from(harnessRecord)
        .where(
          and(
            eq(harnessRecord.kind, "card_plan"),
            eq(harnessRecord.version, 1),
            sql`${harnessRecord.body} ->> 'subtopic' = ${tier.id}`,
          ),
        )
        .limit(1);
      let plan: CardPlanRecord;
      if (first) {
        const latest = await readLatestRecord(context.db, CardPlanRecord, "card_plan", first.id);
        plan = await changeRecord(context.db, CardPlanRecord, {
          from: refOf(latest),
          status: "active",
          author: context.author,
          reason: "Planned again",
          body,
        });
      } else {
        plan = await createRecord(context.db, CardPlanRecord, {
          kind: "card_plan",
          author: context.author,
          body,
        });
      }
      return recordsStored(context.db, deps.prompts, [plan]);
    },
  };
}

export const CardDraft = Type.Object(
  {
    title: Type.String({ minLength: 1, description: "The feed's title: playful some of the time" }),
    canonical_title: Type.String({ minLength: 1, description: "The concept's literal name" }),
    summary: Type.String({ minLength: 1, description: "A purpose-written hook, not a truncation" }),
    body: Type.String({ minLength: 1, description: "Markdown; plain, exact and true" }),
    passages: Type.Array(Type.Integer({ minimum: 1 }), {
      minItems: 1,
      description: "The grounding passages it is written from, by number",
    }),
    form: Type.Enum([...CARD_TYPES].filter((form) => form !== "image")),
    art_request: Type.Optional(
      Type.Object(
        {
          kind: Type.Enum([...ART_KINDS], { description: "A gag, or a small informative drawing" }),
          show: Type.String({ minLength: 1, description: "What the ASCII art should show" }),
          ideas: Type.String({ minLength: 1, description: "Ideas for drawing it" }),
        },
        CLOSED,
      ),
    ),
    hero: Type.Boolean({ description: "The tier's one hero card: the concept's best way in" }),
  },
  CLOSED,
);

type Draft = Static<typeof CardDraft>;

/**
 * A topic whose tiers name no code cards has no code, so no body carries a code block. On a code
 * subject any card may hold one and still counts as its own form (the owner, 2026-10-13): an ascii
 * card with code is an ascii card.
 */
export async function codeAllowedIn(db: Db | Tx, tier: Tier): Promise<boolean> {
  const coded = await db
    .select({ id: subtopic.id })
    .from(subtopic)
    .where(
      and(
        eq(subtopic.topicId, tier.topicId),
        sql`coalesce((${subtopic.cardTypeQuotas} ->> 'code')::int, 0) > 0`,
      ),
    )
    .limit(1);
  return coded.length > 0;
}

/**
 * Every structural fault of a draft, named: lengths, prose length, code where the tier has none,
 * mermaid, leaked correction notes, and passages outside the grounding.
 */
export function draftProblems(
  draft: Omit<Draft, "passages" | "form" | "art_request" | "hero"> & { passages?: number[] },
  passages: number,
  codeAllowed: boolean,
): string[] {
  const problems: string[] = [];
  if (draft.title.length > LIMITS.title)
    problems.push(`the title is ${draft.title.length} characters; at most ${LIMITS.title}`);
  if (draft.canonical_title.length > LIMITS.canonicalTitle) {
    problems.push(
      `the canonical title is ${draft.canonical_title.length} characters; at most ${LIMITS.canonicalTitle}`,
    );
  }
  if (draft.summary.length > LIMITS.summary)
    problems.push(`the summary is ${draft.summary.length} characters; at most ${LIMITS.summary}`);
  if (draft.body.length < LIMITS.bodyMin || draft.body.length > LIMITS.bodyMax) {
    problems.push(`the body is ${draft.body.length} characters; give ${LIMITS.bodyMin} to ${LIMITS.bodyMax}`);
  }
  const prose = draft.body.replace(FENCE, "").trim();
  if (prose.length > PROSE_MAX) {
    problems.push(
      `its prose outside code and diagrams is ${prose.length} characters; at most ${PROSE_MAX}: a card is one idea`,
    );
  }
  for (const fence of draft.body.matchAll(FENCE)) {
    const language = (fence[1] ?? "").trim();
    if (language !== "mermaid" && !codeAllowed) {
      problems.push("this topic has no code cards, so a body has no code block: say it in words");
    }
  }
  for (const fence of draft.body.matchAll(/```mermaid\n([\s\S]*?)```/g)) {
    const first = (fence[1] ?? "").trim().split("\n")[0] ?? "";
    if (!MERMAID_TYPES.test(first))
      problems.push(`a mermaid block opens with "${first}", not a diagram type`);
    // An emoji is one character but two columns, and breaks the diagram's text measuring.
    if (/\p{Extended_Pictographic}/u.test(fence[1] ?? "")) problems.push("a mermaid block has an emoji");
    if (MERMAID_STYLING.test(fence[1] ?? "")) {
      problems.push(
        "a mermaid block styles its nodes; every flowchart is drawn black on white, so leave colour out",
      );
    }
  }
  if (EDITORIAL_NOTE.test(draft.body))
    problems.push("the body carries a correction note; notes go in `note`");
  if ((draft.body.match(/```/g)?.length ?? 0) % 2 !== 0) problems.push("a fenced block is never closed");
  for (const number of draft.passages ?? []) {
    if (number > passages) problems.push(`it cites passage ${number}; the grounding has ${passages}`);
  }
  return problems;
}

const WriteCardsParameters = Type.Object({ cards: Type.Array(CardDraft, { minItems: 1 }) }, CLOSED);

export function writeCardsTool(deps: AgentDeps): HarnessTool<typeof WriteCardsParameters> {
  return {
    name: "write_cards",
    label: "Write drafts",
    description: deps.prompts.render("tools/write-cards.njk", {}),
    parameters: WriteCardsParameters,
    kind: "change",
    async execute(params, context) {
      const tier = await tierOfHelper(context);
      const grounding = await groundingOf(deps, tier);
      const standing = await context.db
        .select()
        .from(card)
        .where(and(eq(card.subtopicId, tier.id), ne(card.status, "rejected")));
      // Each draft that passes is stored, and only a faulty one is refused, so a batch with one
      // fault never has to be written again whole (the owner's rule: no output paid for twice).
      const room = tier.targetCards - standing.length;
      const quotas = (tier.cardTypeQuotas ?? {}) as Record<string, number>;
      const forms = new Map<string, number>();
      for (const row of standing) forms.set(metaOf(row).form, (forms.get(metaOf(row).form) ?? 0) + 1);
      const artQuota = artQuotas(quotas.ascii ?? 0);
      const arts = new Map<string, number>();
      for (const row of standing) {
        const kind = metaOf(row).art?.kind;
        if (kind) arts.set(kind, (arts.get(kind) ?? 0) + 1);
      }
      let heroes = standing.filter((row) => row.isHero).length;
      const kept: Draft[] = [];
      const refused: string[] = [];
      const codeAllowed = await codeAllowedIn(context.db, tier);
      params.cards.forEach((draft, index) => {
        const where = `card ${index + 1} ("${draft.canonical_title}")`;
        const problems = draftProblems(draft, grounding.length, codeAllowed);
        const used = forms.get(draft.form) ?? 0;
        const quota = quotas[draft.form] ?? 0;
        if (kept.length >= room) {
          problems.push(
            `the tier needed ${Math.max(room, 0)} more cards to reach its target of ${tier.targetCards}`,
          );
        } else if (used >= quota) {
          problems.push(`the tier's quota for ${draft.form} cards is ${quota}, and it has them all`);
        } else if (draft.hero && heroes >= 1) {
          problems.push("the tier has its one hero card already");
        }
        const art = draft.art_request?.kind;
        if (draft.form === "ascii" && !art) {
          problems.push("an ascii card asks for its art: a gag or an informative drawing");
        }
        if (draft.form === "ascii" && art && (arts.get(art) ?? 0) >= artQuota[art]) {
          problems.push(`the tier's quota for ${art} art is ${artQuota[art]}, and it has them all`);
        }
        if (draft.form === "diagram" && !FLOWCHART.test(draft.body)) {
          problems.push("a diagram card is a mermaid flowchart: a ```mermaid fence opening with `flowchart`");
        }
        if (problems.length > 0) {
          refused.push(`${where}: ${problems.join("; ")}`);
          return;
        }
        forms.set(draft.form, used + 1);
        if (draft.form !== "ascii") {
          // Only an ascii card carries art, so a request on any other is dropped, not refused.
          delete draft.art_request;
        } else if (art) {
          arts.set(art, (arts.get(art) ?? 0) + 1);
        }
        if (draft.hero) heroes += 1;
        kept.push(draft);
      });
      if (kept.length === 0) {
        throw new ToolError(
          `Nothing was stored; fix every problem and call again:\n- ${refused.join("\n- ")}`,
        );
      }
      const vectors = await deps.embedder.embedPassage(kept.map((draft) => draft.body));
      const chunkIds = new Map(grounding.map((passage) => [passage.number, passage.chunkId]));
      const { written, gate } = await context.db.transaction(async (tx) => {
        const rows = await tx
          .insert(card)
          .values(
            kept.map((draft, index) => {
              const meta: CardMeta = {
                stage: "correcting",
                form: draft.form,
                ...(draft.art_request ? { art: draft.art_request } : {}),
                writer: context.chat.id,
                passages: draft.passages,
              };
              return {
                familyId: randomUUID(),
                topicId: tier.topicId,
                subtopicId: tier.id,
                difficulty: tier.difficulty,
                title: draft.title.trim(),
                canonicalTitle: draft.canonical_title.trim(),
                summary: draft.summary.trim(),
                body: draft.body.trim(),
                contentEmbedding: vectors[index] as number[],
                embeddingModel: deps.embedder.modelName,
                groundedChunkIds: draft.passages.map((number) => chunkIds.get(number) as string),
                genMeta: { ...meta, model: context.run.model, run: context.run.id },
                archetype: classifyArchetype(draft.body),
                isHero: draft.hero,
              };
            }),
          )
          .returning({ id: card.id, canonicalTitle: card.canonicalTitle });
        const sent = await sendToPassOne(
          tx,
          tier,
          context,
          rows.map((row) => row.id),
        );
        return { written: rows, gate: sent };
      });
      const lines = written.map((row) => `- ${row.id}: ${row.canonicalTitle}`).join("\n");
      const stored = await recordsStored(context.db, deps.prompts, [gate]);
      let value = `Stored ${written.length} drafts, now in pass 1:\n${lines}\n${String(stored.value)}\nThe verdicts wake you.`;
      if (refused.length > 0) {
        value += `\n\nNot stored, so write only these again, each with its fault fixed:\n- ${refused.join("\n- ")}`;
      }
      return { ...stored, value };
    },
  };
}

/** The corrector of a tier: one per writer, made when its first drafts are gated. */
async function correctorOf(db: Conn, tierId: string): Promise<string | undefined> {
  const [found] = await db
    .select({ helper: sql<string>`${harnessRecord.body} ->> 'helper'` })
    .from(harnessRecord)
    .where(
      and(
        eq(harnessRecord.kind, "brief"),
        sql`${harnessRecord.body} ->> 'task' = 'corrector'`,
        sql`${harnessRecord.body} ->> 'subtopic' = ${tierId}`,
      ),
    )
    .limit(1);
  return found?.helper;
}

/** Sends new drafts to the tier's corrector, starting it with the tier's first drafts. */
async function sendToPassOne(tx: Tx, tier: Tier, context: ToolContext, items: string[]): Promise<GateRecord> {
  let corrector = await correctorOf(tx, tier.id);
  if (!corrector) {
    const tadpole = await openTopicChat(tx, "tadpole", tier.topicId);
    const started = await startHelper(tx, tadpole, TIERS_AUTHOR, {
      task: "corrector",
      brief: `Correct the drafts of the ${tier.difficulty} tier of "${tier.title}" as they come.`,
      topic: tier.topicId,
      subtopic: tier.id,
    });
    corrector = started.chat.id;
  }
  return createRecord(tx, GateRecord, {
    kind: "gate",
    author: context.author,
    body: { stage: "pass1", subtopic: tier.id, to: corrector, writer: context.chat.id, items },
  });
}

const QuestionDraft = Type.Object(
  {
    card: Id,
    kind: Type.Enum(["mcq", "free_text"]),
    stem: Type.String({ minLength: 1 }),
    options: Type.Optional(Type.Array(Type.String({ minLength: 1 }), { minItems: 4, maxItems: 4 })),
    correct_index: Type.Optional(Type.Integer({ minimum: 0, maximum: 3 })),
    rubric: Type.Optional(
      Type.String({ minLength: 1, description: "Levels 0 to 3, each saying what an answer at it holds" }),
    ),
    reference_answer: Type.Optional(Type.String({ minLength: 1 })),
    explanation: Type.String({ minLength: 1, description: "Why the answer is right, from the card" }),
  },
  CLOSED,
);

const WriteQuestionsParameters = Type.Object(
  { questions: Type.Array(QuestionDraft, { minItems: 1 }) },
  CLOSED,
);

/** An MCQ has four options (the old pipeline's quiz prompt), and a tier one free-text question. */
const MCQ_OPTIONS = 4;

export function writeQuestionsTool(deps: AgentDeps): HarnessTool<typeof WriteQuestionsParameters> {
  return {
    name: "write_questions",
    label: "Write questions",
    description: deps.prompts.render("tools/write-questions.njk", {}),
    parameters: WriteQuestionsParameters,
    kind: "change",
    async execute(params, context) {
      const tier = await tierOfHelper(context);
      if (!(await cardsLive(context.db, tier))) {
        throw new ToolError("Questions come once the tier's cards are live: your brief says when they are.");
      }
      const target = await questionTarget(context.db, tier);
      const live = await context.db
        .select({ id: card.id, difficulty: card.difficulty })
        .from(card)
        .where(and(eq(card.subtopicId, tier.id), eq(card.status, "active")));
      const difficultyOf = new Map(live.map((row) => [row.id, row.difficulty]));
      const existing = await context.db
        .select({ id: question.id, stem: question.stem, kind: question.kind, embedding: question.embedding })
        .from(question)
        .where(and(eq(question.subtopicId, tier.id), ne(question.status, "rejected")));
      let places = target - existing.length;
      let hasFreeText = existing.some((row) => row.kind === "free_text");
      const stems = await deps.embedder.embedPassage(params.questions.map((draft) => draft.stem));
      // Each question that passes is stored, and only a faulty one is refused, so one fault never
      // has every question written again (the owner's rule: no output paid for twice).
      const kept: { draft: (typeof params.questions)[number]; stem: number[] }[] = [];
      const refused: string[] = [];
      params.questions.forEach((draft, index) => {
        const problems: string[] = [];
        if (!difficultyOf.has(draft.card))
          problems.push(`card ${draft.card} is not a live card of this tier`);
        if (places <= 0) {
          problems.push(`the tier's ${target} questions are all written`);
        } else if (draft.kind === "free_text" && hasFreeText) {
          problems.push("the tier has its one free-text question; write an MCQ");
        } else if (draft.kind === "mcq" && !hasFreeText && places === 1) {
          problems.push("the last place is the tier's one free-text question");
        }
        if (draft.kind === "mcq") {
          const options = draft.options ?? [];
          if (options.length !== MCQ_OPTIONS) problems.push(`an MCQ has ${MCQ_OPTIONS} options`);
          const distinct = new Set(options.map((option) => option.trim().toLowerCase()));
          if (distinct.size !== options.length) problems.push("two options say the same thing");
          if (draft.correct_index === undefined || draft.correct_index >= options.length) {
            problems.push("correct_index must name one of its options, counting from 0");
          }
        } else {
          if (!draft.rubric || !draft.reference_answer) {
            problems.push("free text needs a rubric and a reference answer");
          }
          const levels = new Set(draft.rubric?.match(/\b[0-3](?=\s*[:=.)-])/g) ?? []);
          if (levels.size < 4) problems.push('the rubric gives each level 0 to 3, as "0: ...", "1: ..."');
        }
        const vector = stems[index] as number[];
        for (const other of existing) {
          if (other.embedding && cosine(vector, other.embedding) >= NEAR_DUPLICATE) {
            problems.push(`its stem repeats question ${other.id}, "${other.stem}"`);
          }
        }
        for (const earlier of kept) {
          if (cosine(vector, earlier.stem) >= NEAR_DUPLICATE) {
            problems.push(`its stem repeats "${earlier.draft.stem}", stored in this call`);
          }
        }
        if (problems.length > 0) {
          refused.push(`question ${index + 1}: ${problems.join("; ")}`);
          return;
        }
        places -= 1;
        if (draft.kind === "free_text") hasFreeText = true;
        kept.push({ draft, stem: vector });
      });
      if (kept.length === 0) {
        throw new ToolError(
          `Nothing was stored; fix every problem and call again:\n- ${refused.join("\n- ")}`,
        );
      }
      const brief = await context.db.transaction(async (tx) => {
        const written = await tx
          .insert(question)
          .values(
            kept.map(({ draft, stem }) => ({
              subtopicId: tier.id,
              cardId: draft.card,
              // A tierless topic's cards run easy to advanced, so a question takes its card's difficulty.
              difficulty: difficultyOf.get(draft.card) ?? tier.difficulty,
              kind: draft.kind,
              stem: draft.stem.trim(),
              options: draft.kind === "mcq" ? (draft.options ?? []).map((option) => option.trim()) : null,
              correctIndex: draft.kind === "mcq" ? (draft.correct_index ?? null) : null,
              rubric: draft.kind === "free_text" ? (draft.rubric ?? null) : null,
              referenceAnswer: draft.kind === "free_text" ? (draft.reference_answer ?? null) : null,
              explanation: draft.explanation,
              embedding: stem,
              embeddingModel: deps.embedder.modelName,
              genMeta: { stage: "gated", writer: context.chat.id, run: context.run.id },
            })),
          )
          .returning({ id: question.id });
        return startVerifier(tx, tier, { cards: [], questions: written.map((row) => row.id) });
      });
      const stored = await recordsStored(context.db, deps.prompts, [brief]);
      let value = `Stored ${kept.length} questions, now with a pass-2 verifier:\n${String(stored.value)}\nIts verdicts wake you.`;
      if (refused.length > 0) {
        value += `\nNot stored, so write only these again, each with its fault fixed:\n- ${refused.join("\n- ")}`;
      }
      return { ...stored, value };
    },
  };
}

export type { Difficulty };
