import { Type } from "typebox";
import type { Prompts } from "../prompts.ts";
import { listSharedRecords, readSharedRecord, readSharedRecordHistory, refOf } from "./records.ts";
import { CLOSED, Id, RECORD_SCHEMAS, type RecordKind, RecordStatus } from "./schemas.ts";
import type { HarnessTool } from "./tools.ts";
import { viewsOf } from "./views.ts";

/**
 * Reading any record (Trotter's `read_record`, `read_record_history` and `list_records`, task 0045):
 * every chat's tools but AskAI's. Agents look records up rather than remember them, so a judgment
 * rests on what was recorded. Every record reads as its own template shows it, and AskAI's aren't
 * there: they are its readers' alone (ADR-0106).
 */

const ReadRecordParameters = Type.Object(
  {
    id: Id,
    version: Type.Optional(Type.Integer({ minimum: 1, description: "Leave it out for the latest version" })),
  },
  CLOSED,
);

export function readRecordTool(prompts: Prompts): HarnessTool<typeof ReadRecordParameters> {
  return {
    name: "read_record",
    label: "Read a record",
    description: prompts.render("tools/read-record.njk", {}),
    parameters: ReadRecordParameters,
    kind: "read",
    async execute(params, context) {
      const record = await readSharedRecord(context.db, params.id, params.version);
      const [view] = await viewsOf(context.db, [record]);
      return {
        value: prompts.render("tool-results/record.njk", { record: view }),
        dataSeen: [refOf(record)],
        recordsWritten: [],
      };
    },
  };
}

const ReadRecordHistoryParameters = Type.Object({ id: Id }, CLOSED);

export function readRecordHistoryTool(prompts: Prompts): HarnessTool<typeof ReadRecordHistoryParameters> {
  return {
    name: "read_record_history",
    label: "Read a record's history",
    description: prompts.render("tools/read-record-history.njk", {}),
    parameters: ReadRecordHistoryParameters,
    kind: "read",
    async execute(params, context) {
      const versions = await readSharedRecordHistory(context.db, params.id);
      return {
        value: prompts.render("tool-results/history.njk", { records: await viewsOf(context.db, versions) }),
        dataSeen: versions.map(refOf),
        recordsWritten: [],
      };
    },
  };
}

const RECORD_KINDS = Object.keys(RECORD_SCHEMAS) as RecordKind[];

const ListRecordsParameters = Type.Object(
  { kind: Type.Enum(RECORD_KINDS), status: Type.Optional(RecordStatus) },
  CLOSED,
);

export function listRecordsTool(prompts: Prompts): HarnessTool<typeof ListRecordsParameters> {
  return {
    name: "list_records",
    label: "List records",
    description: prompts.render("tools/list-records.njk", {}),
    parameters: ListRecordsParameters,
    kind: "read",
    async execute(params, context) {
      const records = await listSharedRecords(context.db, params.kind, params.status);
      const value = prompts.render("tool-results/listed.njk", {
        kind: params.kind,
        status: params.status ?? null,
        records: await viewsOf(context.db, records),
      });
      return { value, dataSeen: records.map(refOf), recordsWritten: [] };
    },
  };
}

export function readingTools(prompts: Prompts): HarnessTool[] {
  return [readRecordTool(prompts), readRecordHistoryTool(prompts), listRecordsTool(prompts)];
}
