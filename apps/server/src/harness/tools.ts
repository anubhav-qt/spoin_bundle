import type { AgentTool } from "@spoin/pi-agent";
import type { JsonValue } from "@spoin/pi-ai";
import type { Static, TSchema } from "typebox";
import type { Db } from "../db/client.ts";
import type { Chat, Run } from "./chats.ts";
import { checkValue } from "./check.ts";
import type { Author, RecordRef } from "./schemas.ts";

/** What a tool can reach while it runs: the database, and which chat and run is calling it. */
export interface ToolContext {
  db: Db;
  chat: Chat;
  run: Run;
  /** The author to put on any record the tool writes for the chat. */
  author: Author;
  signal: AbortSignal;
}

/**
 * What a tool hands back: the value the model reads, and the records it read and wrote, for the
 * action log. Text, such as records rendered from their templates, reaches the model as it is; any
 * other value as JSON.
 */
export interface ToolOutput {
  value: JsonValue;
  dataSeen: RecordRef[];
  recordsWritten: RecordRef[];
}

/**
 * A tool a chat calls (Trotter's `TrotterTool`). To fail, it throws an error that tells the model
 * what went wrong. `kind` says how it runs beside the other calls in the same reply (Seelie's, task
 * 0045): reads run at once, and changes one at a time, in the order the model made them.
 */
export interface HarnessTool<Parameters extends TSchema = TSchema> {
  name: string;
  label: string;
  description: string;
  parameters: Parameters;
  kind: "read" | "change";
  execute(params: Static<Parameters>, context: ToolContext): Promise<ToolOutput>;
}

/** A tool refusing a call. The model reads the message, so it says what to fix. */
export class ToolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ToolError";
  }
}

/** Called with each tool's output, so the action log can record what it read and wrote. */
export type OutputListener = (toolCallId: string, output: ToolOutput) => void;

/**
 * The tool as pi's agent loop runs it. The arguments are checked with checkValue before the tool
 * runs, in place of pi's coercion (which would turn a missing number into 0); a call that fails the
 * check never runs, and the model gets every problem back to fix in one go.
 */
export function toAgentTool(
  tool: HarnessTool,
  context: Omit<ToolContext, "signal">,
  onOutput: OutputListener,
): AgentTool<TSchema, ToolOutput> {
  return {
    name: tool.name,
    label: tool.label,
    description: tool.description,
    parameters: tool.parameters,
    executionMode: tool.kind === "change" ? "sequential" : "parallel",
    prepareArguments: (args) => checkValue(tool.parameters, args, `The call to ${tool.name}`),
    execute: async (toolCallId, params, signal) => {
      const output = await tool.execute(params, {
        ...context,
        signal: signal ?? new AbortController().signal,
      });
      onOutput(toolCallId, output);
      return { content: [{ type: "text", text: textFor(output.value) }], details: output };
    },
  };
}

function textFor(value: JsonValue): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
