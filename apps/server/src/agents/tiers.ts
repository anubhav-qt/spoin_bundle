import { randomUUID } from "node:crypto";
import { cosine } from "@spoin/frog/embeddings";
import { resolveGrounding } from "@spoin/frog/retrieval";
import { chunk, document } from "@spoin/frog/schema";
import { type Difficulty, difficultyRank } from "@spoin/shared/enums";
import { and, asc, eq, inArray, ne, sql } from "drizzle-orm";
import { type Static, Type } from "typebox";
import { classifyArchetype } from "../cards/archetype.ts";
import type { Db, Tx } from "../db/client.ts";
import { card, generationJob, harnessRecord, question, rejectedCard, subtopic } from "../db/schema.ts";
import { type Chat, readChat } from "../harness/chats.ts";
import { briefOf } from "../harness/helper-reports.ts";
import { latestJob } from "../harness/intake.ts";
import { recordsStored } from "../harness/outputs.ts";
import { changeRecord, createRecord, readLatestRecord, refOf } from "../harness/records.ts";
import { CARD_TYPES, CardPlanRecord, CLOSED, GateRecord, Id, Text } from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError } from "../harness/tools.ts";
import type { AgentDeps } from "./context.ts";
import { startHelper } from "./helpers.ts";

/*
 * A topic's cards and questions (harness-tools.md, task 0045), after its curriculum is projected:
 * the tadpole starts a writer helper on NIM per tier, each tier's drafts go through pass 1 and
 * pass 2, designer_toad draws each accepted card's art, and the tier goes live once it reaches its
 * target with every card's art and questions. What must be true is checked in code; a draft that
 * fails a check is refused and never stored.
 */

type Conn = Db | Tx;
export type Tier = typeof subtopic.$inferSelect;
type CardRow = typeof card.$inferSelect;

/**
 * Where a card is in the gate, kept in its `gen_meta` until it goes live: written, sent to pass 1,
 * past it, given to a pass-2 verifier, accepted.
 */
export type CardStage = "drafted" | "correcting" | "corrected" | "verifying" | "accepted";

/** What the writer said about a card beyond its text, and where the gate has it. */
export interface CardMeta {
  stage: CardStage;
  form: (typeof CARD_TYPES)[number];
  art: { show: string; ideas: string };
  writer: string;
  passages: number[];
  /** The pass-2 verifier given the card. */
  verifier?: string;
  /** Why pass 2 rejected it, for the writer. */
  feedback?: string;
}

/** Where a question is in the gate: written, sent to pass 2, or passed. */
export type QuestionStage = "written" | "gated" | "passed";

/** Near-duplicates: two bodies or stems this close in meaning say the same thing. */
export const NEAR_DUPLICATE = 0.92;

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
  drafted: number;
  inGate: number;
  accepted: number;
  rejected: number;
  withArt: number;
  live: number;
  questions: { written: number; gated: number; passed: number; rejected: number };
}

export async function tierProgress(db: Conn, tierId: string): Promise<TierProgress> {
  const cards = await db
    .select({ status: card.status, meta: card.genMeta, visualKind: card.visualKind })
    .from(card)
    .where(eq(card.subtopicId, tierId));
  const progress: TierProgress = {
    drafted: 0,
    inGate: 0,
    accepted: 0,
    rejected: 0,
    withArt: 0,
    live: 0,
    questions: { written: 0, gated: 0, passed: 0, rejected: 0 },
  };
  for (const row of cards) {
    const stage = (row.meta as { stage?: CardStage }).stage;
    if (row.status === "active") progress.live += 1;
    else if (row.status === "rejected") progress.rejected += 1;
    else if (stage === "accepted") {
      progress.accepted += 1;
      if (row.visualKind) progress.withArt += 1;
    } else if (stage === "drafted") progress.drafted += 1;
    else progress.inGate += 1;
  }
  const questions = await db
    .select({ status: question.status, meta: question.genMeta })
    .from(question)
    .where(eq(question.subtopicId, tierId));
  for (const row of questions) {
    const stage = (row.meta as { stage?: QuestionStage }).stage;
    if (row.status === "rejected") progress.questions.rejected += 1;
    else if (row.status === "active" || stage === "passed") progress.questions.passed += 1;
    else if (stage === "gated") progress.questions.gated += 1;
    else progress.questions.written += 1;
  }
  return progress;
}

/** Whether a tier is live: its target reached, or toad_sage let it finish short, and nothing left in the gate. */
export async function tierFinished(db: Conn, tier: Tier): Promise<boolean> {
  const progress = await tierProgress(db, tier.id);
  if (progress.accepted > 0 || progress.drafted > 0 || progress.inGate > 0) return false;
  if (progress.live >= tier.targetCards) return true;
  return progress.live > 0 && (await allowedShort(db, tier.id));
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
          writer: (await writerOf(context.db, tier.id)) ?? null,
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

const StartSubtopicParameters = Type.Object(
  {
    subtopic: Id,
    notes: Type.Optional(Type.String({ minLength: 1, description: "Anything the writer should know" })),
  },
  CLOSED,
);

export function startSubtopicTool(deps: AgentDeps): HarnessTool<typeof StartSubtopicParameters> {
  return {
    name: "start_subtopic",
    label: "Start a tier's writer",
    description: deps.prompts.render("tools/start-subtopic.njk", {}),
    parameters: StartSubtopicParameters,
    kind: "change",
    async execute(params, context) {
      const topicId = topicOfTadpole(context);
      const tier = await tierById(context.db, params.subtopic);
      if (tier.topicId !== topicId)
        throw new ToolError(`Subtopic ${tier.id} is not one of your topic's tiers.`);
      const writer = await writerOf(context.db, tier.id);
      if (writer) throw new ToolError(`The tier's writer is started already (chat ${writer}).`);
      const lower = await context.db
        .select()
        .from(subtopic)
        .where(eq(subtopic.subtopicGroupId, tier.subtopicGroupId));
      for (const other of lower) {
        if (difficultyRank(other.difficulty) >= difficultyRank(tier.difficulty)) continue;
        if (!(await tierFinished(context.db, other))) {
          throw new ToolError(`Its ${other.difficulty} tier (${other.id}) isn't live yet: start that first.`);
        }
      }
      let brief = `Write the ${tier.difficulty} tier of "${tier.title}" to its target of ${tier.targetCards} cards, with its questions.`;
      if (params.notes) brief = `${brief} ${params.notes}`;
      const { brief: stored } = await context.db.transaction((tx) =>
        startHelper(tx, context.chat, context.author, {
          task: "tier_writer",
          brief,
          topic: topicId,
          subtopic: tier.id,
        }),
      );
      return recordsStored(context.db, deps.prompts, [stored]);
    },
  };
}

const StartVerifierParameters = Type.Object(
  {
    subtopic: Id,
    brief: Type.String({
      minLength: 1,
      description: "What it should check and what context it gets; never the writer's or pass 1's reasoning",
    }),
  },
  CLOSED,
);

export function startVerifierTool(deps: AgentDeps): HarnessTool<typeof StartVerifierParameters> {
  return {
    name: "start_verifier",
    label: "Start pass 2 for a tier",
    description: deps.prompts.render("tools/start-verifier.njk", {}),
    parameters: StartVerifierParameters,
    kind: "change",
    async execute(params, context) {
      const topicId = topicOfTadpole(context);
      const tier = await tierById(context.db, params.subtopic);
      if (tier.topicId !== topicId)
        throw new ToolError(`Subtopic ${tier.id} is not one of your topic's tiers.`);
      const { brief, cards, questions } = await context.db.transaction(async (tx) => {
        const started = await startHelper(tx, context.chat, context.author, {
          task: "verifier",
          brief: params.brief,
          topic: topicId,
          subtopic: tier.id,
        });
        // What waits for pass 2 now is this verifier's alone, so two verifiers never share a card.
        const assigned = sql`jsonb_build_object('verifier', ${started.chat.id}::text)`;
        const givenCards = await tx
          .update(card)
          .set({ genMeta: sql`${card.genMeta} || ${assigned} || '{"stage": "verifying"}'::jsonb` })
          .where(
            and(
              eq(card.subtopicId, tier.id),
              eq(card.status, "draft"),
              sql`${card.genMeta} ->> 'stage' = 'corrected'`,
            ),
          )
          .returning({ id: card.id });
        const givenQuestions = await tx
          .update(question)
          .set({ genMeta: sql`${question.genMeta} || ${assigned}` })
          .where(
            and(
              eq(question.subtopicId, tier.id),
              eq(question.status, "draft"),
              sql`${question.genMeta} ->> 'stage' = 'gated'`,
              sql`NOT (${question.genMeta} ? 'verifier')`,
            ),
          )
          .returning({ id: question.id });
        if (givenCards.length === 0 && givenQuestions.length === 0) {
          throw new ToolError("Nothing of that tier is waiting for pass 2.");
        }
        return { brief: started.brief, cards: givenCards.length, questions: givenQuestions.length };
      });
      const stored = await recordsStored(context.db, deps.prompts, [brief]);
      return {
        ...stored,
        value: `${String(stored.value)}\nIt verifies ${cards} cards and ${questions} questions.`,
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
    art_request: Type.Object(
      {
        show: Type.String({ minLength: 1, description: "What the ASCII art should show" }),
        ideas: Type.String({ minLength: 1, description: "Ideas for drawing it" }),
      },
      CLOSED,
    ),
    hero: Type.Boolean({ description: "The tier's one hero card: the concept's best way in" }),
  },
  CLOSED,
);

type Draft = Static<typeof CardDraft>;

/** A tier whose quotas name no code cards is a topic with no code, so its bodies carry none either. */
export function codeAllowedIn(tier: Tier): boolean {
  const quotas = (tier.cardTypeQuotas ?? {}) as Record<string, number>;
  return (quotas.code ?? 0) > 0;
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
      problems.push("this tier has no code cards, so a body has no code block: say it in words");
    }
  }
  for (const fence of draft.body.matchAll(/```mermaid\n([\s\S]*?)```/g)) {
    const first = (fence[1] ?? "").trim().split("\n")[0] ?? "";
    if (!MERMAID_TYPES.test(first))
      problems.push(`a mermaid block opens with "${first}", not a diagram type`);
    // An emoji is one character but two columns, and breaks the diagram's text measuring.
    if (/\p{Extended_Pictographic}/u.test(fence[1] ?? "")) problems.push("a mermaid block has an emoji");
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
      let heroes = standing.filter((row) => row.isHero).length;
      const kept: Draft[] = [];
      const refused: string[] = [];
      params.cards.forEach((draft, index) => {
        const where = `card ${index + 1} ("${draft.canonical_title}")`;
        const problems = draftProblems(draft, grounding.length, codeAllowedIn(tier));
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
        if (problems.length > 0) {
          refused.push(`${where}: ${problems.join("; ")}`);
          return;
        }
        forms.set(draft.form, used + 1);
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
      const written = await context.db
        .insert(card)
        .values(
          kept.map((draft, index) => {
            const meta: CardMeta = {
              stage: "drafted",
              form: draft.form,
              art: draft.art_request,
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
      const lines = written.map((row) => `- ${row.id}: ${row.canonicalTitle}`).join("\n");
      let value = `Stored ${written.length} drafts:\n${lines}\nSend them through pass 1 with gate_cards.`;
      if (refused.length > 0) {
        value += `\n\nNot stored, so write only these again, each with its fault fixed:\n- ${refused.join("\n- ")}`;
      }
      return { value, dataSeen: [], recordsWritten: [] };
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

/** The writer's main chat: the tadpole that started it. */
export async function tadpoleOf(db: Conn, writer: Chat): Promise<Chat> {
  if (!writer.parentId) throw new ToolError("Only a tier's writer sends work through the gate.");
  return readChat(db, writer.parentId);
}

export function gateCardsTool(deps: AgentDeps): HarnessTool {
  return {
    name: "gate_cards",
    label: "Send drafts through the gate",
    description: deps.prompts.render("tools/gate-cards.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "change",
    async execute(_params, context) {
      const tier = await tierOfHelper(context);
      const drafts = await context.db
        .select({ id: card.id, meta: card.genMeta })
        .from(card)
        .where(
          and(
            eq(card.subtopicId, tier.id),
            eq(card.status, "draft"),
            sql`${card.genMeta} ->> 'stage' = 'drafted'`,
          ),
        );
      if (drafts.length === 0) throw new ToolError("No drafts are waiting: write some with write_cards.");
      const gate = await context.db.transaction(async (tx) => {
        await tx
          .update(card)
          .set({ genMeta: sql`${card.genMeta} || '{"stage": "correcting"}'::jsonb` })
          .where(
            inArray(
              card.id,
              drafts.map((draft) => draft.id),
            ),
          );
        let corrector = await correctorOf(tx, tier.id);
        if (!corrector) {
          const tadpole = await tadpoleOf(tx, context.chat);
          const started = await startHelper(tx, tadpole, context.author, {
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
          body: {
            stage: "pass1",
            subtopic: tier.id,
            to: corrector,
            writer: context.chat.id,
            items: drafts.map((draft) => draft.id),
          },
        });
      });
      const stored = await recordsStored(context.db, deps.prompts, [gate]);
      return {
        ...stored,
        value: `${String(stored.value)}\nThe verdicts wake you. Write more drafts meanwhile only if the tier needs them.`,
      };
    },
  };
}

const QuestionDraft = Type.Object(
  {
    card: Id,
    kind: Type.Enum(["mcq", "free_text"]),
    stem: Type.String({ minLength: 1 }),
    options: Type.Optional(Type.Array(Type.String({ minLength: 1 }), { minItems: 3, maxItems: 5 })),
    correct_index: Type.Optional(Type.Integer({ minimum: 0 })),
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

export function writeQuestionsTool(deps: AgentDeps): HarnessTool<typeof WriteQuestionsParameters> {
  return {
    name: "write_questions",
    label: "Write questions",
    description: deps.prompts.render("tools/write-questions.njk", {}),
    parameters: WriteQuestionsParameters,
    kind: "change",
    async execute(params, context) {
      const tier = await tierOfHelper(context);
      const progress = await tierProgress(context.db, tier.id);
      const reached = progress.accepted + progress.live >= tier.targetCards;
      if (!reached && !(await allowedShort(context.db, tier.id))) {
        throw new ToolError(
          `Questions come once the tier reaches its target: ${progress.accepted} of ${tier.targetCards} cards are accepted.`,
        );
      }
      const accepted = await context.db
        .select({ id: card.id })
        .from(card)
        .where(
          and(
            eq(card.subtopicId, tier.id),
            eq(card.status, "draft"),
            sql`${card.genMeta} ->> 'stage' = 'accepted'`,
          ),
        );
      const acceptedIds = new Set(accepted.map((row) => row.id));
      const stems = await deps.embedder.embedPassage(params.questions.map((draft) => draft.stem));
      const existing = await context.db
        .select({ id: question.id, stem: question.stem, embedding: question.embedding })
        .from(question)
        .where(and(eq(question.subtopicId, tier.id), ne(question.status, "rejected")));
      // Each question that passes is stored, and only a faulty one is refused, so one fault never
      // has every question written again (the owner's rule: no output paid for twice).
      const kept: { draft: (typeof params.questions)[number]; stem: number[] }[] = [];
      const refused: string[] = [];
      params.questions.forEach((draft, index) => {
        const problems: string[] = [];
        if (!acceptedIds.has(draft.card))
          problems.push(`card ${draft.card} is not an accepted card of this tier`);
        if (draft.kind === "mcq") {
          const options = draft.options ?? [];
          if (options.length < 3) problems.push("an MCQ has 3 to 5 options");
          const distinct = new Set(options.map((option) => option.trim().toLowerCase()));
          if (distinct.size !== options.length) problems.push("two options say the same thing");
          if (draft.correct_index === undefined || draft.correct_index >= options.length) {
            problems.push("correct_index must name one of its options, counting from 0");
          }
        } else {
          if (!draft.rubric || !draft.reference_answer)
            problems.push("free text needs a rubric and a reference answer");
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
        kept.push({ draft, stem: vector });
      });
      if (kept.length === 0) {
        throw new ToolError(
          `Nothing was stored; fix every problem and call again:\n- ${refused.join("\n- ")}`,
        );
      }
      const written = await context.db
        .insert(question)
        .values(
          kept.map(({ draft, stem }) => ({
            subtopicId: tier.id,
            cardId: draft.card,
            difficulty: tier.difficulty,
            kind: draft.kind,
            stem: draft.stem.trim(),
            options: draft.kind === "mcq" ? (draft.options ?? []).map((option) => option.trim()) : null,
            correctIndex: draft.kind === "mcq" ? (draft.correct_index ?? null) : null,
            rubric: draft.kind === "free_text" ? (draft.rubric ?? null) : null,
            referenceAnswer: draft.kind === "free_text" ? (draft.reference_answer ?? null) : null,
            explanation: draft.explanation,
            embedding: stem,
            embeddingModel: deps.embedder.modelName,
            genMeta: { stage: "written", writer: context.chat.id, run: context.run.id },
          })),
        )
        .returning({ id: question.id });
      let value = `Stored ${written.length} questions. Send them to pass 2 with gate_questions.`;
      if (refused.length > 0) {
        value += `\nNot stored, so write only these again, each with its fault fixed:\n- ${refused.join("\n- ")}`;
      }
      return { value, dataSeen: [], recordsWritten: [] };
    },
  };
}

export function gateQuestionsTool(deps: AgentDeps): HarnessTool {
  return {
    name: "gate_questions",
    label: "Send questions to pass 2",
    description: deps.prompts.render("tools/gate-questions.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "change",
    async execute(_params, context) {
      const tier = await tierOfHelper(context);
      const gate = await context.db.transaction(async (tx) => {
        const written = await tx
          .update(question)
          .set({ genMeta: sql`${question.genMeta} || '{"stage": "gated"}'::jsonb` })
          .where(
            and(
              eq(question.subtopicId, tier.id),
              eq(question.status, "draft"),
              sql`${question.genMeta} ->> 'stage' = 'written'`,
            ),
          )
          .returning({ id: question.id });
        if (written.length === 0)
          throw new ToolError("No questions are waiting: write some with write_questions.");
        const tadpole = await tadpoleOf(tx, context.chat);
        return createRecord(tx, GateRecord, {
          kind: "gate",
          author: context.author,
          body: {
            stage: "questions",
            subtopic: tier.id,
            to: tadpole.id,
            writer: context.chat.id,
            items: written.map((row) => row.id),
          },
        });
      });
      return recordsStored(context.db, deps.prompts, [gate]);
    },
  };
}

export function submitTierTool(deps: AgentDeps): HarnessTool {
  return {
    name: "submit_tier",
    label: "Put the tier live",
    description: deps.prompts.render("tools/submit-tier.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "change",
    async execute(_params, context) {
      const tier = await tierOfHelper(context);
      const progress = await tierProgress(context.db, tier.id);
      const problems: string[] = [];
      const short = await allowedShort(context.db, tier.id);
      if (progress.accepted + progress.live < tier.targetCards && !short) {
        problems.push(`${progress.accepted} of ${tier.targetCards} cards are accepted`);
      }
      if (progress.accepted === 0) problems.push("no card is accepted");
      if (progress.drafted + progress.inGate > 0) {
        problems.push(`${progress.drafted + progress.inGate} cards are still on their way through the gate`);
      }
      if (progress.withArt < progress.accepted) {
        problems.push(
          `${progress.accepted - progress.withArt} accepted cards are still waiting for their art`,
        );
      }
      if (progress.questions.written + progress.questions.gated > 0) {
        problems.push(
          `${progress.questions.written + progress.questions.gated} questions haven't passed pass 2 yet`,
        );
      }
      const unquestioned = await context.db.execute(sql`
        SELECT c.id FROM card c
        WHERE c.subtopic_id = ${tier.id} AND c.status = 'draft' AND c.gen_meta ->> 'stage' = 'accepted'
          AND NOT EXISTS (
            SELECT 1 FROM question q
            WHERE q.card_id = c.id AND q.status <> 'rejected' AND q.gen_meta ->> 'stage' = 'passed'
          )
      `);
      if (unquestioned.rows.length > 0)
        problems.push(`${unquestioned.rows.length} accepted cards have no passed question`);
      if (problems.length > 0) throw new ToolError(`The tier can't go live yet:\n- ${problems.join("\n- ")}`);

      const done = await context.db.transaction(async (tx) => {
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
        await tx
          .update(question)
          .set({ status: "active" })
          .where(
            and(
              eq(question.subtopicId, tier.id),
              eq(question.status, "draft"),
              sql`${question.genMeta} ->> 'stage' = 'passed'`,
            ),
          );
        return finishTopicIfDone(tx, tier.topicId);
      });
      let said = `The ${tier.difficulty} tier of "${tier.title}" is live.`;
      if (done) said = `${said} It was the topic's last: the topic is written, and its job is complete.`;
      return { value: `${said} Report to the tadpole now.`, dataSeen: [], recordsWritten: [] };
    },
  };
}

/** Completes the topic's job once every tier is live; true if it did. */
async function finishTopicIfDone(tx: Tx, topicId: string): Promise<boolean> {
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

export type { Difficulty };
