import type { StreamFn } from "@spoin/pi-agent";
import {
  type Api,
  type AssistantMessage,
  type Message,
  type Model,
  normalizeContext,
  type ToolCall,
} from "@spoin/pi-ai";
import { Type } from "typebox";
import { checkValue, SchemaError } from "../harness/check.ts";
import { contextMessages } from "../harness/compaction.ts";
import { CLOSED } from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError, type ToolOutput } from "../harness/tools.ts";
import { GEMINI_THINKING } from "../models/proxy.ts";
import type { Prompts } from "../prompts.ts";

/*
 * NIM writes, the Gemini writer decides (the owner's rule, task 0045, ADR-0108). A writer chat runs
 * on Gemini with the real write tools, for the small writes it makes itself: a fix, a section
 * added or dropped. For a big write (a whole document, curriculum, tier's cards or its quiz) it
 * calls write_on_nim, which hands NIM the writer's whole chat and instructions. NIM answers with
 * the tool's arguments as JSON text, and code stores them through the real tool, whose checks
 * decide what passes. Text, not a tool call: NVIDIA sends a tool call's arguments in one piece once
 * they are all written, so a big write was minutes of silence that looked like a dead call.
 */

/**
 * How write_on_nim calls NIM: its ladder for a run, which retries a call across it (busy,
 * rate-limited, cut off or silent), with Gemini behind it for a call NIM gives up on. An answer
 * that comes back unusable goes to the writer, which calls again with what to change.
 */
export interface NimWriter {
  /** Names the call; the ladder picks the model. */
  model: Model<Api>;
  apiKey: string;
  streamFn: (runId: string) => StreamFn;
}

function writeOnNimParameters(names: string[]) {
  return Type.Object(
    {
      tool: Type.Enum(names, { description: "The tool whose write NIM makes" }),
      instructions: Type.String({
        minLength: 1,
        description: "What NIM writes in this call: the shape you decided, and what to draw on",
      }),
    },
    CLOSED,
  );
}

/** The writer's big writes: NIM writes one of `tools`' arguments from the writer's chat. */
export function writeOnNimTool(
  prompts: Prompts,
  nim: NimWriter,
  tools: HarnessTool[],
): HarnessTool<ReturnType<typeof writeOnNimParameters>> {
  const names = tools.map((tool) => tool.name);
  const parameters = writeOnNimParameters(names);
  return {
    name: "write_on_nim",
    label: "Write on NIM",
    description: prompts.render("tools/write-on-nim.njk", { tools: names }),
    parameters,
    kind: "change",
    async execute(params, context) {
      const tool = tools.find((one) => one.name === params.tool);
      if (!tool) throw new ToolError(`NIM writes only with ${names.join(" or ")}.`);
      // The chat up to the call that asked for this write, which has no result yet.
      const history = await contextMessages(context.db, context.chat);
      const asked = history.findLastIndex((message) => message.role === "assistant");
      const messages: Message[] = [];
      if (asked === -1) messages.push(...history);
      else messages.push(...history.slice(0, asked));
      messages.push({
        role: "user",
        content: prompts.render("lines/nim-write.njk", {
          tool: tool.name,
          schema: JSON.stringify(tool.parameters),
          instructions: params.instructions,
        }),
        timestamp: Date.now(),
      });
      // The tool goes along so the chat's earlier calls read as calls; "none" has NIM answer in text.
      const nimTool = { name: tool.name, description: tool.description, parameters: tool.parameters };
      const stream = nim.streamFn(context.run.id);
      const answer: AssistantMessage = await (
        await stream(
          nim.model,
          normalizeContext({ systemPrompt: context.run.systemPrompt, tools: [nimTool], messages }),
          { apiKey: nim.apiKey, reasoning: GEMINI_THINKING, toolChoice: "none", signal: context.signal },
        )
      ).result();
      if (answer.stopReason === "error" || answer.stopReason === "aborted") {
        const why = answer.errorMessage ?? answer.stopReason;
        throw new ToolError(
          `NIM's write didn't come back (${why}). Call write_on_nim again, or write it yourself with ${tool.name}.`,
        );
      }
      const written = argumentsWritten(answer, tool.name);
      if (written === undefined) {
        throw new ToolError(
          `NIM wrote no JSON for ${tool.name}, so nothing was stored. What it wrote, kept:\n${textWritten(answer)}`,
        );
      }
      return await stored(tool, written, context);
    },
  };
}

/**
 * The writer's own copy of a tool whose first write is NIM's (the owner's rule for a tier's cards
 * and questions): it refuses until `firstWritten` says that write happened, and corrects after.
 */
export function correctionsOnly(
  tool: HarnessTool,
  firstWritten: (context: ToolContext) => Promise<boolean>,
): HarnessTool {
  return {
    ...tool,
    async execute(params, context) {
      if (!(await firstWritten(context))) {
        throw new ToolError(
          `The first write is NIM's: call write_on_nim with ${tool.name}. ${tool.name} is for corrections once it has written.`,
        );
      }
      return tool.execute(params, context);
    },
  };
}

/**
 * Stores what NIM wrote through the real tool. It is kept in the result whether or not it passes
 * (the owner's rule: no output paid for twice), so a fix is a small write the writer makes itself.
 */
async function stored(tool: HarnessTool, written: unknown, context: ToolContext): Promise<ToolOutput> {
  const kept = `NIM wrote:\n${JSON.stringify(written)}`;
  let output: ToolOutput;
  try {
    output = await tool.execute(checkValue(tool.parameters, written, `NIM's ${tool.name}`), context);
  } catch (error) {
    if (!(error instanceof ToolError) && !(error instanceof SchemaError)) throw error;
    throw new ToolError(
      `${kept}\n\nRefused: ${error.message}\nFix it with ${tool.name} yourself, sending only what changes.`,
    );
  }
  return { ...output, value: `${kept}\n\nStored:\n${textOf(output.value)}` };
}

/**
 * The arguments NIM wrote: the JSON object in its text, or, if it called the tool anyway, that
 * call's. Undefined when it wrote neither.
 */
function argumentsWritten(answer: AssistantMessage, name: string): unknown {
  for (const block of answer.content) {
    if (block.type === "toolCall" && block.name === name) return (block as ToolCall).arguments;
  }
  const text = textWritten(answer);
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end < start) return undefined;
  try {
    return JSON.parse(text.slice(start, end + 1));
  } catch {
    return undefined;
  }
}

function textWritten(answer: AssistantMessage): string {
  const parts: string[] = [];
  for (const block of answer.content) {
    if (block.type === "text") parts.push(block.text);
  }
  return parts.join("\n");
}

function textOf(value: ToolOutput["value"]): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
