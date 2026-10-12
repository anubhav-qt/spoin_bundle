import type { Prompts } from "../prompts.ts";
import { refOf } from "./records.ts";
import type { AnyRecord } from "./schemas.ts";
import type { ToolOutput } from "./tools.ts";

/**
 * What the harness's own tools hand back (Trotter's `system-tools/outputs.ts`). Records reach the
 * model rendered from their own templates, just as they reach a chat that is woken by them, never
 * as another agent's raw JSON.
 */

/** The records a writing tool stored, as the agents that read them will see them. */
export function recordsStored(prompts: Prompts, records: AnyRecord[]): ToolOutput {
  return {
    value: prompts.render("tool-results/stored.njk", { records }),
    dataSeen: [],
    recordsWritten: records.map(refOf),
  };
}
