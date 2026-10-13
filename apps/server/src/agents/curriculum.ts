import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { closestMatch } from "@spoin/frog/curriculum/close-match";
import { parseCurriculum, splitGroundingRef } from "@spoin/frog/curriculum/contract";
import { ingestCurriculum } from "@spoin/frog/curriculum/runner";
import { chunk, document } from "@spoin/frog/schema";
import { and, asc, eq, inArray, sql } from "drizzle-orm";
import { Type } from "typebox";
import { projectCurricula } from "../curriculum/projection.ts";
import type { Db, Tx } from "../db/client.ts";
import { card, harnessRecord, subtopic, type topic } from "../db/schema.ts";
import { briefOf } from "../harness/helper-reports.ts";
import { intakeOf, topicById } from "../harness/intake.ts";
import { recordsStored } from "../harness/outputs.ts";
import {
  changeRecord,
  createRecord,
  readLatestRecord,
  readRecordHistory,
  refOf,
} from "../harness/records.ts";
import {
  BriefRecord,
  CLOSED,
  type Curriculum,
  CurriculumRecord,
  CurriculumSubtopic,
  HandoverRecord,
  Id,
  ReviewRecord,
} from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError } from "../harness/tools.ts";
import { viewsOf } from "../harness/views.ts";
import type { AgentDeps } from "./context.ts";
import { startHelper } from "./helpers.ts";

/*
 * The curriculum chat and its writers (harness-tools.md, task 0045): a topic's curriculum starts
 * once its corpus is ingested and follows docs/handoff/antigravity-curriculum-authoring.md. A NIM
 * writer writes it whole, code runs the full contract on it, the curriculum chat reviews it and
 * hands it to toad_sage; on go-on, code writes the file, ingests it and projects it onto the
 * topic's subtopics.
 */

type Conn = Db | Tx;
type Topic = typeof topic.$inferSelect;

/** Each tier's grounding: enough sections to write its cards from, few enough to stay its own. */
const MIN_ANCHORS = 5;
const MAX_ANCHORS = 10;

/** The file a topic's curriculum is written to, under the curricula directory. */
export function curriculumPath(found: Topic): string {
  return `${found.slug}/curriculum.md`;
}

/**
 * The file as the contract wants it: YAML front matter and no body. Each value is written as JSON,
 * which YAML reads as it is, so a heading with a colon can't break a grounding reference.
 */
export function curriculumText(found: Topic, curriculum: Curriculum): string {
  const subtopics = curriculum.subtopics.map((unit) => {
    const tiers: Record<string, unknown> = {};
    for (const [tier, plan] of Object.entries(unit.tiers)) {
      if (!plan) continue;
      tiers[tier] = { target_cards: plan.targetCards, card_types: plan.cardTypes, grounding: plan.grounding };
    }
    return { title: unit.title, description: unit.description, prerequisites: unit.prerequisites, tiers };
  });
  const lines = [
    "---",
    `topic: ${JSON.stringify(found.canonicalName)}`,
    `description: ${JSON.stringify(curriculum.description)}`,
    `scope: ${JSON.stringify(found.scope)}`,
    `subtopics: ${JSON.stringify(subtopics)}`,
    "---",
    "",
  ];
  return lines.join("\n");
}

/**
 * Every problem with a curriculum, named at once (harness-tools.md): the contract's own checks, the
 * scope its documents share, 5 to 10 grounding anchors a tier, each an exact heading of the
 * topic's ingested corpus, and no image cards until visual_toad sources photos.
 */
export async function curriculumProblems(
  deps: AgentDeps,
  found: Topic,
  curriculum: Curriculum,
): Promise<string[]> {
  const text = curriculumText(found, curriculum);
  const { errors } = parseCurriculum(curriculumPath(found), Buffer.from(text, "utf8"));
  const problems = [...errors.problems];
  const refs: string[] = [];
  for (const unit of curriculum.subtopics) {
    for (const [tier, plan] of Object.entries(unit.tiers)) {
      if (!plan) continue;
      const where = `subtopic "${unit.title}", tier ${tier}`;
      if (plan.grounding.length < MIN_ANCHORS || plan.grounding.length > MAX_ANCHORS) {
        problems.push(
          `${where}: ${plan.grounding.length} grounding anchors; give ${MIN_ANCHORS} to ${MAX_ANCHORS}`,
        );
      }
      if ((plan.cardTypes.image ?? 0) > 0) {
        problems.push(`${where}: image cards wait until photographs are sourced; give \`image\` 0 for now`);
      }
      refs.push(...plan.grounding);
    }
  }
  problems.push(...(await groundingProblems(deps, found, refs)));
  return problems;
}

/** Each reference names a section of an ingested document of the topic's scope, by its exact heading. */
async function groundingProblems(deps: AgentDeps, found: Topic, refs: string[]): Promise<string[]> {
  const paths = [
    ...new Set(refs.map((ref) => splitGroundingRef(ref)?.[0]).filter((path) => path !== undefined)),
  ];
  if (paths.length === 0) return [];
  const rows = await deps.universe
    .select({ path: document.sourcePath, scope: document.scope, heading: chunk.heading })
    .from(document)
    .innerJoin(chunk, eq(chunk.documentId, document.id))
    .where(inArray(document.sourcePath, paths));
  const headings = new Map<string, string[]>();
  const scopes = new Map<string, string | null>();
  for (const row of rows) {
    headings.set(row.path, [...(headings.get(row.path) ?? []), row.heading ?? ""]);
    scopes.set(row.path, row.scope);
  }
  const problems: string[] = [];
  for (const path of paths) {
    const scope = scopes.get(path);
    if (scope !== undefined && scope !== found.scope) {
      problems.push(
        `${path} is a ${scope} document, and the topic is a ${found.scope}: ground it in its own kind`,
      );
    }
  }
  for (const ref of new Set(refs)) {
    const split = splitGroundingRef(ref);
    if (!split) continue;
    const [path, heading] = split;
    const known = headings.get(path);
    if (!known) {
      problems.push(`"${ref}": ${path} is not an ingested document; list_documents shows what there is`);
    } else if (!known.includes(heading)) {
      const near = closestMatch(heading, known);
      let hint = "";
      if (near) hint = `, did you mean "${near}"?`;
      problems.push(`"${ref}": ${path} has no section headed exactly "${heading}"${hint}`);
    }
  }
  return problems;
}

/** A topic's curriculum record, its latest version, if one is written. */
export async function curriculumOf(db: Conn, topicId: string) {
  const [first] = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(
      and(
        eq(harnessRecord.kind, "curriculum"),
        eq(harnessRecord.version, 1),
        sql`${harnessRecord.body} ->> 'topic' = ${topicId}`,
      ),
    )
    .limit(1);
  if (!first) return undefined;
  return readLatestRecord(db, CurriculumRecord, "curriculum", first.id);
}

/** Writes the curriculum's file, ingests it and projects it onto the topic: toad_sage's go-on. */
export async function publishCurriculum(deps: AgentDeps, curriculum: Curriculum): Promise<void> {
  const found = await topicById(deps.db, curriculum.topic);
  const problems = await curriculumProblems(deps, found, curriculum);
  if (problems.length > 0) {
    throw new ToolError(`The curriculum no longer passes its checks:\n- ${problems.join("\n- ")}`);
  }
  const path = curriculumPath(found);
  const text = curriculumText(found, curriculum);
  const parsed = parseCurriculum(path, Buffer.from(text, "utf8")).curriculum;
  if (!parsed) throw new ToolError("The curriculum could not be parsed.");
  mkdirSync(join(deps.files.curricula, found.slug), { recursive: true });
  writeFileSync(join(deps.files.curricula, path), text);
  await deps.universe.transaction((tx) => ingestCurriculum(tx, parsed));
  await projectCurricula({
    db: deps.db,
    universe: deps.universe,
    embedder: deps.embedder,
    minCardsFraction: deps.minCardsFraction,
  });
}

/** Topics past their closing report whose curriculum toad_sage hasn't said go on to: the curriculum chat's work. */
async function waitingTopics(db: Conn): Promise<{ topicId: string; since: Date }[]> {
  const rows = await db.execute<{ topic: string; since: Date }>(sql`
    SELECT h.body ->> 'topic' AS topic, min(r.written_at) AS since
    FROM harness_record r
    JOIN harness_record h ON h.kind = 'handover' AND h.version = 1 AND h.id::text = r.body -> 'handover' ->> 'id'
    WHERE r.kind = 'review' AND r.body ->> 'verdict' = 'go_on' AND h.body ->> 'kind' = 'closing_report'
      AND NOT EXISTS (
        SELECT 1 FROM harness_record r2
        JOIN harness_record h2 ON h2.kind = 'handover' AND h2.version = 1 AND h2.id::text = r2.body -> 'handover' ->> 'id'
        WHERE r2.kind = 'review' AND r2.body ->> 'verdict' = 'go_on' AND h2.body ->> 'kind' = 'curriculum'
          AND h2.body ->> 'topic' = h.body ->> 'topic'
      )
    GROUP BY h.body ->> 'topic'
    ORDER BY min(r.written_at)
  `);
  return rows.rows.map((row) => ({ topicId: row.topic, since: new Date(row.since) }));
}

export function listWaitingTool(deps: AgentDeps): HarnessTool {
  return {
    name: "list_waiting",
    label: "List the topics waiting for a curriculum",
    description: deps.prompts.render("tools/list-waiting.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "read",
    async execute(_params, context) {
      const topics = [];
      for (const waiting of await waitingTopics(context.db)) {
        const found = await topicById(context.db, waiting.topicId);
        const written = await curriculumOf(context.db, found.id);
        const writers = await context.db
          .select({ id: harnessRecord.id })
          .from(harnessRecord)
          .where(
            and(
              eq(harnessRecord.kind, "brief"),
              sql`${harnessRecord.body} ->> 'task' = 'curriculum_writer'`,
              sql`${harnessRecord.body} ->> 'topic' = ${found.id}`,
            ),
          );
        topics.push({
          id: found.id,
          name: found.canonicalName,
          scope: found.scope,
          curriculum: written ? refOf(written) : null,
          writers: writers.length,
        });
      }
      return {
        value: deps.prompts.render("tool-results/waiting.njk", { topics }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

const StartWriterParameters = Type.Object(
  {
    topic: Id,
    brief: Type.String({ minLength: 1, description: "What the curriculum should do beyond the intake" }),
  },
  CLOSED,
);

export function startCurriculumWriterTool(deps: AgentDeps): HarnessTool<typeof StartWriterParameters> {
  return {
    name: "start_writer",
    label: "Start a curriculum's writer",
    description: deps.prompts.render("tools/start-curriculum-writer.njk", {}),
    parameters: StartWriterParameters,
    kind: "change",
    async execute(params, context) {
      await topicById(context.db, params.topic);
      const { brief } = await context.db.transaction((tx) =>
        startHelper(tx, context.chat, context.author, {
          task: "curriculum_writer",
          brief: params.brief,
          topic: params.topic,
        }),
      );
      return recordsStored(context.db, deps.prompts, [brief]);
    },
  };
}

const TopicParameters = Type.Object({ topic: Id }, CLOSED);

export function readIntakeTool(deps: AgentDeps): HarnessTool<typeof TopicParameters> {
  return {
    name: "read_intake",
    label: "Read a topic's intake",
    description: deps.prompts.render("tools/read-intake.njk", {}),
    parameters: TopicParameters,
    kind: "read",
    async execute(params, context) {
      const intake = await intakeOf(context.db, params.topic);
      if (!intake) throw new ToolError(`Topic ${params.topic} has no intake.`);
      const [view] = await viewsOf(context.db, [intake]);
      return {
        value: deps.prompts.render("tool-results/record.njk", { record: view }),
        dataSeen: [refOf(intake)],
        recordsWritten: [],
      };
    },
  };
}

export function readCurriculumTool(deps: AgentDeps): HarnessTool<typeof TopicParameters> {
  return {
    name: "read_curriculum",
    label: "Read a topic's curriculum",
    description: deps.prompts.render("tools/read-curriculum.njk", {}),
    parameters: TopicParameters,
    kind: "read",
    async execute(params, context) {
      const written = await curriculumOf(context.db, params.topic);
      if (!written) {
        return { value: `Topic ${params.topic} has no curriculum yet.`, dataSeen: [], recordsWritten: [] };
      }
      const versions = await readRecordHistory(context.db, CurriculumRecord, "curriculum", written.id);
      const reviews = await reviewsOfCurriculum(context.db, written.id);
      const tiers = await context.db
        .select({
          title: subtopic.title,
          difficulty: subtopic.difficulty,
          target: subtopic.targetCards,
          live: sql<number>`count(${card.id}) filter (where ${card.status} = 'active')`.mapWith(Number),
        })
        .from(subtopic)
        .leftJoin(card, eq(card.subtopicId, subtopic.id))
        .where(eq(subtopic.topicId, params.topic))
        .groupBy(subtopic.id)
        .orderBy(asc(subtopic.position), asc(subtopic.difficulty));
      return {
        value: deps.prompts.render("tool-results/curriculum.njk", {
          latest: (await viewsOf(context.db, [written]))[0],
          versions: versions.length,
          reviews: await viewsOf(context.db, reviews),
          tiers,
        }),
        dataSeen: [refOf(written)],
        recordsWritten: [],
      };
    },
  };
}

/** toad_sage's reviews of the handovers of a curriculum, oldest first. */
async function reviewsOfCurriculum(db: Conn, curriculumId: string) {
  const rows = await db.execute<{ id: string }>(sql`
    SELECT r.id FROM harness_record r
    JOIN harness_record h ON h.kind = 'handover' AND h.version = 1 AND h.id::text = r.body -> 'handover' ->> 'id'
    WHERE r.kind = 'review' AND r.version = 1 AND h.body -> 'records' @> ${JSON.stringify([{ id: curriculumId }])}::jsonb
    ORDER BY r.seq
  `);
  const reviews = [];
  for (const row of rows.rows) reviews.push(await readLatestRecord(db, ReviewRecord, "review", row.id));
  return reviews;
}

const WriteCurriculumParameters = Type.Object(
  {
    description: Type.String({ minLength: 1, description: "What the topic teaches, for the topic row" }),
    subtopics: Type.Array(CurriculumSubtopic, { minItems: 1 }),
    reasoning: Type.String({ minLength: 1, description: "A paragraph per major decision" }),
  },
  CLOSED,
);

/** The writer's: the whole curriculum, checked at once, stored as the next version of its record. */
export function writeCurriculumTool(deps: AgentDeps): HarnessTool<typeof WriteCurriculumParameters> {
  return {
    name: "write_curriculum",
    label: "Write the curriculum",
    description: deps.prompts.render("tools/write-curriculum.njk", {}),
    parameters: WriteCurriculumParameters,
    kind: "change",
    async execute(params, context) {
      const topicId = await briefTopic(context);
      const found = await topicById(context.db, topicId);
      const body: Curriculum = { topic: topicId, ...params };
      const problems = await curriculumProblems(deps, found, body);
      if (problems.length > 0) {
        throw new ToolError(
          `Nothing was stored; fix every problem and call again:\n- ${problems.join("\n- ")}`,
        );
      }
      const existing = await curriculumOf(context.db, topicId);
      let stored: CurriculumRecord;
      if (existing) {
        stored = await changeRecord(context.db, CurriculumRecord, {
          from: refOf(existing),
          status: "active",
          author: context.author,
          reason: "Written again",
          body,
        });
      } else {
        stored = await createRecord(context.db, CurriculumRecord, {
          kind: "curriculum",
          author: context.author,
          body,
        });
      }
      return recordsStored(context.db, deps.prompts, [stored]);
    },
  };
}

async function briefTopic(context: ToolContext): Promise<string> {
  const brief = await briefOf(context.db, context.chat);
  if (!brief?.body.topic)
    throw new ToolError("Only a curriculum's writer writes it: your brief names no topic.");
  return brief.body.topic;
}

const SendBackParameters = Type.Object(
  {
    curriculum: Id,
    notes: Type.String({ minLength: 1, description: "What to change, and why" }),
  },
  CLOSED,
);

/** After the quick review: wakes the curriculum's writer with what to change. */
export function sendBackTool(deps: AgentDeps): HarnessTool<typeof SendBackParameters> {
  return {
    name: "send_back",
    label: "Send a curriculum back",
    description: deps.prompts.render("tools/send-back.njk", {}),
    parameters: SendBackParameters,
    kind: "change",
    async execute(params, context) {
      const written = await curriculumRecordById(context.db, params.curriculum);
      const author = written.author;
      if (author.kind !== "chat") throw new ToolError("That curriculum has no writer to send it back to.");
      const brief = await createRecord(context.db, BriefRecord, {
        kind: "brief",
        author: context.author,
        body: {
          helper: author.chatId,
          task: "curriculum_writer",
          brief: `Change curriculum ${written.id} (version ${written.version}): ${params.notes}`,
          topic: written.body.topic,
          path: null,
          subtopic: null,
        },
      });
      return recordsStored(context.db, deps.prompts, [brief]);
    },
  };
}

const HandOverCurriculumParameters = Type.Object(
  {
    curriculum: Id,
    reasoning: Type.String({ minLength: 1, description: "A paragraph of reasoning per major decision" }),
  },
  CLOSED,
);

/** The curriculum chat's: a checked curriculum to toad_sage. */
export function handOverCurriculumTool(deps: AgentDeps): HarnessTool<typeof HandOverCurriculumParameters> {
  return {
    name: "hand_over",
    label: "Hand a curriculum to toad_sage",
    description: deps.prompts.render("tools/hand-over-curriculum.njk", {}),
    parameters: HandOverCurriculumParameters,
    kind: "change",
    async execute(params, context) {
      const written = await curriculumRecordById(context.db, params.curriculum);
      const found = await topicById(context.db, written.body.topic);
      const problems = await curriculumProblems(deps, found, written.body);
      if (problems.length > 0) {
        throw new ToolError(`It fails its checks now; send it back:\n- ${problems.join("\n- ")}`);
      }
      const handover = await createRecord(context.db, HandoverRecord, {
        kind: "handover",
        author: context.author,
        body: {
          kind: "curriculum",
          topic: found.id,
          records: [refOf(written)],
          note: params.reasoning,
          subtopic: null,
        },
      });
      return recordsStored(context.db, deps.prompts, [handover]);
    },
  };
}

async function curriculumRecordById(db: Conn, id: string) {
  const [row] = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(and(eq(harnessRecord.kind, "curriculum"), eq(harnessRecord.id, id)))
    .limit(1);
  if (!row) throw new ToolError(`There is no curriculum ${id}.`);
  return readLatestRecord(db, CurriculumRecord, "curriculum", id);
}
