import type { HelperTask } from "@spoin/shared/enums";
import { Type } from "typebox";
import type { Db, Tx } from "../db/client.ts";
import { type Chat, newHelperChat } from "../harness/chats.ts";
import { briefOf } from "../harness/helper-reports.ts";
import { recordsStored } from "../harness/outputs.ts";
import { createRecord } from "../harness/records.ts";
import { type Author, BriefRecord, CLOSED, ReportRecord } from "../harness/schemas.ts";
import { type HarnessTool, ToolError } from "../harness/tools.ts";
import type { Prompts } from "../prompts.ts";

/*
 * Helpers (harness-tools.md, task 0045): a main chat starts one per task, by writing its brief,
 * which wakes it; the helper's last call is its report, which wakes the main chat.
 */

type Conn = Db | Tx;

export interface NewHelper {
  task: HelperTask;
  brief: string;
  topic?: string | null;
  path?: string | null;
  subtopic?: string | null;
}

/** Makes a helper under `main` and writes its brief, which wakes it. */
export async function startHelper(
  db: Conn,
  main: Chat,
  author: Author,
  helper: NewHelper,
): Promise<{ chat: Chat; brief: BriefRecord }> {
  const chat = await newHelperChat(db, main, helper.task);
  const brief = await createRecord(db, BriefRecord, {
    kind: "brief",
    author,
    body: {
      helper: chat.id,
      task: helper.task,
      brief: helper.brief,
      topic: helper.topic ?? null,
      path: helper.path ?? null,
      subtopic: helper.subtopic ?? null,
    },
  });
  return { chat, brief };
}

const StartHelperParameters = Type.Object(
  {
    task: Type.String({ minLength: 1, description: "A few words naming the task" }),
    brief: Type.String({
      minLength: 1,
      description: "Everything the helper needs: it sees none of your chat, only this and the records",
    }),
  },
  CLOSED,
);

/** A helper for the main chat's own work, with its tools but this one. */
export function startHelperTool(prompts: Prompts): HarnessTool<typeof StartHelperParameters> {
  return {
    name: "start_helper",
    label: "Start a helper",
    description: prompts.render("tools/start-helper.njk", {}),
    parameters: StartHelperParameters,
    kind: "change",
    async execute(params, context) {
      const { brief } = await context.db.transaction((tx) =>
        startHelper(tx, context.chat, context.author, {
          task: "helper",
          brief: `${params.task}: ${params.brief}`,
          topic: context.chat.topicId,
        }),
      );
      return recordsStored(context.db, prompts, [brief]);
    },
  };
}

const ReportParameters = Type.Object(
  {
    summary: Type.String({
      minLength: 1,
      description: "What you did, what you found, and what you could not settle",
    }),
  },
  CLOSED,
);

/** A helper's last call: the record its main chat reads. */
export function reportTool(prompts: Prompts): HarnessTool<typeof ReportParameters> {
  return {
    name: "report",
    label: "Report",
    description: prompts.render("tools/report.njk", {}),
    parameters: ReportParameters,
    kind: "change",
    async execute(params, context) {
      const brief = await briefOf(context.db, context.chat);
      if (!brief) throw new ToolError("You have no brief to report on: only a helper reports.");
      const report = await createRecord(context.db, ReportRecord, {
        kind: "report",
        author: context.author,
        body: { brief: { kind: "brief", id: brief.id, version: brief.version }, summary: params.summary },
      });
      const stored = await recordsStored(context.db, prompts, [report]);
      return { ...stored, value: `${String(stored.value)}\nYour work on this brief is done: end your turn.` };
    },
  };
}
