import {
  CHAT_ROLES,
  DIFFICULTIES,
  HELPER_TASKS,
  RECORD_STATUSES,
  RUN_STATUSES,
  SINGLE_CHAT_ROLES,
  TOPIC_CHAT_ROLES,
  TOPIC_SCOPES,
} from "@spoin/shared/enums";
import { type Static, type TSchema, Type } from "typebox";

/**
 * The harness's shared data format, Trotter's ADR 0023 (task 0045): versioned records, runs and
 * their triggers, the action log and wakes, as typebox schemas checked by `checkValue`. Every
 * object is closed: a field the schema doesn't name is an error, so a misspelt field in a model's
 * handover is caught instead of dropped.
 */

export const CLOSED = { additionalProperties: false } as const;

/** Text that must say something. */
export const Text = Type.String({ minLength: 1 });

export const Id = Type.String({ format: "uuid" });

/** A moment, as a UTC ISO 8601 string ending in Z. */
export const UtcTimestamp = Type.String({
  format: "date-time",
  pattern: "Z$",
  description: "A UTC ISO 8601 timestamp ending in Z",
});

export const ChatRole = Type.Enum([...CHAT_ROLES]);
export const RecordStatus = Type.Enum([...RECORD_STATUSES]);
export const RunStatus = Type.Enum([...RUN_STATUSES]);

/** One exact version of a record, so what an agent saw or cited reads back as it was then. */
export const RecordRef = Type.Object({ kind: Text, id: Id, version: Type.Integer({ minimum: 1 }) }, CLOSED);

/** Who wrote a version: a chat (with the run and model, so models can be compared), code, or the owner. */
export const Author = Type.Union([
  Type.Object({ kind: Type.Literal("chat"), chatId: Id, runId: Id, model: Text }, CLOSED),
  Type.Object({ kind: Type.Literal("code"), component: Text }, CLOSED),
  Type.Object({ kind: Type.Literal("owner") }, CLOSED),
]);

/** The fields every version of a record carries. A change, a retirement or an undo is a new version. */
export function versionFields<Kind extends string>(kind: Kind) {
  return {
    id: Id,
    version: Type.Integer({ minimum: 1 }),
    kind: Type.Literal(kind),
    status: RecordStatus,
    writtenAt: UtcTimestamp,
    author: Author,
    reason: Type.Optional(
      Type.String({ minLength: 1, description: "Why this version changed the one before it" }),
    ),
    revertsTo: Type.Optional(
      Type.Integer({ minimum: 1, description: "Set on an undo: the earlier version this one puts back" }),
    ),
  };
}

/** A versioned record of one kind, holding a body its writer wrote. */
export function versionedRecord<Kind extends string, Body extends TSchema>(kind: Kind, body: Body) {
  return Type.Object({ ...versionFields(kind), body }, CLOSED);
}

/**
 * What woke a run (Trotter's ADR 0026, 0027): a schedule's slot; a record the chat should read; a
 * queued topic name for toad_sage to take in; a compaction, since the chat's context reached its
 * limit; or a continuation of a run that paused so the chat could compact, which brings the paused
 * run's own triggers with it.
 */
export const ScheduleTrigger = Type.Object({ kind: Type.Literal("schedule"), schedule: Text }, CLOSED);
export const RecordTrigger = Type.Object({ kind: Type.Literal("record"), record: RecordRef }, CLOSED);
/** A topic name waiting in the queue, by its generate job (task 0045). */
export const JobTrigger = Type.Object({ kind: Type.Literal("job"), job: Id }, CLOSED);
/** A reader's turn in an AskAI thread: their question, untrusted, and the card they were on, if any. */
export const ReaderTrigger = Type.Object(
  { kind: Type.Literal("reader"), question: Text, card: Type.Union([Id, Type.Null()]) },
  CLOSED,
);
export const RunTrigger = Type.Union([
  ScheduleTrigger,
  RecordTrigger,
  JobTrigger,
  ReaderTrigger,
  Type.Object(
    {
      kind: Type.Literal("compaction"),
      contextTokens: Type.Integer({ minimum: 0 }),
      /** Set when the chat compacts after its turn ended, while it waits for other chats. */
      whileWaiting: Type.Optional(Type.Literal(true)),
    },
    CLOSED,
  ),
  Type.Object({ kind: Type.Literal("continuation"), run: Id }, CLOSED),
]);

/** What the scheduler queues a wake for. */
export const WakeTrigger = Type.Union([ScheduleTrigger, RecordTrigger, JobTrigger]);

/** A tool call's result in the action log. */
export const ActionResult = Type.Union([
  Type.Object({ ok: Type.Literal(true), value: Type.Unknown() }, CLOSED),
  Type.Object({ ok: Type.Literal(false), error: Text }, CLOSED),
]);

/**
 * A chat by its address: one of the chats there is one of, or a topic's tadpole, designer_toad or
 * visual_toad. A helper has no address; it reports to the chat that started it.
 */
export const ChatAddress = Type.Union([
  Type.Object({ role: Type.Enum([...SINGLE_CHAT_ROLES]) }, CLOSED),
  Type.Object({ role: Type.Enum([...TOPIC_CHAT_ROLES]), topic: Id }, CLOSED),
]);

/** A question one chat asks another (Trotter's `ask`); it wakes the chat it asks. */
export const Question = Type.Object({ to: ChatAddress, question: Text, reasoning: Text }, CLOSED);

/** An answer to a question; it wakes the chat that asked. */
export const Answer = Type.Object({ question: RecordRef, answer: Text }, CLOSED);

/**
 * What a chat writes when it compacts (Trotter's ADR 0014, copied exactly per task 0045), in fixed
 * sections and under 2,000 tokens. No numbers: card counts, progress and targets are read fresh
 * from the tools at the next run. The earlier summary is folded into each new one.
 */
export const SummarySections = Type.Object(
  {
    soFar: Text,
    learnings: Type.Array(Text),
    feedback: Type.Array(Text, {
      description: "The auditors' findings and toad_sage's reviews it received",
    }),
    dos: Type.Array(Text),
    donts: Type.Array(Text),
    nextSteps: Type.Array(Text),
  },
  CLOSED,
);

/**
 * A chat's summary as stored: whose it is and the last run it covers, then its sections. Each chat
 * has one summary record, and each compaction writes its next version, so an undo puts back the
 * earlier summary together with the earlier point the chat reads its transcript from.
 */
export const CompactionSummary = Type.Object(
  {
    chatId: Id,
    throughRun: Type.String({
      format: "uuid",
      description: "The chat's last run the summary covers: the chat reads only the messages after it",
    }),
    ...SummarySections.properties,
  },
  CLOSED,
);

/**
 * What toad_sage decided when it took a name in (task 0045): what the topic is, who it is for, how
 * it is grouped, how many cards it gets and what it should cover. The topic row carries the name,
 * scope and category for the product; the tadpole and the curriculum chat read this.
 */
export const Intake = Type.Object(
  {
    topic: Id,
    name: Text,
    subject: Type.String({
      minLength: 1,
      description: "What the topic is about, told apart from its namesakes",
    }),
    angle: Type.Union([Text, Type.Null()], {
      description: "Who it is for and how it is written; null when it has none",
    }),
    scope: Type.Enum([...TOPIC_SCOPES]),
    category: Text,
    subCategory: Type.Union([Text, Type.Null()]),
    cardCount: Type.Integer({ minimum: 1 }),
    brief: Type.String({ minLength: 1, description: "What the topic should cover" }),
    buildsOn: Type.Array(Id, {
      description: "Topics sharing its subject, whose corpus and pages its tadpole reuses",
    }),
  },
  CLOSED,
);

/** A requester moved by a merge, with what their subscription held, so an undo can put it back. */
const MergedRequester = Type.Object(
  {
    userId: Id,
    displayName: Text,
    entry: Type.Enum([...DIFFICULTIES]),
    accentHue: Type.Union([Type.Integer(), Type.Null()]),
  },
  CLOSED,
);

/**
 * A requested name folded into a topic (task 0045). Its placeholder and job are gone, so this keeps
 * all ero_sennin needs to judge the merge and to undo it: the name and description as asked, its
 * aliases, requesters and priority, and both topics' subject and angle as toad_sage read them.
 */
export const Merge = Type.Object(
  {
    requested: Type.Object(
      {
        name: Text,
        description: Type.Union([Text, Type.Null()]),
        subject: Text,
        angle: Type.Union([Text, Type.Null()]),
        priority: Type.Integer(),
        aliases: Type.Array(Type.Object({ normalizedText: Text, rawText: Text }, CLOSED)),
        requesters: Type.Array(MergedRequester),
      },
      CLOSED,
    ),
    into: Type.Object(
      { topic: Id, name: Text, subject: Text, angle: Type.Union([Text, Type.Null()]) },
      CLOSED,
    ),
    reasoning: Text,
  },
  CLOSED,
);

/**
 * A helper's task, written by the chat that starts it (task 0045); it wakes the helper. What the
 * task is about: a document writer's path, a topic, or a tier.
 */
export const Brief = Type.Object(
  {
    helper: Id,
    task: Type.Enum([...HELPER_TASKS]),
    brief: Text,
    topic: Type.Union([Id, Type.Null()]),
    path: Type.Union([Text, Type.Null()]),
    subtopic: Type.Union([Id, Type.Null()]),
    /** A document writer's: how many sections its document must have, which write_document holds it to. */
    sections: Type.Optional(Type.Integer({ minimum: 1 })),
  },
  CLOSED,
);

/** A helper's last word on its brief; it wakes the chat that started it. */
export const Report = Type.Object({ brief: RecordRef, summary: Text }, CLOSED);

/** What a chat hands toad_sage at the procedure's approval points (ADR-0100, task 0045). */
export const HANDOVER_KINDS = [
  "coverage",
  "maps",
  "closing_report",
  "insufficient_evidence",
  "curriculum",
] as const;

/** Work handed to toad_sage for review; it wakes toad_sage, and the run that sent it ends. */
export const Handover = Type.Object(
  {
    kind: Type.Enum([...HANDOVER_KINDS]),
    topic: Id,
    records: Type.Array(RecordRef),
    note: Type.String({ minLength: 1, description: "The note, the report or the reasoning handed over" }),
    /** The tier an "insufficient evidence" is about. */
    subtopic: Type.Union([Id, Type.Null()]),
  },
  CLOSED,
);

/** toad_sage's answer to a handover; it wakes the chat that sent it. */
export const Review = Type.Object(
  { handover: RecordRef, verdict: Type.Enum(["go_on", "change"]), notes: Text },
  CLOSED,
);

/** ADR-0100's maps, before prose: domain, prerequisites, claims, evidence, competencies, misconceptions, applications, variability, gaps, versions. */
export const MAP_KINDS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"] as const;
export const CLAIM_TYPES = [
  "normative",
  "empirical",
  "mechanistic",
  "heuristic",
  "implementation",
  "pedagogical",
] as const;
export const CLAIM_SCOPES = ["universal", "common", "conditional", "product-specific"] as const;
export const CONFIDENCES = ["high", "medium", "low"] as const;
/** The source hierarchy, highest first (antigravity-corpus-authoring.md). */
export const SOURCE_TIERS = [
  "primary_specification",
  "official_documentation",
  "primary_research",
  "authoritative_textbook",
  "recognised_expert",
  "secondary_synthesis",
  "community_heuristic",
] as const;

/** A stored page's passage, as `fetch` numbered it. */
export const Evidence = Type.Object({ page: Id, passage: Type.Integer({ minimum: 1 }) }, CLOSED);

export const MapItem = Type.Object(
  {
    name: Type.String({ minLength: 1, description: "Short and unique within the map" }),
    text: Text,
    claimType: Type.Optional(Type.Enum([...CLAIM_TYPES])),
    scope: Type.Optional(Type.Enum([...CLAIM_SCOPES])),
    confidence: Type.Optional(Type.Enum([...CONFIDENCES])),
    sourceTier: Type.Optional(Type.Enum([...SOURCE_TIERS])),
    evidence: Type.Array(Evidence),
    after: Type.Optional(
      Type.Array(Text, { description: "Map B: the names of the items that must be understood first" }),
    ),
    checkBy: Type.Optional(
      Type.String({ format: "date", description: "Map J: when the claim must be checked again" }),
    ),
  },
  CLOSED,
);

export const TopicMap = Type.Object(
  { topic: Id, map: Type.Enum([...MAP_KINDS]), items: Type.Array(MapItem, { minItems: 1 }), summary: Text },
  CLOSED,
);

/** A corpus document as its writer last wrote it; every write is its next version. */
export const Draft = Type.Object({ topic: Id, path: Text, text: Text }, CLOSED);

/** The three auditing calls, each with its own fixed prompt (corpus-authoring-system.md roles 11-13). */
export const AUDITORS = ["versions", "precision", "coverage"] as const;
/** The zero-to-mastery stages the coverage auditor marks (role 13). */
export const COMPETENCY_STAGES = [
  "awareness",
  "vocabulary",
  "foundational mental model",
  "fundamentals",
  "basic application",
  "guided practice",
  "independent application",
  "diagnosis and debugging",
  "trade-off reasoning",
  "novel situations",
  "cross-topic integration",
  "expert judgment",
] as const;

export const CoverageMark = Type.Object(
  {
    stage: Type.Enum([...COMPETENCY_STAGES]),
    mark: Type.Enum(["strong", "weak", "absent"]),
    evidence: Text,
  },
  CLOSED,
);

/** One run of audit_drafts: the drafts it read and the coverage matrix. Its findings are records of their own. */
export const Audit = Type.Object(
  { topic: Id, drafts: Type.Array(RecordRef), matrix: Type.Array(CoverageMark) },
  CLOSED,
);

/** A problem an auditor found, settled by the tadpole once fixed or answered. */
export const Finding = Type.Object(
  {
    audit: RecordRef,
    topic: Id,
    auditor: Type.Enum([...AUDITORS]),
    path: Type.Union([Text, Type.Null()]),
    problem: Text,
    fix: Text,
    settled: Type.Union([
      Type.Null(),
      Type.Object({ how: Type.Enum(["fixed", "kept"]), note: Text }, CLOSED),
    ]),
  },
  CLOSED,
);

/** The card types a tier's quotas share out (content-model.md), mirrored from frog's curriculum contract. */
export const CARD_TYPES = ["prose", "image", "code", "diagram", "comparison", "ascii"] as const;

const Count = Type.Integer({ minimum: 0 });

export const CardTypeQuotas = Type.Object(
  {
    prose: Type.Optional(Count),
    image: Type.Optional(Count),
    code: Type.Optional(Count),
    diagram: Type.Optional(Count),
    comparison: Type.Optional(Count),
    ascii: Type.Optional(Count),
  },
  CLOSED,
);

export const CurriculumTier = Type.Object(
  {
    targetCards: Type.Integer({ minimum: 5, maximum: 25 }),
    cardTypes: CardTypeQuotas,
    grounding: Type.Array(Text, {
      minItems: 1,
      description: "`<corpus path>#<exact ## heading>`, 5 to 10 of them",
    }),
  },
  CLOSED,
);

export const CurriculumSubtopic = Type.Object(
  {
    title: Text,
    description: Text,
    prerequisites: Type.Array(Text),
    tiers: Type.Object(
      {
        beginner: Type.Optional(CurriculumTier),
        intermediate: Type.Optional(CurriculumTier),
        advanced: Type.Optional(CurriculumTier),
      },
      CLOSED,
    ),
  },
  CLOSED,
);

/** A topic's curriculum as its writer wrote it, checked against the whole contract on the way in. */
export const Curriculum = Type.Object(
  {
    topic: Id,
    description: Text,
    subtopics: Type.Array(CurriculumSubtopic, { minItems: 1 }),
    reasoning: Text,
  },
  CLOSED,
);

/** A tier's plan (ADR-0059): concept, form and angle per card. */
export const CardPlan = Type.Object(
  {
    subtopic: Id,
    briefs: Type.Array(
      Type.Object({ concept: Text, form: Type.Enum([...CARD_TYPES]), angle: Text }, CLOSED),
      { minItems: 1 },
    ),
  },
  CLOSED,
);

/**
 * Drafts sent to the tier's pass-1 corrector (task 0045); it wakes the corrector. Pass 2 needs no
 * gate record: code starts a verifier on each batch with a brief of its own. The stages name the
 * verdicts too.
 */
export const GATE_STAGES = ["pass1", "pass2", "questions"] as const;
export const Gate = Type.Object(
  {
    stage: Type.Enum([...GATE_STAGES]),
    subtopic: Id,
    to: Id,
    writer: Id,
    items: Type.Array(Id, { minItems: 1 }),
  },
  CLOSED,
);

/** What a gate pass decided; it wakes the writer, and designer_toad for cards pass 2 accepted. */
export const Verdicts = Type.Object(
  {
    stage: Type.Enum([...GATE_STAGES]),
    subtopic: Id,
    writer: Id,
    accepted: Type.Array(Id),
    rejected: Type.Array(Type.Object({ id: Id, feedback: Text }, CLOSED)),
  },
  CLOSED,
);

/** One phone render of a card with designer_toad's art. */
export const Render = Type.Object({ card: Id, art: Text }, CLOSED);

/** Art attached to a card. It wakes no one: the art that completes a tier puts its cards live. */
export const Art = Type.Object({ card: Id, render: RecordRef, writer: Id }, CLOSED);

export const QuestionRecord = versionedRecord("question", Question);
export const AnswerRecord = versionedRecord("answer", Answer);
export const CompactionSummaryRecord = versionedRecord("compaction_summary", CompactionSummary);
export const IntakeRecord = versionedRecord("intake", Intake);
export const MergeRecord = versionedRecord("merge", Merge);
export const BriefRecord = versionedRecord("brief", Brief);
export const ReportRecord = versionedRecord("report", Report);
export const HandoverRecord = versionedRecord("handover", Handover);
export const ReviewRecord = versionedRecord("review", Review);
export const MapRecord = versionedRecord("map", TopicMap);
export const DraftRecord = versionedRecord("draft", Draft);
export const AuditRecord = versionedRecord("audit", Audit);
export const FindingRecord = versionedRecord("finding", Finding);
export const CurriculumRecord = versionedRecord("curriculum", Curriculum);
export const CardPlanRecord = versionedRecord("card_plan", CardPlan);
export const GateRecord = versionedRecord("gate", Gate);
export const VerdictsRecord = versionedRecord("verdicts", Verdicts);
export const RenderRecord = versionedRecord("render", Render);
export const ArtRecord = versionedRecord("art", Art);

/** The schema of every kind of record, so code holding only a reference can read and check it. */
export const RECORD_SCHEMAS = {
  question: QuestionRecord,
  answer: AnswerRecord,
  compaction_summary: CompactionSummaryRecord,
  intake: IntakeRecord,
  merge: MergeRecord,
  brief: BriefRecord,
  report: ReportRecord,
  handover: HandoverRecord,
  review: ReviewRecord,
  map: MapRecord,
  draft: DraftRecord,
  audit: AuditRecord,
  finding: FindingRecord,
  curriculum: CurriculumRecord,
  card_plan: CardPlanRecord,
  gate: GateRecord,
  verdicts: VerdictsRecord,
  render: RenderRecord,
  art: ArtRecord,
} as const;

export type RecordKind = keyof typeof RECORD_SCHEMAS;

export function isRecordKind(kind: string): kind is RecordKind {
  return Object.hasOwn(RECORD_SCHEMAS, kind);
}

/** Any one kind of record, typed by its kind. */
export type AnyRecord = { [Kind in RecordKind]: Static<(typeof RECORD_SCHEMAS)[Kind]> }[RecordKind];

export type RecordRef = Static<typeof RecordRef>;
export type RecordStatus = Static<typeof RecordStatus>;
export type Author = Static<typeof Author>;
export type RunTrigger = Static<typeof RunTrigger>;
export type WakeTrigger = Static<typeof WakeTrigger>;
export type ActionResult = Static<typeof ActionResult>;
export type ChatAddress = Static<typeof ChatAddress>;
export type QuestionRecord = Static<typeof QuestionRecord>;
export type AnswerRecord = Static<typeof AnswerRecord>;
export type SummarySections = Static<typeof SummarySections>;
export type CompactionSummary = Static<typeof CompactionSummary>;
export type CompactionSummaryRecord = Static<typeof CompactionSummaryRecord>;
export type Intake = Static<typeof Intake>;
export type IntakeRecord = Static<typeof IntakeRecord>;
export type MergeRecord = Static<typeof MergeRecord>;
export type BriefRecord = Static<typeof BriefRecord>;
export type ReportRecord = Static<typeof ReportRecord>;
export type HandoverRecord = Static<typeof HandoverRecord>;
export type ReviewRecord = Static<typeof ReviewRecord>;
export type MapRecord = Static<typeof MapRecord>;
export type MapItem = Static<typeof MapItem>;
export type DraftRecord = Static<typeof DraftRecord>;
export type AuditRecord = Static<typeof AuditRecord>;
export type FindingRecord = Static<typeof FindingRecord>;
export type Curriculum = Static<typeof Curriculum>;
export type CurriculumRecord = Static<typeof CurriculumRecord>;
export type CardPlanRecord = Static<typeof CardPlanRecord>;
export type GateRecord = Static<typeof GateRecord>;
export type VerdictsRecord = Static<typeof VerdictsRecord>;
export type RenderRecord = Static<typeof RenderRecord>;
export type ArtRecord = Static<typeof ArtRecord>;
