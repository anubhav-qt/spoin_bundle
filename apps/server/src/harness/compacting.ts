import { estimateTextTokens } from "@spoin/pi-ai";
import type { Prompts } from "../prompts.ts";
import { findSummary, SUMMARY_MAX_TOKENS } from "./compaction.ts";
import { recordsStored } from "./outputs.ts";
import { changeRecord, createRecord, refOf } from "./records.ts";
import { CompactionSummaryRecord, SummarySections } from "./schemas.ts";
import { type HarnessTool, ToolError } from "./tools.ts";

/**
 * Writing the chat's summary (Trotter's `system-tools/compacting.ts`), only in a compaction run. It
 * covers the chat through this run, and is the next version of the chat's one summary record.
 */

const NEXT_SUMMARY_REASON = "The chat compacted again, folding in the summary before.";

export function writeSummaryTool(prompts: Prompts): HarnessTool<typeof SummarySections> {
  return {
    name: "write_summary",
    label: "Write the chat's summary",
    description: prompts.render("tools/write-summary.njk", { maxTokens: SUMMARY_MAX_TOKENS }),
    parameters: SummarySections,
    kind: "change",
    async execute(params, context) {
      checkSummaryLength(params);
      const { db, chat, run, author } = context;
      const body = { chatId: chat.id, throughRun: run.id, ...params };
      const earlier = await findSummary(db, chat);
      if (!earlier) {
        const first = await createRecord(db, CompactionSummaryRecord, {
          kind: "compaction_summary",
          author,
          body,
        });
        return recordsStored(prompts, [first]);
      }
      const next = await changeRecord(db, CompactionSummaryRecord, {
        from: refOf(earlier),
        status: "active",
        author,
        reason: NEXT_SUMMARY_REASON,
        body,
      });
      return recordsStored(prompts, [next]);
    },
  };
}

function checkSummaryLength(sections: SummarySections): void {
  const tokens = estimateTextTokens(JSON.stringify(sections));
  if (tokens > SUMMARY_MAX_TOKENS) {
    throw new ToolError(
      `The summary is about ${tokens} tokens; keep it under ${SUMMARY_MAX_TOKENS}. Keep only what you'll need from here on.`,
    );
  }
}
