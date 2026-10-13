import { cosine } from "@spoin/frog/embeddings";
import { DIFFICULTIES } from "@spoin/shared/enums";
import { and, asc, eq, inArray, ne, sql } from "drizzle-orm";
import { Type } from "typebox";
import { classifyArchetype } from "../cards/archetype.ts";
import type { Db, Tx } from "../db/client.ts";
import { card, question, rejectedCard, topic } from "../db/schema.ts";
import { recordsStored } from "../harness/outputs.ts";
import { createRecord } from "../harness/records.ts";
import { CLOSED, GateRecord, Id, VerdictsRecord } from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError, type ToolOutput } from "../harness/tools.ts";
import type { AgentDeps } from "./context.ts";
import {
  type CardMeta,
  codeAllowedIn,
  draftProblems,
  groundingOf,
  metaOf,
  NEAR_DUPLICATE,
  type Tier,
  tierOfHelper,
  writerOf,
} from "./tiers.ts";

/*
 * The gate's two passes (harness-tools.md, task 0045). Pass 1, one corrector per tier, rewrites
 * each draft or leaves it be and never rejects; code rejects a near-duplicate. Its survivors go to
 * the tadpole, which starts a pass-2 verifier with a brief of its own. Pass 2 rates each card's
 * difficulty itself and accepts or rejects it, solves each MCQ without its key, and judges each
 * free-text rubric. Each pass's verdicts wake the writer; pass 2's accepted cards wake designer_toad.
 */

type Conn = Db | Tx;
type CardRow = typeof card.$inferSelect;
type QuestionRow = typeof question.$inferSelect;

async function topicNameOf(db: Conn, topicId: string): Promise<string> {
  const [found] = await db.select({ name: topic.canonicalName }).from(topic).where(eq(topic.id, topicId));
  return found?.name ?? "";
}

/** Each card's own passages, numbered as in the tier's grounding. */
async function withPassages(deps: AgentDeps, tier: Tier, rows: CardRow[]) {
  const grounding = await groundingOf(deps, tier);
  return rows.map((row) => {
    const meta = metaOf(row);
    const passages = grounding.filter((passage) => meta.passages.includes(passage.number));
    return { ...row, meta, passages };
  });
}

/** A card or question is named once in a call, and only one waiting for this chat. */
function settleOnce<Row extends { id: string }>(
  waiting: Row[],
  ids: string[],
  what: string,
): Map<string, Row> {
  const byId = new Map(waiting.map((row) => [row.id, row]));
  const problems: string[] = [];
  const seen = new Set<string>();
  for (const id of ids) {
    if (!byId.has(id)) problems.push(`${what} ${id} isn't one waiting for you`);
    if (seen.has(id)) problems.push(`${what} ${id} is named twice`);
    seen.add(id);
  }
  if (problems.length > 0) throw new ToolError(`Nothing was stored:\n- ${problems.join("\n- ")}`);
  return byId;
}

async function rejectCard(
  tx: Tx,
  row: CardRow,
  tier: Tier,
  stage: "near_duplicate" | "verification",
  reason: string,
) {
  await tx
    .update(card)
    .set({
      status: "rejected",
      genMeta: sql`${card.genMeta} || ${JSON.stringify({ feedback: reason })}::jsonb`,
    })
    .where(eq(card.id, row.id));
  await tx.insert(rejectedCard).values({
    topicId: row.topicId,
    subtopicId: row.subtopicId,
    requestedDifficulty: tier.difficulty,
    title: row.title,
    canonicalTitle: row.canonicalTitle,
    summary: row.summary,
    body: row.body,
    stage,
    reason,
    genMeta: { card: row.id, writer: metaOf(row).writer },
  });
}

function writerOrThrow(writer: string | undefined): string {
  if (!writer) throw new ToolError("The tier has no writer to send verdicts to.");
  return writer;
}

// -- pass 1 -------------------------------------------------------------------

function correctingCards(db: Conn, tierId: string): Promise<CardRow[]> {
  return db
    .select()
    .from(card)
    .where(
      and(
        eq(card.subtopicId, tierId),
        eq(card.status, "draft"),
        sql`${card.genMeta} ->> 'stage' = 'correcting'`,
      ),
    )
    .orderBy(asc(card.createdAt));
}

export function readDraftsTool(deps: AgentDeps): HarnessTool {
  return {
    name: "read_drafts",
    label: "Read the drafts to correct",
    description: deps.prompts.render("tools/read-drafts.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "read",
    async execute(_params, context) {
      const tier = await tierOfHelper(context);
      const drafts = await withPassages(deps, tier, await correctingCards(context.db, tier.id));
      return {
        value: deps.prompts.render("tool-results/drafts.njk", {
          topic: await topicNameOf(context.db, tier.topicId),
          subtopic: tier.title,
          drafts,
        }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

const CorrectCardsParameters = Type.Object(
  {
    cards: Type.Array(
      Type.Object(
        {
          card: Id,
          title: Type.Optional(Type.String({ minLength: 1 })),
          canonical_title: Type.Optional(Type.String({ minLength: 1 })),
          summary: Type.Optional(Type.String({ minLength: 1 })),
          body: Type.Optional(Type.String({ minLength: 1 })),
          note: Type.String({
            minLength: 1,
            description: "What you changed and why, or why it stands as written",
          }),
        },
        CLOSED,
      ),
      { minItems: 1 },
    ),
  },
  CLOSED,
);

export function correctCardsTool(deps: AgentDeps): HarnessTool<typeof CorrectCardsParameters> {
  return {
    name: "correct_cards",
    label: "Correct drafts",
    description: deps.prompts.render("tools/correct-cards.njk", {}),
    parameters: CorrectCardsParameters,
    kind: "change",
    async execute(params, context) {
      const tier = await tierOfHelper(context);
      const waiting = settleOnce(
        await correctingCards(context.db, tier.id),
        params.cards.map((corrected) => corrected.card),
        "Card",
      );
      const grounding = await groundingOf(deps, tier);
      // Each correction that passes is stored, and only a faulty one is refused, so one fault never
      // has every correction written again (the owner's rule: no output paid for twice).
      const refused: string[] = [];
      const corrected: { row: CardRow; draft: Draft; note: string | undefined; rewritten: boolean }[] = [];
      for (const given of params.cards) {
        const row = waiting.get(given.card) as CardRow;
        const draft = {
          title: (given.title ?? row.title).trim(),
          canonical_title: (given.canonical_title ?? row.canonicalTitle).trim(),
          summary: (given.summary ?? row.summary).trim(),
          body: (given.body ?? row.body).trim(),
          passages: metaOf(row).passages,
        };
        const problems = draftProblems(draft, grounding.length, codeAllowedIn(tier));
        if (problems.length > 0) {
          refused.push(`card ${row.id}: ${problems.join("; ")}`);
          continue;
        }
        corrected.push({ row, draft, note: given.note, rewritten: draft.body !== row.body });
      }
      if (corrected.length === 0) {
        throw new ToolError(
          `Nothing was stored; fix every problem and call again:\n- ${refused.join("\n- ")}`,
        );
      }

      const rewritten = corrected.filter((one) => one.rewritten);
      const vectors = await deps.embedder.embedPassage(rewritten.map((one) => one.draft.body));
      const vectorOf = new Map<string, number[]>();
      rewritten.forEach((one, index) => {
        vectorOf.set(one.row.id, vectors[index] as number[]);
      });
      for (const one of corrected) {
        if (!vectorOf.has(one.row.id) && one.row.contentEmbedding) {
          vectorOf.set(one.row.id, one.row.contentEmbedding);
        }
      }

      const inCall = corrected.map((one) => one.row.id);
      const others = await context.db
        .select({ id: card.id, canonicalTitle: card.canonicalTitle, embedding: card.contentEmbedding })
        .from(card)
        .where(and(eq(card.topicId, tier.topicId), ne(card.status, "rejected")));
      const earlier: { id: string; canonicalTitle: string; vector: number[] }[] = [];
      const said: string[] = [];
      const rejected: { id: string; feedback: string }[] = [];

      await context.db.transaction(async (tx) => {
        for (const one of corrected) {
          const vector = vectorOf.get(one.row.id);
          let twin: { id: string; canonicalTitle: string } | undefined;
          if (vector) {
            twin = others.find(
              (other) =>
                !inCall.includes(other.id) &&
                other.embedding !== null &&
                cosine(vector, other.embedding) >= NEAR_DUPLICATE,
            );
            if (!twin) twin = earlier.find((other) => cosine(vector, other.vector) >= NEAR_DUPLICATE);
          }
          if (twin) {
            const reason = `It says what card ${twin.id} ("${twin.canonicalTitle}") already says.`;
            await rejectCard(tx, { ...one.row, ...titlesOf(one.draft) }, tier, "near_duplicate", reason);
            rejected.push({ id: one.row.id, feedback: reason });
            said.push(`- ${one.row.id}: rejected as a near-duplicate of ${twin.id}`);
            continue;
          }
          const meta = { stage: "corrected", correction: one.note };
          await tx
            .update(card)
            .set({
              ...titlesOf(one.draft),
              contentEmbedding: vector ?? null,
              embeddingModel: vector ? deps.embedder.modelName : null,
              archetype: classifyArchetype(one.draft.body),
              genMeta: sql`${card.genMeta} || ${JSON.stringify(meta)}::jsonb`,
            })
            .where(eq(card.id, one.row.id));
          if (vector) earlier.push({ id: one.row.id, canonicalTitle: one.draft.canonical_title, vector });
          said.push(`- ${one.row.id}: corrected`);
        }
      });

      const records = await passOn(context, tier, rejected);
      const stored = await recordsStored(context.db, deps.prompts, records);
      const left = (await correctingCards(context.db, tier.id)).length;
      let next = "Every draft is through pass 1.";
      if (left > 0) next = `${left} drafts are still waiting for you.`;
      if (refused.length > 0) {
        next += `\nNot stored, so correct only these again, each with its fault fixed:\n- ${refused.join("\n- ")}`;
      }
      return { ...stored, value: `${said.join("\n")}\n${String(stored.value)}\n${next}` };
    },
  };
}

type Draft = { title: string; canonical_title: string; summary: string; body: string; passages: number[] };

function titlesOf(draft: { title: string; canonical_title: string; summary: string; body: string }) {
  return {
    title: draft.title,
    canonicalTitle: draft.canonical_title,
    summary: draft.summary,
    body: draft.body,
  };
}

/**
 * Pass 1's rejections go to the writer at once; once nothing waits for correction, the survivors
 * go to the tadpole for pass 2.
 */
async function passOn(context: ToolContext, tier: Tier, rejected: { id: string; feedback: string }[]) {
  const writer = writerOrThrow(await writerOf(context.db, tier.id));
  const records: (GateRecord | VerdictsRecord)[] = [];
  if (rejected.length > 0) {
    records.push(
      await createRecord(context.db, VerdictsRecord, {
        kind: "verdicts",
        author: context.author,
        body: { stage: "pass1", subtopic: tier.id, writer, accepted: [], rejected },
      }),
    );
  }
  if ((await correctingCards(context.db, tier.id)).length > 0) return records;
  const survivors = await context.db
    .select({ id: card.id })
    .from(card)
    .where(
      and(
        eq(card.subtopicId, tier.id),
        eq(card.status, "draft"),
        sql`${card.genMeta} ->> 'stage' = 'corrected'`,
      ),
    );
  if (survivors.length === 0 || !context.chat.parentId) return records;
  records.push(
    await createRecord(context.db, GateRecord, {
      kind: "gate",
      author: context.author,
      body: {
        stage: "pass2",
        subtopic: tier.id,
        to: context.chat.parentId,
        writer,
        items: survivors.map((row) => row.id),
      },
    }),
  );
  return records;
}

// -- pass 2 -------------------------------------------------------------------

function myCards(db: Conn, verifier: string): Promise<CardRow[]> {
  return db
    .select()
    .from(card)
    .where(and(sql`${card.genMeta} ->> 'verifier' = ${verifier}`, eq(card.status, "draft")))
    .orderBy(asc(card.createdAt));
}

function myQuestions(db: Conn, verifier: string): Promise<QuestionRow[]> {
  return db
    .select()
    .from(question)
    .where(sql`${question.genMeta} ->> 'verifier' = ${verifier}`)
    .orderBy(asc(question.createdAt));
}

function stageOf(row: { genMeta: unknown }): string | undefined {
  return (row.genMeta as { stage?: string }).stage;
}

export function readSurvivorsTool(deps: AgentDeps): HarnessTool {
  return {
    name: "read_survivors",
    label: "Read what pass 2 checks",
    description: deps.prompts.render("tools/read-survivors.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "read",
    async execute(_params, context) {
      const tier = await tierOfHelper(context);
      const cards = (await myCards(context.db, context.chat.id)).filter(
        (row) => stageOf(row) === "verifying",
      );
      const questions = (await myQuestions(context.db, context.chat.id)).filter(
        (row) => row.status === "draft" && stageOf(row) === "gated",
      );
      const cardIds = questions.map((row) => row.cardId);
      let questionCards: { id: string; title: string; body: string }[] = [];
      if (cardIds.length > 0) {
        questionCards = await context.db
          .select({ id: card.id, title: card.canonicalTitle, body: card.body })
          .from(card)
          .where(inArray(card.id, cardIds));
      }
      return {
        value: deps.prompts.render("tool-results/survivors.njk", {
          topic: await topicNameOf(context.db, tier.topicId),
          tier,
          cards: await withPassages(deps, tier, cards),
          mcqs: questions.filter((row) => row.kind === "mcq"),
          freeText: questions.filter((row) => row.kind === "free_text"),
          questionCards,
        }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

const VerifyCardsParameters = Type.Object(
  {
    verdicts: Type.Array(
      Type.Object(
        {
          card: Id,
          reads_as: Type.Enum([...DIFFICULTIES], {
            description: "The difficulty the card reads as, by your own reading",
          }),
          accept: Type.Boolean(),
          feedback: Type.String({ minLength: 1, description: "Why, in words the writer can act on" }),
        },
        CLOSED,
      ),
      { minItems: 1 },
    ),
  },
  CLOSED,
);

export function verifyCardsTool(deps: AgentDeps): HarnessTool<typeof VerifyCardsParameters> {
  return {
    name: "verify_cards",
    label: "Verify cards",
    description: deps.prompts.render("tools/verify-cards.njk", {}),
    parameters: VerifyCardsParameters,
    kind: "change",
    async execute(params, context) {
      const tier = await tierOfHelper(context);
      const waiting = (await myCards(context.db, context.chat.id)).filter(
        (row) => stageOf(row) === "verifying",
      );
      const byId = settleOnce(
        waiting,
        params.verdicts.map((verdict) => verdict.card),
        "Card",
      );
      const said: string[] = [];
      await context.db.transaction(async (tx) => {
        for (const verdict of params.verdicts) {
          const row = byId.get(verdict.card) as CardRow;
          // The difficulty is checked here, not taken on trust: a card that reads as another tier's is rejected.
          if (verdict.reads_as !== tier.difficulty) {
            const reason = `It reads as ${verdict.reads_as}, and the tier is ${tier.difficulty}. ${verdict.feedback}`;
            await rejectCard(tx, row, tier, "verification", reason);
            said.push(`- ${row.id}: rejected, it reads as ${verdict.reads_as}`);
          } else if (!verdict.accept) {
            await rejectCard(tx, row, tier, "verification", verdict.feedback);
            said.push(`- ${row.id}: rejected`);
          } else {
            const meta = { stage: "accepted", verification: verdict.feedback };
            await tx
              .update(card)
              .set({ genMeta: sql`${card.genMeta} || ${JSON.stringify(meta)}::jsonb` })
              .where(eq(card.id, row.id));
            said.push(`- ${row.id}: accepted`);
          }
        }
      });
      const left = (await myCards(context.db, context.chat.id)).filter((row) => stageOf(row) === "verifying");
      if (left.length > 0) {
        return {
          value: `${said.join("\n")}\n${left.length} cards are still waiting for you.`,
          dataSeen: [],
          recordsWritten: [],
        };
      }
      const mine = await context.db
        .select()
        .from(card)
        .where(sql`${card.genMeta} ->> 'verifier' = ${context.chat.id}`);
      const accepted = mine
        .filter((row) => row.status === "draft" && stageOf(row) === "accepted")
        .map((row) => row.id);
      const rejected = mine
        .filter((row) => row.status === "rejected")
        .map((row) => ({
          id: row.id,
          feedback: (row.genMeta as unknown as CardMeta).feedback ?? "Rejected.",
        }));
      const verdicts = await createRecord(context.db, VerdictsRecord, {
        kind: "verdicts",
        author: context.author,
        body: {
          stage: "pass2",
          subtopic: tier.id,
          writer: writerOrThrow(await writerOf(context.db, tier.id)),
          accepted,
          rejected,
        },
      });
      const stored = await recordsStored(context.db, deps.prompts, [verdicts]);
      return {
        ...stored,
        value: `${said.join("\n")}\n${String(stored.value)}\nEvery card given you is verified.`,
      };
    },
  };
}

const SolveQuestionsParameters = Type.Object(
  {
    answers: Type.Array(
      Type.Object(
        {
          question: Id,
          choice: Type.Integer({ minimum: 0, description: "The option you answer, counting from 0" }),
          sure: Type.Boolean({ description: "False when two options could be right, or none quite is" }),
          note: Type.String({
            minLength: 1,
            description: "Your reasoning, and any doubt about the question",
          }),
        },
        CLOSED,
      ),
      { minItems: 1 },
    ),
  },
  CLOSED,
);

export function solveQuestionsTool(deps: AgentDeps): HarnessTool<typeof SolveQuestionsParameters> {
  return {
    name: "solve_questions",
    label: "Solve the MCQs",
    description: deps.prompts.render("tools/solve-questions.njk", {}),
    parameters: SolveQuestionsParameters,
    kind: "change",
    async execute(params, context) {
      const tier = await tierOfHelper(context);
      const waiting = (await myQuestions(context.db, context.chat.id)).filter(
        (row) => row.kind === "mcq" && row.status === "draft" && stageOf(row) === "gated",
      );
      const byId = settleOnce(
        waiting,
        params.answers.map((answer) => answer.question),
        "MCQ",
      );
      const said: string[] = [];
      await context.db.transaction(async (tx) => {
        for (const answer of params.answers) {
          const row = byId.get(answer.question) as QuestionRow;
          const options = row.options ?? [];
          let feedback: string | null = null;
          if (answer.choice >= options.length) {
            feedback = `Pass 2 answered option ${answer.choice}, and the question has ${options.length}.`;
          } else if (answer.choice !== row.correctIndex) {
            feedback = `Pass 2 answered "${options[answer.choice]}", and the key says "${options[row.correctIndex ?? 0]}": the question is ambiguous or its key is wrong. ${answer.note}`;
          } else if (!answer.sure) {
            feedback = `Pass 2 found the key, but doubted it: ${answer.note}`;
          }
          await settleQuestion(tx, row, feedback);
          if (feedback) said.push(`- ${row.id}: rejected`);
          else said.push(`- ${row.id}: passed`);
        }
      });
      return questionVerdictsIfDone(deps, context, tier, said);
    },
  };
}

const CheckRubricsParameters = Type.Object(
  {
    verdicts: Type.Array(
      Type.Object(
        {
          question: Id,
          pass: Type.Boolean(),
          feedback: Type.String({ minLength: 1, description: "Why, in words the writer can act on" }),
        },
        CLOSED,
      ),
      { minItems: 1 },
    ),
  },
  CLOSED,
);

export function checkRubricsTool(deps: AgentDeps): HarnessTool<typeof CheckRubricsParameters> {
  return {
    name: "check_rubrics",
    label: "Check the free-text rubrics",
    description: deps.prompts.render("tools/check-rubrics.njk", {}),
    parameters: CheckRubricsParameters,
    kind: "change",
    async execute(params, context) {
      const tier = await tierOfHelper(context);
      const waiting = (await myQuestions(context.db, context.chat.id)).filter(
        (row) => row.kind === "free_text" && row.status === "draft" && stageOf(row) === "gated",
      );
      const byId = settleOnce(
        waiting,
        params.verdicts.map((verdict) => verdict.question),
        "Free-text question",
      );
      const said: string[] = [];
      await context.db.transaction(async (tx) => {
        for (const verdict of params.verdicts) {
          const row = byId.get(verdict.question) as QuestionRow;
          let feedback: string | null = null;
          if (!verdict.pass) feedback = verdict.feedback;
          await settleQuestion(tx, row, feedback);
          if (feedback) said.push(`- ${row.id}: rejected`);
          else said.push(`- ${row.id}: passed`);
        }
      });
      return questionVerdictsIfDone(deps, context, tier, said);
    },
  };
}

/** A question passes with no feedback; with feedback, it is rejected and the feedback kept for the writer. */
async function settleQuestion(tx: Tx, row: QuestionRow, feedback: string | null): Promise<void> {
  if (feedback === null) {
    await tx
      .update(question)
      .set({ genMeta: sql`${question.genMeta} || '{"stage": "passed"}'::jsonb` })
      .where(eq(question.id, row.id));
    return;
  }
  await tx
    .update(question)
    .set({ status: "rejected", genMeta: sql`${question.genMeta} || ${JSON.stringify({ feedback })}::jsonb` })
    .where(eq(question.id, row.id));
}

/** Once every question given this verifier is settled, one verdicts record wakes the writer. */
async function questionVerdictsIfDone(
  deps: AgentDeps,
  context: ToolContext,
  tier: Tier,
  said: string[],
): Promise<ToolOutput> {
  const mine = await myQuestions(context.db, context.chat.id);
  const left = mine.filter((row) => row.status === "draft" && stageOf(row) === "gated");
  if (left.length > 0) {
    return {
      value: `${said.join("\n")}\n${left.length} questions are still waiting for you.`,
      dataSeen: [],
      recordsWritten: [],
    };
  }
  const accepted = mine.filter((row) => row.status !== "rejected").map((row) => row.id);
  const rejected = mine
    .filter((row) => row.status === "rejected")
    .map((row) => ({ id: row.id, feedback: (row.genMeta as { feedback?: string }).feedback ?? "Rejected." }));
  const verdicts = await createRecord(context.db, VerdictsRecord, {
    kind: "verdicts",
    author: context.author,
    body: {
      stage: "questions",
      subtopic: tier.id,
      writer: writerOrThrow(await writerOf(context.db, tier.id)),
      accepted,
      rejected,
    },
  });
  const stored = await recordsStored(context.db, deps.prompts, [verdicts]);
  return {
    ...stored,
    value: `${said.join("\n")}\n${String(stored.value)}\nEvery question given you is checked.`,
  };
}
