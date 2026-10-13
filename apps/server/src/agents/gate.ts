import { cosine } from "@spoin/frog/embeddings";
import { DIFFICULTIES } from "@spoin/shared/enums";
import { and, asc, eq, inArray, ne, sql } from "drizzle-orm";
import { type Static, Type } from "typebox";
import { classifyArchetype } from "../cards/archetype.ts";
import type { Db, Tx } from "../db/client.ts";
import { card, question, rejectedCard, topic } from "../db/schema.ts";
import { recordsStored } from "../harness/outputs.ts";
import { createRecord } from "../harness/records.ts";
import { type BriefRecord, CLOSED, Id, VerdictsRecord } from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError, type ToolOutput } from "../harness/tools.ts";
import type { AgentDeps } from "./context.ts";
import {
  type CardMeta,
  codeAllowedIn,
  draftProblems,
  finishTopicIfDone,
  groundingOf,
  isTierless,
  metaOf,
  NEAR_DUPLICATE,
  putCardsLiveIfDone,
  quizLive,
  startVerifier,
  type Tier,
  tierOfHelper,
  writerOf,
} from "./tiers.ts";

/*
 * The gate's two passes (harness-tools.md, task 0045). Pass 1, one corrector per tier, rewrites
 * each draft or leaves it be and never rejects; NIM writes each draft's first correction, and the
 * corrector fixes what code refused of it. Code rejects a near-duplicate. Code starts a
 * pass-2 verifier on its survivors. Pass 2 rates each card's difficulty itself and accepts or
 * rejects it, solves each MCQ without its key, and judges each free-text rubric; a question it
 * passes is live at once. Pass 1's rejections and pass 2's verdicts wake the writer, and pass 2's
 * accepted cards wake designer_toad.
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

/**
 * The entries a call settles: each names one row waiting for this chat, once. An entry naming
 * another row, or a row already named, is refused alone, so one wrong id never has every other
 * entry written again (the owner's rule: no output paid for twice). A call with nothing to settle
 * is refused whole.
 */
export function settleOnce<Row extends { id: string }, Entry>(
  waiting: Row[],
  entries: Entry[],
  idOf: (entry: Entry) => string,
  what: string,
): { settled: { entry: Entry; row: Row }[]; refused: string[] } {
  const byId = new Map(waiting.map((row) => [row.id, row]));
  const settled: { entry: Entry; row: Row }[] = [];
  const refused: string[] = [];
  const seen = new Set<string>();
  for (const entry of entries) {
    const id = idOf(entry);
    const row = byId.get(id);
    if (!row) {
      refused.push(`${what} ${id} isn't one waiting for you`);
    } else if (seen.has(id)) {
      refused.push(`${what} ${id} is named twice; only its first entry counts`);
    } else {
      settled.push({ entry, row });
    }
    seen.add(id);
  }
  if (settled.length === 0) throw new ToolError(`Nothing was stored:\n- ${refused.join("\n- ")}`);
  return { settled, refused };
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
      const named = settleOnce(
        await correctingCards(context.db, tier.id),
        params.cards,
        (given) => given.card,
        "Card",
      );
      const grounding = await groundingOf(deps, tier);
      const codeAllowed = await codeAllowedIn(context.db, tier);
      // Each correction that passes is stored, and only a faulty one is refused, so one fault never
      // has every correction written again (the owner's rule: no output paid for twice).
      const refused: string[] = [...named.refused];
      const corrected: { row: CardRow; draft: Draft; note: string | undefined; rewritten: boolean }[] = [];
      for (const { entry: given, row } of named.settled) {
        const draft = {
          title: (given.title ?? row.title).trim(),
          canonical_title: (given.canonical_title ?? row.canonicalTitle).trim(),
          summary: (given.summary ?? row.summary).trim(),
          body: (given.body ?? row.body).trim(),
          passages: metaOf(row).passages,
        };
        const problems = draftProblems(draft, grounding.length, codeAllowed);
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
        next += `\nNot stored, so send only these again, each with its fault fixed:\n- ${refused.join("\n- ")}`;
      }
      return { ...stored, value: `${said.join("\n")}\n${String(stored.value)}\n${next}` };
    },
  };
}

/**
 * correct_cards as NIM writes it, through the corrector's write_on_nim. It marks the waiting cards
 * NIM names before storing them, so once NIM has written a card's first correction, stored or
 * refused, the corrector's own correct_cards may fix it (the owner's rule).
 */
export function correctCardsOnNimTool(deps: AgentDeps): HarnessTool<typeof CorrectCardsParameters> {
  const tool = correctCardsTool(deps);
  return {
    ...tool,
    async execute(params, context) {
      const tier = await tierOfHelper(context);
      const named = params.cards.map((one) => one.card);
      await context.db
        .update(card)
        .set({ genMeta: sql`${card.genMeta} || ${JSON.stringify({ nimTried: true })}::jsonb` })
        .where(
          and(
            inArray(card.id, named),
            eq(card.subtopicId, tier.id),
            eq(card.status, "draft"),
            sql`${card.genMeta} ->> 'stage' = 'correcting'`,
          ),
        );
      return tool.execute(params, context);
    },
  };
}

/** Whether NIM has written the first correction of every card the call names. */
export async function correctedOnNim(
  context: ToolContext,
  params: Static<typeof CorrectCardsParameters>,
): Promise<boolean> {
  const named = params.cards.map((one) => one.card);
  const untried = await context.db
    .select({ id: card.id })
    .from(card)
    .where(and(inArray(card.id, named), sql`${card.genMeta} ->> 'nimTried' is distinct from 'true'`));
  return untried.length === 0;
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
 * Pass 1's rejections go to the writer at once; once nothing waits for correction, code starts a
 * pass-2 verifier on the survivors.
 */
async function passOn(context: ToolContext, tier: Tier, rejected: { id: string; feedback: string }[]) {
  const writer = writerOrThrow(await writerOf(context.db, tier.id));
  const records: (BriefRecord | VerdictsRecord)[] = [];
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
  if (survivors.length === 0) return records;
  const cards = survivors.map((row) => row.id);
  records.push(await context.db.transaction((tx) => startVerifier(tx, tier, { cards, questions: [] })));
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
      const named = settleOnce(waiting, params.verdicts, (verdict) => verdict.card, "Card");
      const said = named.refused.map((problem) => `- not stored: ${problem}`);
      const tierless = await isTierless(context.db, tier.topicId);
      await context.db.transaction(async (tx) => {
        for (const { entry: verdict, row } of named.settled) {
          // The difficulty is checked here, not taken on trust: a card that reads as another tier's
          // is rejected. A tierless topic's cards run easy to advanced, so each takes the one read.
          if (tierless) {
            await tx.update(card).set({ difficulty: verdict.reads_as }).where(eq(card.id, row.id));
          }
          if (!tierless && verdict.reads_as !== tier.difficulty) {
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
      // Cards that asked for no art wait for nothing: the tier may go live on these verdicts.
      const wentLive = await context.db.transaction((tx) => putCardsLiveIfDone(tx, tier));
      const stored = await recordsStored(context.db, deps.prompts, [verdicts]);
      let value = `${said.join("\n")}\n${String(stored.value)}\nEvery card given you is verified.`;
      if (wentLive) value += " The tier's cards are live.";
      return { ...stored, value };
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
      const named = settleOnce(waiting, params.answers, (answer) => answer.question, "MCQ");
      const said = named.refused.map((problem) => `- not stored: ${problem}`);
      await context.db.transaction(async (tx) => {
        for (const { entry: answer, row } of named.settled) {
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
      const named = settleOnce(waiting, params.verdicts, (verdict) => verdict.question, "Free-text question");
      const said = named.refused.map((problem) => `- not stored: ${problem}`);
      await context.db.transaction(async (tx) => {
        for (const { entry: verdict, row } of named.settled) {
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

/**
 * A question passes with no feedback and goes live, since its card already is; with feedback, it
 * is rejected and the feedback kept for the writer.
 */
async function settleQuestion(tx: Tx, row: QuestionRow, feedback: string | null): Promise<void> {
  if (feedback === null) {
    await tx
      .update(question)
      .set({ status: "active", genMeta: sql`${question.genMeta} || '{"stage": "passed"}'::jsonb` })
      .where(eq(question.id, row.id));
    return;
  }
  await tx
    .update(question)
    .set({ status: "rejected", genMeta: sql`${question.genMeta} || ${JSON.stringify({ feedback })}::jsonb` })
    .where(eq(question.id, row.id));
}

/**
 * Once every question given this verifier is settled: if the tier's quiz is complete, the topic's
 * job completes when it was the last, and the writer, with nothing left to do, isn't woken;
 * otherwise one verdicts record wakes it to write what is missing.
 */
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
  if (await quizLive(context.db, tier)) {
    await context.db.transaction((tx) => finishTopicIfDone(tx, tier.topicId));
    return {
      value: `${said.join("\n")}\nEvery question given you is checked, and the tier's quiz is complete.`,
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
