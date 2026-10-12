import {
  CHAT_ROLES,
  RECORD_STATUSES,
  RUN_STATUSES,
  SINGLE_CHAT_ROLES,
  TOPIC_CHAT_ROLES,
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
 * compaction, since the chat's context reached its limit; or a continuation of a run that paused
 * so the chat could compact, which brings the paused run's own triggers with it.
 */
export const ScheduleTrigger = Type.Object({ kind: Type.Literal("schedule"), schedule: Text }, CLOSED);
export const RecordTrigger = Type.Object({ kind: Type.Literal("record"), record: RecordRef }, CLOSED);
export const RunTrigger = Type.Union([
  ScheduleTrigger,
  RecordTrigger,
  Type.Object({ kind: Type.Literal("compaction"), contextTokens: Type.Integer({ minimum: 0 }) }, CLOSED),
  Type.Object({ kind: Type.Literal("continuation"), run: Id }, CLOSED),
]);

/** What the scheduler queues a wake for. */
export const WakeTrigger = Type.Union([ScheduleTrigger, RecordTrigger]);

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
      description: "ero_sennin's findings, toad_sage's reviews and wise_toad's lessons it received",
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

export const QuestionRecord = versionedRecord("question", Question);
export const AnswerRecord = versionedRecord("answer", Answer);
export const CompactionSummaryRecord = versionedRecord("compaction_summary", CompactionSummary);

/** The schema of every kind of record, so code holding only a reference can read and check it. */
export const RECORD_SCHEMAS = {
  question: QuestionRecord,
  answer: AnswerRecord,
  compaction_summary: CompactionSummaryRecord,
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
