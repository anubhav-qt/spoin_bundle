import type { Embedder } from "@spoin/frog/embeddings";
import { normalizeTopicText } from "@spoin/frog/normalize";
import { TOPIC_SCOPES } from "@spoin/shared/enums";
import { and, desc, eq, inArray, ne, sql } from "drizzle-orm";
import { Type } from "typebox";
import type { Db, Tx } from "../db/client.ts";
import {
  feedPlan,
  generationJob,
  harnessRecord,
  topic,
  topicAlias,
  userTopic,
  userTopicProgress,
} from "../db/schema.ts";
import type { Prompts } from "../prompts.ts";
import { followTopic } from "../topics/service.ts";
import { slugify } from "../topics/slug.ts";
import { recordsStored } from "./outputs.ts";
import { changeRecord, createRecord, readLatestRecord, refOf } from "./records.ts";
import { withoutRequestTag } from "./requests.ts";
import { CLOSED, Id, type Intake, IntakeRecord, MergeRecord } from "./schemas.ts";
import { type HarnessTool, ToolError } from "./tools.ts";

/**
 * toad_sage's intake (harness-tools.md, task 0045): every queued name is rejected, merged into a
 * topic, or accepted as a topic of its own. A job stays pending through all of it: a reject fails
 * it, a merge deletes it with its placeholder, and an accepted topic waits in the queue with its
 * intake written until the scheduler starts its tadpole.
 */

type Conn = Db | Tx;
type Job = typeof generationJob.$inferSelect;
type Topic = typeof topic.$inferSelect;

/** A topic's intake, the latest version, or undefined before its name is taken in. */
export async function intakeOf(db: Conn, topicId: string): Promise<IntakeRecord | undefined> {
  const [first] = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(and(eq(harnessRecord.kind, "intake"), sql`${harnessRecord.body} ->> 'topic' = ${topicId}`))
    .limit(1);
  if (!first) return undefined;
  return readLatestRecord(db, IntakeRecord, "intake", first.id);
}

/**
 * The text a topic's meaning is embedded from, for `find_topics_by_meaning`: what it is about, who it is for,
 * and what its requester said they want.
 */
export function meaningText(parts: {
  subject: string;
  angle: string | null;
  description: string | null;
}): string {
  const lines = [parts.subject];
  if (parts.angle) lines.push(parts.angle);
  if (parts.description) lines.push(parts.description);
  return lines.join("\n");
}

const Angle = Type.String({
  minLength: 1,
  description:
    "Who it is for and how it is written: 'plain words for newcomers'. Leave it out when it has none",
});

/** The fields toad_sage decides at intake, and restates in full to change them. */
const IntakeFields = {
  subject: Type.String({
    minLength: 1,
    description: "What it is about, told apart from its namesakes: 'Rust, the programming language'",
  }),
  angle: Type.Optional(Angle),
  scope: Type.Enum([...TOPIC_SCOPES], {
    description:
      "survey: a broad overview of a field, untiered; topic: one subject in three tiers, beginner to advanced; one_shot: one small subject, untiered",
  }),
  category: Type.String({ minLength: 1, maxLength: 120, description: "The field it belongs to" }),
  sub_category: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
  card_count: Type.Integer({ minimum: 1, description: "How many cards the topic gets in all" }),
  brief: Type.String({
    minLength: 1,
    description: "What the topic should cover and leave out, for the chats that write it",
  }),
  builds_on: Type.Optional(
    Type.Array(Id, {
      description:
        "Topics sharing its subject, whose corpus and fetched pages its tadpole reuses before searching the web",
    }),
  ),
};

const RejectParameters = Type.Object(
  {
    job: Id,
    reason: Type.String({ minLength: 1, description: "Why, in a sentence or two its requesters read" }),
  },
  CLOSED,
);

export function rejectTopicTool(prompts: Prompts): HarnessTool<typeof RejectParameters> {
  return {
    name: "reject_topic",
    label: "Reject a queued name",
    description: prompts.render("tools/reject-topic.njk", {}),
    parameters: RejectParameters,
    kind: "change",
    async execute(params, context) {
      await context.db.transaction(async (tx) => {
        const job = await waitingJob(tx, params.job);
        await tx
          .update(generationJob)
          .set({ status: "failed", lastError: params.reason })
          .where(eq(generationJob.id, job.id));
      });
      return {
        value: prompts.render("tool-results/rejected.njk", { reason: params.reason }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

const MergeParameters = Type.Object(
  {
    job: Id,
    into: Type.String({ format: "uuid", description: "The topic the name belongs to" }),
    subject: Type.String({ minLength: 1, description: "What the requested name is about, as you read it" }),
    angle: Type.Optional(Angle),
    into_subject: Type.String({ minLength: 1, description: "What the topic it goes into is about" }),
    into_angle: Type.Optional(Angle),
    reasoning: Type.String({ minLength: 1, description: "Why the two are one topic" }),
  },
  CLOSED,
);

export function mergeTopicTool(prompts: Prompts): HarnessTool<typeof MergeParameters> {
  return {
    name: "merge_topic",
    label: "Merge a queued name into a topic",
    description: prompts.render("tools/merge-topic.njk", {}),
    parameters: MergeParameters,
    kind: "change",
    async execute(params, context) {
      const { db, author } = context;
      const merge = await db.transaction(async (tx) => {
        const job = await waitingJob(tx, params.job);
        if (params.into === job.topicId) {
          throw new ToolError("That is the name's own placeholder: merge it into another topic.");
        }
        const target = await standingTopic(tx, params.into);
        const placeholder = await topicById(tx, job.topicId);
        const aliases = await tx
          .select({ normalizedText: topicAlias.normalizedText, rawText: topicAlias.rawText })
          .from(topicAlias)
          .where(eq(topicAlias.topicId, placeholder.id));
        const requesters = await requestersOf(tx, placeholder.id);

        // The placeholder takes its job, aliases and subscriptions with it; they move as they were.
        await tx.delete(topic).where(eq(topic.id, placeholder.id));
        for (const requester of requesters) {
          await followTopic(tx, requester.userId, target, {
            displayName: requester.displayName,
            isCustom: true,
            entry: requester.entry,
            hue: requester.accentHue,
          });
        }
        if (requesters.length > 0) {
          const userIds = requesters.map((requester) => requester.userId);
          await tx.delete(feedPlan).where(inArray(feedPlan.userId, userIds));
        }
        for (const alias of aliases) {
          await tx
            .insert(topicAlias)
            .values({ ...alias, topicId: target.id, decidedBy: "toad_sage" })
            .onConflictDoNothing();
        }

        let description: string | null = null;
        if (placeholder.description) description = withoutRequestTag(placeholder.description);
        return createRecord(tx, MergeRecord, {
          kind: "merge",
          author,
          body: {
            requested: {
              name: withoutRequestTag(placeholder.canonicalName),
              description,
              subject: params.subject,
              angle: params.angle ?? null,
              priority: job.priority,
              aliases,
              requesters,
            },
            into: {
              topic: target.id,
              name: target.canonicalName,
              subject: params.into_subject,
              angle: params.into_angle ?? null,
            },
            reasoning: params.reasoning,
          },
        });
      });
      return recordsStored(db, prompts, [merge]);
    },
  };
}

const AcceptParameters = Type.Object(
  {
    job: Id,
    name: Type.String({
      minLength: 1,
      maxLength: 120,
      description: "The topic's full name, as a reader would ask for it: 'Rust in easy language'",
    }),
    ...IntakeFields,
  },
  CLOSED,
);

export function acceptTopicTool(prompts: Prompts, embedder: Embedder): HarnessTool<typeof AcceptParameters> {
  return {
    name: "accept_topic",
    label: "Accept a queued name as a topic",
    description: prompts.render("tools/accept-topic.njk", {}),
    parameters: AcceptParameters,
    kind: "change",
    async execute(params, context) {
      const { db, author } = context;
      const placeholder = await topicOfJob(db, params.job);
      const body = intakeBody(placeholder.id, params.name, params);
      // Embedded before the transaction, so the job isn't locked while the embedder runs.
      const meaning = await embedMeaning(embedder, body, placeholder.description);
      const intake = await db.transaction(async (tx) => {
        await waitingJob(tx, params.job);
        await checkBuildsOn(tx, placeholder.id, body.buildsOn);
        const slug = slugify(params.name);
        await checkNameFree(tx, placeholder.id, params.name, slug);
        await tx
          .update(topic)
          .set({ canonicalName: params.name, slug, ...topicFields(body), ...meaning })
          .where(eq(topic.id, placeholder.id));
        await tx
          .insert(topicAlias)
          .values({
            normalizedText: normalizeTopicText(params.name),
            rawText: params.name,
            topicId: placeholder.id,
            decidedBy: "toad_sage",
          })
          .onConflictDoNothing();
        return createRecord(tx, IntakeRecord, { kind: "intake", author, body });
      });
      return recordsStored(db, prompts, [intake]);
    },
  };
}

const ChangeIntakeParameters = Type.Object(
  {
    topic: Id,
    reason: Type.String({ minLength: 1, description: "What was wrong with the intake it replaces" }),
    ...IntakeFields,
  },
  CLOSED,
);

export function changeIntakeTool(
  prompts: Prompts,
  embedder: Embedder,
): HarnessTool<typeof ChangeIntakeParameters> {
  return {
    name: "change_intake",
    label: "Change a topic's intake",
    description: prompts.render("tools/change-intake.njk", {}),
    parameters: ChangeIntakeParameters,
    kind: "change",
    async execute(params, context) {
      const { db, author } = context;
      const current = await intakeOf(db, params.topic);
      if (!current) {
        throw new ToolError(
          `Topic ${params.topic} has no intake: a queued name is taken in with accept_topic.`,
        );
      }
      const job = await latestJob(db, params.topic);
      if (job?.status === "completed") {
        throw new ToolError(`Topic ${params.topic} is live, so its intake stays as it is.`);
      }
      const written = await topicById(db, params.topic);
      const body = intakeBody(params.topic, current.body.name, params);
      const meaning = await embedMeaning(embedder, body, written.description);
      const intake = await db.transaction(async (tx) => {
        await checkBuildsOn(tx, params.topic, body.buildsOn);
        const next = await changeRecord(tx, IntakeRecord, {
          from: refOf(current),
          status: "active",
          author,
          reason: params.reason,
          body,
        });
        await tx
          .update(topic)
          .set({ ...topicFields(body), ...meaning })
          .where(eq(topic.id, params.topic));
        return next;
      });
      return recordsStored(db, prompts, [intake]);
    },
  };
}

export function intakeTools(prompts: Prompts, embedder: Embedder): HarnessTool[] {
  return [
    rejectTopicTool(prompts),
    mergeTopicTool(prompts),
    acceptTopicTool(prompts, embedder),
    changeIntakeTool(prompts, embedder),
  ];
}

interface IntakeParams {
  subject: string;
  angle?: string;
  scope: Intake["scope"];
  category: string;
  sub_category?: string;
  card_count: number;
  brief: string;
  builds_on?: string[];
}

/** The intake as stored, its categories normalized as the corpus's are (ADR-0091). */
function intakeBody(topicId: string, name: string, params: IntakeParams): Intake {
  let subCategory: string | null = null;
  if (params.sub_category) subCategory = normalizeTopicText(params.sub_category);
  return {
    topic: topicId,
    name,
    subject: params.subject,
    angle: params.angle ?? null,
    scope: params.scope,
    category: normalizeTopicText(params.category),
    subCategory,
    cardCount: params.card_count,
    brief: params.brief,
    buildsOn: [...new Set(params.builds_on ?? [])],
  };
}

/** What the topic row carries of the intake, for the product. */
function topicFields(intake: Intake) {
  return { scope: intake.scope, category: intake.category, subCategory: intake.subCategory };
}

async function embedMeaning(embedder: Embedder, intake: Intake, description: string | null) {
  const [embedding] = await embedder.embedPassage([meaningText({ ...intake, description })]);
  if (!embedding) throw new Error("The embedder returned nothing for the topic's meaning.");
  return { meaningEmbedding: embedding, meaningEmbeddingModel: embedder.modelName };
}

/**
 * The job of a name waiting to be taken in, locked until the transaction ends, so the owner can't
 * cancel it halfway through.
 */
async function waitingJob(tx: Tx, jobId: string): Promise<Job> {
  const [job] = await tx
    .select()
    .from(generationJob)
    .where(and(eq(generationJob.id, jobId), eq(generationJob.kind, "generate")))
    .for("update");
  if (!job) throw new ToolError(`There is no job ${jobId} in the queue: it was cancelled or merged.`);
  if (job.status !== "pending") {
    throw new ToolError(`Job ${jobId} is ${job.status}: only a name waiting in the queue can be taken in.`);
  }
  if (await intakeOf(tx, job.topicId)) {
    throw new ToolError(
      `The name of job ${jobId} is taken in already, as topic ${job.topicId}: change its intake with change_intake.`,
    );
  }
  return job;
}

async function topicOfJob(db: Conn, jobId: string): Promise<Topic> {
  const [found] = await db
    .select({ topicId: generationJob.topicId })
    .from(generationJob)
    .where(and(eq(generationJob.id, jobId), eq(generationJob.kind, "generate")));
  if (!found) throw new ToolError(`There is no job ${jobId} in the queue: it was cancelled or merged.`);
  return topicById(db, found.topicId);
}

export async function topicById(db: Conn, topicId: string): Promise<Topic> {
  const [found] = await db.select().from(topic).where(eq(topic.id, topicId));
  if (!found) throw new ToolError(`There is no topic ${topicId}.`);
  return found;
}

export async function latestJob(db: Conn, topicId: string): Promise<Job | undefined> {
  const [job] = await db
    .select()
    .from(generationJob)
    .where(and(eq(generationJob.topicId, topicId), eq(generationJob.kind, "generate")))
    .orderBy(desc(generationJob.createdAt))
    .limit(1);
  return job;
}

/** A topic a name can merge into: any but one whose own name was rejected. */
async function standingTopic(tx: Tx, topicId: string): Promise<Topic> {
  const found = await topicById(tx, topicId);
  const job = await latestJob(tx, topicId);
  if (job?.status === "failed") {
    throw new ToolError(
      `Topic ${topicId} was rejected: merge into a topic that stands, or accept this name as its own.`,
    );
  }
  return found;
}

/** Everyone following a placeholder, with what their subscription held. */
async function requestersOf(tx: Tx, topicId: string) {
  const rows = await tx
    .select({
      userId: userTopic.userId,
      displayName: userTopic.displayName,
      accentHue: userTopic.accentHue,
      entry: userTopicProgress.currentDifficulty,
    })
    .from(userTopic)
    .leftJoin(
      userTopicProgress,
      and(eq(userTopicProgress.userId, userTopic.userId), eq(userTopicProgress.topicId, userTopic.topicId)),
    )
    .where(eq(userTopic.topicId, topicId));
  return rows.map((row) => ({
    userId: row.userId,
    displayName: row.displayName,
    accentHue: row.accentHue,
    entry: row.entry ?? "beginner",
  }));
}

async function checkBuildsOn(tx: Tx, topicId: string, buildsOn: string[]): Promise<void> {
  if (buildsOn.includes(topicId))
    throw new ToolError("A topic can't build on itself: leave it out of builds_on.");
  if (buildsOn.length === 0) return;
  const found = await tx.select({ id: topic.id }).from(topic).where(inArray(topic.id, buildsOn));
  const known = new Set(found.map((row) => row.id));
  const missing = buildsOn.filter((id) => !known.has(id));
  if (missing.length > 0)
    throw new ToolError(`builds_on names topics that don't exist: ${missing.join(", ")}.`);
}

/** The name and its slug must be this topic's own, or free: two topics never share either. */
async function checkNameFree(tx: Tx, topicId: string, name: string, slug: string): Promise<void> {
  const [slugHolder] = await tx
    .select({ id: topic.id })
    .from(topic)
    .where(and(eq(topic.slug, slug), ne(topic.id, topicId)));
  const [aliasHolder] = await tx
    .select({ id: topicAlias.topicId })
    .from(topicAlias)
    .where(and(eq(topicAlias.normalizedText, normalizeTopicText(name)), ne(topicAlias.topicId, topicId)));
  if (slugHolder) throw nameTaken(slugHolder.id);
  if (aliasHolder) throw nameTaken(aliasHolder.id);
}

function nameTaken(holder: string): ToolError {
  return new ToolError(
    `Topic ${holder} goes by that name already: merge into it with merge_topic, or give this one a name of its own.`,
  );
}
