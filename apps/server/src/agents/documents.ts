import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { type ParsedDocument, parseDocument } from "@spoin/frog/ingest/contract";
import { ingestDocument } from "@spoin/frog/ingest/runner";
import type { Tool } from "@spoin/pi-ai";
import { and, desc, eq, sql } from "drizzle-orm";
import { type Static, Type } from "typebox";
import type { Db, Tx } from "../db/client.ts";
import { harnessRecord, type topic } from "../db/schema.ts";
import { briefOf } from "../harness/helper-reports.ts";
import { intakeOf, topicById } from "../harness/intake.ts";
import { recordsStored } from "../harness/outputs.ts";
import { changeRecord, createRecord, readLatestRecord, refOf } from "../harness/records.ts";
import {
  AUDITORS,
  AuditRecord,
  CLAIM_TYPES,
  CLOSED,
  COMPETENCY_STAGES,
  CoverageMark,
  DraftRecord,
  FindingRecord,
  Id,
  SOURCE_TIERS,
  Text,
} from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError } from "../harness/tools.ts";
import type { AgentDeps } from "./context.ts";
import { corpusFile, corpusPaths, topicDir } from "./corpus.ts";
import { startHelper } from "./helpers.ts";
import { mapFindingRefusal } from "./maps.ts";

/*
 * A topic's corpus documents (harness-tools.md, task 0045): written one per writer helper on NIM,
 * checked against the corpus contract at write time, audited by three fixed calls that never see
 * the author's reasoning, and ingested only once toad_sage says go on to the closing report.
 */

type Conn = Db | Tx;
type Topic = typeof topic.$inferSelect;

/** A document's file name in its topic's directory. */
const FILE_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*\.md$/;

/**
 * How many cards one section grounds, at most. A tier of 5 to 25 cards is written from 5 to 10
 * sections of its own; the first Rust run's tadpole was only told so, and wrote 56 sections for
 * 700 cards (task 0045).
 */
export const CARDS_PER_SECTION = 3;

/** A document's sections: NIM writes it whole in one call, and 30 of them is some 13k tokens, as much as it gave in one. */
const MIN_DOCUMENT_SECTIONS = 3;
const MAX_DOCUMENT_SECTIONS = 30;

/** The sections a topic's documents must hold between them before its closing report goes. */
export function sectionsNeeded(cardCount: number): number {
  return Math.ceil(cardCount / CARDS_PER_SECTION);
}

/** Every subject has one (antigravity-corpus-authoring.md): field tips, pitfalls and lessons learned. */
export const TIPS_AND_TRICKS = "tips-and-tricks.md";

/** The topic a chat works on: its own, or its main chat's for a helper. */
async function topicOfChat(context: ToolContext): Promise<Topic> {
  let topicId = context.chat.topicId;
  if (!topicId) {
    const brief = await briefOf(context.db, context.chat);
    topicId = brief?.body.topic ?? null;
  }
  if (!topicId) throw new ToolError("You work on no topic, so you have no documents.");
  return topicById(context.db, topicId);
}

const StartWriterParameters = Type.Object(
  {
    file: Type.String({
      pattern: FILE_NAME.source,
      description: "The document's file name in your topic's directory, kebab-case, ending .md",
    }),
    brief: Type.String({
      minLength: 1,
      description: "What the document covers, from which maps and passages, and what it leaves to others",
    }),
    sections: Type.Integer({
      minimum: MIN_DOCUMENT_SECTIONS,
      maximum: MAX_DOCUMENT_SECTIONS,
      description: "How many sections the document has, whole: write_document refuses it with fewer",
    }),
  },
  CLOSED,
);

/** A writer helper on NIM for one of the topic's documents. */
export function startDocumentWriterTool(deps: AgentDeps): HarnessTool<typeof StartWriterParameters> {
  return {
    name: "start_writer",
    label: "Start a document's writer",
    description: deps.prompts.render("tools/start-document-writer.njk", {}),
    parameters: StartWriterParameters,
    kind: "change",
    async execute(params, context) {
      const found = await topicOfChat(context);
      const path = `${topicDir(found)}/${params.file}`;
      const { brief } = await context.db.transaction((tx) =>
        startHelper(tx, context.chat, context.author, {
          task: "document_writer",
          brief: params.brief,
          topic: found.id,
          path,
          sections: params.sections,
        }),
      );
      return recordsStored(context.db, deps.prompts, [brief]);
    },
  };
}

const Section = Type.Object(
  {
    heading: Type.String({ minLength: 1, description: "Descriptive: it goes into the chunk's header" }),
    text: Type.String({
      minLength: 1,
      description: "Self-contained, 1,000 to 2,000 characters, never over 2,200",
    }),
  },
  CLOSED,
);

const WriteDocumentParameters = Type.Object(
  {
    title: Text,
    source: Type.String({ minLength: 1, description: "The URL or the origin the document is curated from" }),
    source_date: Type.String({
      pattern: "^\\d{4}(-\\d{2}(-\\d{2})?)?$",
      description: "When the source material is from: YYYY-MM-DD, YYYY-MM or YYYY",
    }),
    tags: Type.Array(Type.String({ minLength: 1 }), {
      minItems: 1,
      description: "What the document is about",
    }),
    knowledge_kind: Type.Enum([...CLAIM_TYPES], { description: "The document's dominant claim class" }),
    source_tier: Type.Enum([...SOURCE_TIERS]),
    applies_to: Type.Optional(
      Type.Record(Type.String({ minLength: 1 }), Type.String({ minLength: 1 }), {
        description: 'What it is true of, such as {"framework": "langgraph", "version": "1.x"}',
      }),
    ),
    verified_on: Type.Optional(
      Type.String({ format: "date", description: "When you checked it against what it describes" }),
    ),
    status: Type.Optional(Type.Enum(["current", "historical", "deprecated"])),
    sections: Type.Array(Section, {
      description:
        "A new document whole the first time; after that, and for one already written, only the sections that change",
    }),
    drop: Type.Optional(
      Type.Array(Type.String({ minLength: 1 }), { description: "Headings of sections to take out" }),
    ),
  },
  CLOSED,
);

type DocumentTry = Omit<Static<typeof WriteDocumentParameters>, "drop">;

/** The writer's: its document, checked against the contract, written to disk and kept as a record. */
export function writeDocumentTool(deps: AgentDeps): HarnessTool<typeof WriteDocumentParameters> {
  return {
    name: "write_document",
    label: "Write the document",
    description: deps.prompts.render("tools/write-document.njk", {}),
    parameters: WriteDocumentParameters,
    kind: "change",
    async execute(params, context) {
      const brief = await briefOf(context.db, context.chat);
      if (!brief?.body.path || !brief.body.topic) {
        throw new ToolError("Only a document's writer writes it: you have no document in your brief.");
      }
      const path = brief.body.path;
      const found = await topicById(context.db, brief.body.topic);
      const full = corpusFile(deps, path);
      // Every try is kept as it was written, passing or not, and the next call changes only the
      // sections it names: a document refused for one section is never written again whole (the
      // owner's rule: no output paid for twice).
      const tryFile = `${full}.try.json`;
      const merged = mergeTry(lastTry(tryFile, full, path), params);
      mkdirSync(dirname(full), { recursive: true });
      writeFileSync(tryFile, JSON.stringify(merged));
      const text = documentText(found, merged);
      const problems = epistemicProblems(merged);
      problems.push(...parseDocument(path, Buffer.from(text, "utf8")).errors.problems);
      const asked = brief.body.sections;
      if (asked !== undefined && merged.sections.length < asked) {
        const missing = asked - merged.sections.length;
        problems.push(
          `your brief asks for ${asked} sections and the document has ${merged.sections.length}: add ${missing}, each on an idea of its own`,
        );
      }
      const headings = merged.sections.map((section) => `- ${section.heading.trim()}`).join("\n");
      if (problems.length > 0) {
        throw new ToolError(
          `Not written yet, but your try is kept: call write_document again with only the sections that change.\n` +
            `Problems:\n- ${problems.join("\n- ")}\nThe sections as kept:\n${headings}`,
        );
      }
      writeFileSync(full, text);
      const draft = await keepDraft(context.db, context, { topic: found.id, path, text });
      const stored = await recordsStored(context.db, deps.prompts, [draft]);
      return { ...stored, value: `${String(stored.value)}\nIts sections:\n${headings}` };
    },
  };
}

type Sections = Pick<DocumentTry, "sections">;

/**
 * The sections a call is laid over: the last try, or the document as written when it has none (it
 * was written before tries were kept), so a writer changing a written document sends only what
 * changes and never loses the rest.
 */
export function lastTry(tryFile: string, full: string, path: string): Sections | null {
  if (existsSync(tryFile)) return JSON.parse(readFileSync(tryFile, "utf8")) as DocumentTry;
  if (!existsSync(full)) return null;
  const { document } = parseDocument(path, readFileSync(full));
  if (!document) return null;
  return { sections: document.sections };
}

/**
 * The last try with this call laid over it: its fields replace the try's, a section replaces the
 * one of the same heading where it stood, a new heading goes at the end, and `drop` takes one out.
 */
export function mergeTry(last: Sections | null, params: Static<typeof WriteDocumentParameters>): DocumentTry {
  const { drop, sections, ...fields } = params;
  const merged = new Map<string, Static<typeof Section>>();
  for (const section of last?.sections ?? []) merged.set(section.heading.trim(), section);
  for (const heading of drop ?? []) merged.delete(heading.trim());
  for (const section of sections) merged.set(section.heading.trim(), section);
  return { ...fields, sections: [...merged.values()] };
}

/** The checks the contract leaves to the epistemic fields (antigravity-corpus-authoring.md). */
function epistemicProblems(params: { knowledge_kind: string; applies_to?: object; verified_on?: string }) {
  const problems: string[] = [];
  if (params.knowledge_kind === "implementation" && !params.applies_to) {
    problems.push("`applies_to` is required when `knowledge_kind` is implementation: say what it is true of");
  }
  if (params.applies_to && !params.verified_on) {
    problems.push("`verified_on` is required with `applies_to`: when you last checked it against the thing");
  }
  return problems;
}

/**
 * The file as the contract wants it. Front matter is YAML; each value is written as JSON, which
 * YAML reads as it is, so a title with a colon can't break it. Kind, category, sub category and
 * scope come from the topic row, not the writer.
 */
function documentText(found: Topic, params: Static<typeof WriteDocumentParameters>): string {
  const front: Record<string, unknown> = {
    title: params.title,
    kind: "topic_source",
    category: found.category ?? "uncategorized",
  };
  if (found.subCategory) front.sub_category = found.subCategory;
  front.scope = found.scope;
  front.source = params.source;
  front.source_date = params.source_date;
  front.topic_tags = params.tags;
  front.knowledge_kind = params.knowledge_kind;
  front.source_tier = params.source_tier;
  if (params.applies_to) front.applies_to = params.applies_to;
  if (params.verified_on) front.verified_on = params.verified_on;
  if (params.status) front.status = params.status;
  const lines = ["---"];
  for (const [key, value] of Object.entries(front)) lines.push(`${key}: ${JSON.stringify(value)}`);
  lines.push("---", "");
  for (const section of params.sections) {
    lines.push(`## ${section.heading.trim()}`, "", section.text.trim(), "");
  }
  return lines.join("\n");
}

/** The draft record of a path: its next version, or its first. */
async function keepDraft(
  db: Conn,
  context: ToolContext,
  body: { topic: string; path: string; text: string },
): Promise<DraftRecord> {
  const existing = await draftOf(db, body.path);
  if (!existing) return createRecord(db, DraftRecord, { kind: "draft", author: context.author, body });
  return changeRecord(db, DraftRecord, {
    from: refOf(existing),
    status: "active",
    author: context.author,
    reason: "Written again",
    body,
  });
}

async function draftOf(db: Conn, path: string): Promise<DraftRecord | undefined> {
  const [first] = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(
      and(
        eq(harnessRecord.kind, "draft"),
        eq(harnessRecord.version, 1),
        sql`${harnessRecord.body} ->> 'path' = ${path}`,
      ),
    )
    .limit(1);
  if (!first) return undefined;
  return readLatestRecord(db, DraftRecord, "draft", first.id);
}

/** The latest version of each of a topic's drafts. */
export async function draftsOf(db: Conn, topicId: string): Promise<DraftRecord[]> {
  const firsts = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(
      and(
        eq(harnessRecord.kind, "draft"),
        eq(harnessRecord.version, 1),
        sql`${harnessRecord.body} ->> 'topic' = ${topicId}`,
      ),
    )
    .orderBy(harnessRecord.seq);
  const drafts: DraftRecord[] = [];
  for (const first of firsts) drafts.push(await readLatestRecord(db, DraftRecord, "draft", first.id));
  return drafts;
}

const FoundProblems = Type.Object({
  findings: Type.Array(
    Type.Object({
      path: Type.Union([Type.String({ minLength: 1 }), Type.Null()], {
        description: "The document, or null for the drafts as a whole",
      }),
      problem: Type.String({ minLength: 1, description: "What is wrong, quoting the words at fault" }),
      fix: Type.String({ minLength: 1, description: "What the document should say instead" }),
    }),
  ),
});

const CoverageAnswer = Type.Object({
  matrix: Type.Array(CoverageMark, { minItems: COMPETENCY_STAGES.length }),
  findings: FoundProblems.properties.findings,
});

/** The three auditors, each one fixed call that the tadpole doesn't brief. */
export function auditDraftsTool(deps: AgentDeps): HarnessTool {
  const parameters = Type.Object({}, CLOSED);
  return {
    name: "audit_drafts",
    label: "Audit the drafts",
    description: deps.prompts.render("tools/audit-drafts.njk", {}),
    parameters,
    kind: "change",
    async execute(_params, context) {
      const found = await topicOfChat(context);
      const drafts = await draftsOf(context.db, found.id);
      if (drafts.length === 0) throw new ToolError("There are no drafts to audit yet.");
      const prompt = deps.prompts.render("auditors/drafts.njk", { drafts });
      const findingsTool: Tool<typeof FoundProblems> = {
        name: "report_findings",
        description: deps.prompts.render("tools/report-findings.njk", {}),
        parameters: FoundProblems,
      };
      const coverageTool: Tool<typeof CoverageAnswer> = {
        name: "report_coverage",
        description: deps.prompts.render("tools/report-coverage.njk", { stages: COMPETENCY_STAGES }),
        parameters: CoverageAnswer,
      };
      const call = { prompt, runId: context.run.id, signal: context.signal };
      const [versions, precision, coverage] = await Promise.all([
        deps.oneShot({
          ...call,
          systemPrompt: deps.prompts.render("auditors/versions.njk", {}),
          tool: findingsTool,
        }),
        deps.oneShot({
          ...call,
          systemPrompt: deps.prompts.render("auditors/precision.njk", {}),
          tool: findingsTool,
        }),
        deps.oneShot({
          ...call,
          systemPrompt: deps.prompts.render("auditors/coverage.njk", { stages: COMPETENCY_STAGES }),
          tool: coverageTool,
        }),
      ]);
      const byAuditor = {
        versions: versions.findings,
        precision: precision.findings,
        coverage: coverage.findings,
      };
      const stored = await context.db.transaction(async (tx) => {
        const audit = await createRecord(tx, AuditRecord, {
          kind: "audit",
          author: { kind: "code", component: "audit_drafts" },
          body: { topic: found.id, drafts: drafts.map(refOf), matrix: coverage.matrix },
        });
        const records = [];
        for (const auditor of AUDITORS) {
          for (const item of byAuditor[auditor]) {
            records.push(
              await createRecord(tx, FindingRecord, {
                kind: "finding",
                author: { kind: "code", component: "audit_drafts" },
                body: {
                  audit: refOf(audit),
                  topic: found.id,
                  auditor,
                  path: item.path,
                  problem: item.problem,
                  fix: item.fix,
                  settled: null,
                },
              }),
            );
          }
        }
        return [audit, ...records];
      });
      return recordsStored(context.db, deps.prompts, stored);
    },
  };
}

const SettleParameters = Type.Object(
  {
    finding: Id,
    how: Type.Enum(["fixed", "kept"], {
      description: "fixed in a draft or a map item, or kept as it is (a draft's finding only)",
    }),
    note: Type.String({ minLength: 1, description: "What changed, or why the draft is right as it is" }),
  },
  CLOSED,
);

/** The tadpole's answer to a finding: fixed, or kept with its reason. */
export function settleFindingTool(deps: AgentDeps): HarnessTool<typeof SettleParameters> {
  return {
    name: "settle_finding",
    label: "Settle a finding",
    description: deps.prompts.render("tools/settle-finding.njk", {}),
    parameters: SettleParameters,
    kind: "change",
    async execute(params, context) {
      const finding = await findingOf(context.db, params.finding);
      if (finding.body.settled) throw new ToolError(`Finding ${params.finding} is settled already.`);
      if (finding.body.auditor === "evidence") {
        const refusal = await mapFindingRefusal(context.db, finding, params.how);
        if (refusal) throw new ToolError(refusal);
      }
      const settled = await changeRecord(context.db, FindingRecord, {
        from: refOf(finding),
        status: "active",
        author: context.author,
        reason: `Settled: ${params.how}`,
        body: { ...finding.body, settled: { how: params.how, note: params.note } },
      });
      return recordsStored(context.db, deps.prompts, [settled]);
    },
  };
}

async function findingOf(db: Conn, id: string) {
  const [row] = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(and(eq(harnessRecord.kind, "finding"), eq(harnessRecord.id, id)))
    .limit(1);
  if (!row) throw new ToolError(`There is no finding ${id}.`);
  return readLatestRecord(db, FindingRecord, "finding", id);
}

/** The topic's latest audit, if it has had one. */
async function latestAudit(db: Conn, topicId: string): Promise<AuditRecord | undefined> {
  const [last] = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(and(eq(harnessRecord.kind, "audit"), sql`${harnessRecord.body} ->> 'topic' = ${topicId}`))
    .orderBy(desc(harnessRecord.seq))
    .limit(1);
  if (!last) return undefined;
  return readLatestRecord(db, AuditRecord, "audit", last.id);
}

/**
 * Why the closing report can't go yet (harness-tools.md): the latest drafts audited, every finding
 * of that audit fixed or answered, a tips-and-tricks document, and every document passing the
 * corpus contract. Empty when it can.
 */
export async function closingReportProblems(deps: AgentDeps, db: Conn, found: Topic): Promise<string[]> {
  const problems: string[] = [];
  const dir = topicDir(found);
  const paths = corpusPaths(deps, dir);
  if (paths.length === 0) return ["The topic has no documents yet."];
  if (!paths.includes(`${dir}/${TIPS_AND_TRICKS}`)) {
    problems.push(`There is no ${TIPS_AND_TRICKS}: every topic has one.`);
  }
  let sections = 0;
  for (const path of paths) {
    const { document, errors } = parseDocument(path, readFileSync(corpusFile(deps, path)));
    for (const problem of errors.problems) problems.push(`${path}: ${problem}`);
    if (document) sections += document.sections.length;
  }
  const intake = await intakeOf(db, found.id);
  if (intake) {
    const needed = sectionsNeeded(intake.body.cardCount);
    if (sections < needed) {
      problems.push(
        `The documents hold ${sections} sections, and the topic's ${intake.body.cardCount} cards need at least ${needed}, one for every ${CARDS_PER_SECTION} cards: start writers to add ${needed - sections} more across the documents, each brief giving its document's new section count.`,
      );
    }
  }
  const drafts = await draftsOf(db, found.id);
  const audit = await latestAudit(db, found.id);
  if (!audit) {
    problems.push("The drafts have never been audited: call audit_drafts.");
    return problems;
  }
  const audited = new Set(audit.body.drafts.map((ref) => `${ref.id}@${ref.version}`));
  const unaudited = drafts.filter((draft) => !audited.has(`${draft.id}@${draft.version}`));
  for (const draft of unaudited) {
    problems.push(`${draft.body.path} changed after the last audit: call audit_drafts again.`);
  }
  const open = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(
      and(eq(harnessRecord.kind, "finding"), sql`${harnessRecord.body} -> 'audit' ->> 'id' = ${audit.id}`),
    );
  for (const row of open) {
    const finding = await readLatestRecord(db, FindingRecord, "finding", row.id);
    if (!finding.body.settled) problems.push(`Finding ${finding.id} is not settled.`);
  }
  return problems;
}

/** Ingests a topic's documents into the universe, once toad_sage says go on to its closing report. */
export async function ingestTopicCorpus(deps: AgentDeps, found: Topic): Promise<number> {
  const paths = corpusPaths(deps, topicDir(found));
  const parsed: ParsedDocument[] = [];
  for (const path of paths) {
    const { document, errors } = parseDocument(path, readFileSync(corpusFile(deps, path)));
    if (!document) throw new ToolError(`${path} fails the corpus contract: ${errors.problems.join("; ")}`);
    parsed.push(document);
  }
  let sections = 0;
  await deps.universe.transaction(async (tx) => {
    for (const document of parsed) sections += await ingestDocument(tx, document, deps.embedder);
  });
  return sections;
}
