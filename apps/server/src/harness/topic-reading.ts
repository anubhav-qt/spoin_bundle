import type { Embedder } from "@spoin/frog/embeddings";
import { normalizeTopicText } from "@spoin/frog/normalize";
import type { Difficulty } from "@spoin/shared/enums";
import { and, asc, cosineDistance, desc, eq, isNotNull, ne, sql } from "drizzle-orm";
import { Type } from "typebox";
import type { Db } from "../db/client.ts";
import { card, generationJob, subtopic, topic, topicAlias, topicEdge, userTopic } from "../db/schema.ts";
import type { Prompts } from "../prompts.ts";
import { intakeOf, latestJob, meaningText, topicById } from "./intake.ts";
import { refOf } from "./records.ts";
import { CLOSED, Id, type Intake, type RecordRef } from "./schemas.ts";
import type { HarnessTool } from "./tools.ts";
import { withoutRequestTag } from "./untrusted.ts";
import { type RecordView, viewsOf } from "./views.ts";

/**
 * toad_sage's look at the topics (harness-tools.md, task 0045). Before it takes a name in, it finds
 * the topics near it by name or by meaning, a tool each, so the embedder runs only when it asks for
 * a meaning match. A rejected topic is never found: a name merges only into one that stands.
 */

/** How many topics each search hands back: ADR-0025's candidate count. */
const MATCHES = 5;

/** Where a topic is, from its newest generate job and whether its name has been taken in. */
type Standing = "waiting" | "accepted" | "writing" | "live" | "rejected";

interface TopicView {
  id: string;
  standing: Standing;
  job: string;
  intake: Intake | null;
  /** What readers typed: the names it was asked for under, and its requester's description. */
  aliases: string[];
  description: string | null;
}

interface Match {
  topicId: string;
  score: number;
}

const FindByNameParameters = Type.Object(
  { name: Type.String({ minLength: 1, description: "The name to look for, as it was asked for" }) },
  CLOSED,
);

export function findTopicsByNameTool(prompts: Prompts): HarnessTool<typeof FindByNameParameters> {
  return {
    name: "find_topics_by_name",
    label: "Find topics by name",
    description: prompts.render("tools/find-topics-by-name.njk", {}),
    parameters: FindByNameParameters,
    kind: "read",
    async execute(params, context) {
      const { db } = context;
      const latest = latestJobs(db);
      const score = sql<number>`max(similarity(${topicAlias.normalizedText}, ${normalizeTopicText(params.name)}))`;
      const matches = await db
        .select({ topicId: topicAlias.topicId, score })
        .from(topicAlias)
        .innerJoin(latest, eq(latest.topicId, topicAlias.topicId))
        .where(ne(latest.status, "failed"))
        .groupBy(topicAlias.topicId)
        .orderBy(desc(score))
        .limit(MATCHES);
      return found(db, prompts, "name", matches);
    },
  };
}

const FindByMeaningParameters = Type.Object(
  {
    subject: Type.String({
      minLength: 1,
      description: "What the name is about, as you read it: 'Rust, the programming language'",
    }),
    angle: Type.Optional(
      Type.String({ minLength: 1, description: "Who it is for and how it is written, if it has one" }),
    ),
  },
  CLOSED,
);

export function findTopicsByMeaningTool(
  prompts: Prompts,
  embedder: Embedder,
): HarnessTool<typeof FindByMeaningParameters> {
  return {
    name: "find_topics_by_meaning",
    label: "Find topics by meaning",
    description: prompts.render("tools/find-topics-by-meaning.njk", {}),
    parameters: FindByMeaningParameters,
    kind: "read",
    async execute(params, context) {
      const { db } = context;
      // Stated as a topic's meaning is stored, so like is compared with like.
      const text = meaningText({ subject: params.subject, angle: params.angle ?? null, description: null });
      const [vector] = await embedder.embedPassage([text]);
      if (!vector) throw new Error("The embedder returned nothing for the meaning.");
      const latest = latestJobs(db);
      const distance = cosineDistance(topic.meaningEmbedding, vector);
      const matches = await db
        .select({ topicId: topic.id, score: sql<number>`1 - (${distance})` })
        .from(topic)
        .innerJoin(latest, eq(latest.topicId, topic.id))
        // A vector from another model is in another space: comparing them means nothing.
        .where(and(ne(latest.status, "failed"), eq(topic.meaningEmbeddingModel, embedder.modelName)))
        .orderBy(distance)
        .limit(MATCHES);
      return found(db, prompts, "meaning", matches);
    },
  };
}

const ReadTopicParameters = Type.Object({ topic: Id }, CLOSED);

export function readTopicTool(prompts: Prompts): HarnessTool<typeof ReadTopicParameters> {
  return {
    name: "read_topic",
    label: "Read a topic",
    description: prompts.render("tools/read-topic.njk", {}),
    parameters: ReadTopicParameters,
    kind: "read",
    async execute(params, context) {
      const { db } = context;
      const view = await topicView(db, params.topic);
      const intake = await intakeOf(db, params.topic);
      let intakeView: RecordView | undefined;
      const dataSeen: RecordRef[] = [];
      if (intake) {
        [intakeView] = await viewsOf(db, [intake]);
        dataSeen.push(refOf(intake));
      }
      const value = prompts.render("tool-results/topic.njk", {
        topic: view,
        intake: intakeView ?? null,
        readers: await readersOf(db, params.topic),
        links: await linksOf(db, params.topic),
        tiers: await tiersOf(db, params.topic),
      });
      return { value, dataSeen, recordsWritten: [] };
    },
  };
}

const ListCategoriesParameters = Type.Object({}, CLOSED);

export function listCategoriesTool(prompts: Prompts): HarnessTool<typeof ListCategoriesParameters> {
  return {
    name: "list_categories",
    label: "List the categories",
    description: prompts.render("tools/list-categories.njk", {}),
    parameters: ListCategoriesParameters,
    kind: "read",
    async execute(_params, context) {
      const rows = await context.db
        .select({
          category: topic.category,
          subCategory: topic.subCategory,
          topics: sql<number>`count(*)::int`,
        })
        .from(topic)
        .where(isNotNull(topic.category))
        .groupBy(topic.category, topic.subCategory)
        .orderBy(asc(topic.category), asc(topic.subCategory));
      const categories: {
        name: string;
        topics: number;
        subCategories: { name: string; topics: number }[];
      }[] = [];
      for (const row of rows) {
        if (!row.category) continue;
        let category = categories.at(-1);
        if (category?.name !== row.category) {
          category = { name: row.category, topics: 0, subCategories: [] };
          categories.push(category);
        }
        category.topics += row.topics;
        if (row.subCategory) category.subCategories.push({ name: row.subCategory, topics: row.topics });
      }
      return {
        value: prompts.render("tool-results/categories.njk", { categories }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

export function topicReadingTools(prompts: Prompts, embedder: Embedder): HarnessTool[] {
  return [
    findTopicsByNameTool(prompts),
    findTopicsByMeaningTool(prompts, embedder),
    readTopicTool(prompts),
    listCategoriesTool(prompts),
  ];
}

/** Each topic's newest generate job, for a query to join: a repair job is not where a topic stands. */
function latestJobs(db: Db) {
  return db
    .selectDistinctOn([generationJob.topicId], {
      topicId: generationJob.topicId,
      status: generationJob.status,
    })
    .from(generationJob)
    .where(eq(generationJob.kind, "generate"))
    .orderBy(generationJob.topicId, desc(generationJob.createdAt))
    .as("latest_job");
}

async function found(db: Db, prompts: Prompts, by: "name" | "meaning", matches: Match[]) {
  const views = [];
  for (const match of matches) {
    views.push({ topic: await topicView(db, match.topicId), score: match.score });
  }
  return {
    value: prompts.render("tool-results/topics-found.njk", { by, matches: views }),
    dataSeen: [],
    recordsWritten: [],
  };
}

async function topicView(db: Db, topicId: string): Promise<TopicView> {
  const row = await topicById(db, topicId);
  const job = await latestJob(db, topicId);
  if (!job) throw new Error(`Topic ${topicId} has no generate job.`);
  const intake = await intakeOf(db, topicId);
  const aliases = await db
    .select({ rawText: topicAlias.rawText })
    .from(topicAlias)
    .where(eq(topicAlias.topicId, topicId))
    .orderBy(asc(topicAlias.createdAt));
  let description: string | null = null;
  if (row.description) description = withoutRequestTag(row.description);
  let body: Intake | null = null;
  if (intake) body = intake.body;
  return {
    id: topicId,
    standing: standingOf(job.status, body !== null),
    job: job.id,
    intake: body,
    aliases: aliases.map((alias) => withoutRequestTag(alias.rawText)),
    description,
  };
}

function standingOf(status: typeof generationJob.$inferSelect.status, takenIn: boolean): Standing {
  if (status === "completed") return "live";
  if (status === "failed") return "rejected";
  if (status === "running") return "writing";
  if (takenIn) return "accepted";
  return "waiting";
}

/** The readers who asked for it, under its own name or one merged into it. */
async function readersOf(db: Db, topicId: string): Promise<number> {
  const [row] = await db
    .select({ n: sql<number>`count(*)::int` })
    .from(userTopic)
    .where(and(eq(userTopic.topicId, topicId), eq(userTopic.isCustom, true)));
  return row?.n ?? 0;
}

/** Its edges both ways, each with the topic at the other end. */
async function linksOf(db: Db, topicId: string) {
  const outgoing = await db
    .select({ kind: topicEdge.kind, topic: topic.id, name: topic.canonicalName })
    .from(topicEdge)
    .innerJoin(topic, eq(topic.id, topicEdge.toTopicId))
    .where(eq(topicEdge.fromTopicId, topicId))
    .orderBy(asc(topicEdge.createdAt));
  const incoming = await db
    .select({ kind: topicEdge.kind, topic: topic.id, name: topic.canonicalName })
    .from(topicEdge)
    .innerJoin(topic, eq(topic.id, topicEdge.fromTopicId))
    .where(eq(topicEdge.toTopicId, topicId))
    .orderBy(asc(topicEdge.createdAt));
  return [
    ...outgoing.map((edge) => ({ ...edge, direction: "to" })),
    ...incoming.map((edge) => ({ ...edge, direction: "from" })),
  ];
}

/** Its subtopics tier by tier, each with the cards it has live. */
async function tiersOf(db: Db, topicId: string) {
  const subtopics = await db
    .select({
      id: subtopic.id,
      title: subtopic.title,
      difficulty: subtopic.difficulty,
      target: subtopic.targetCards,
    })
    .from(subtopic)
    .where(eq(subtopic.topicId, topicId))
    .orderBy(asc(subtopic.difficulty), asc(subtopic.position));
  const counted = await db
    .select({ subtopicId: card.subtopicId, cards: sql<number>`count(*)::int` })
    .from(card)
    .where(and(eq(card.topicId, topicId), eq(card.status, "active")))
    .groupBy(card.subtopicId);
  const live = new Map(counted.map((row) => [row.subtopicId, row.cards]));

  const tiers: {
    difficulty: Difficulty;
    cards: number;
    subtopics: { title: string; target: number; cards: number }[];
  }[] = [];
  for (const row of subtopics) {
    let tier = tiers.at(-1);
    if (tier?.difficulty !== row.difficulty) {
      tier = { difficulty: row.difficulty, cards: 0, subtopics: [] };
      tiers.push(tier);
    }
    const cards = live.get(row.id) ?? 0;
    tier.cards += cards;
    tier.subtopics.push({ title: row.title, target: row.target, cards });
  }
  return tiers;
}
