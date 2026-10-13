import type { StreamFn } from "@spoin/pi-agent";
import {
  type Api,
  type AssistantMessage,
  type Message,
  type Model,
  normalizeContext,
  type ToolCall,
  type ToolResultMessage,
} from "@spoin/pi-ai";
import { Type } from "typebox";
import { checkValue, SchemaError } from "../harness/check.ts";
import { contextMessages } from "../harness/compaction.ts";
import { CLOSED } from "../harness/schemas.ts";
import { type HarnessTool, ToolError, type ToolOutput } from "../harness/tools.ts";
import { GEMINI_THINKING } from "../models/proxy.ts";
import type { Prompts } from "../prompts.ts";

/*
 * NIM writes, Gemini orchestrates (the owner's rule, task 0045). A writer chat runs on Gemini and
 * reads, plans and fixes there; each of its big writes (a document, a curriculum, a tier's cards,
 * its questions) is one NIM call. The writer calls the tool with what to write now, and the tool
 * hands NIM the writer's whole chat with the real tool, whose own checks store what NIM writes. A
 * call NIM gives up on goes to Gemini, so a bad day on NIM slows a topic rather than stopping it.
 */

/** How a tool calls NIM: its ladder for a run, with Gemini behind it. */
export interface NimWriter {
  /** Names the call; the ladder picks the model for each try. */
  model: Model<Api>;
  apiKey: string;
  streamFn: (runId: string) => StreamFn;
}

/** NIM's tries at one write: the first, and two with the last one's faults named. */
const TRIES = 3;

const Instructions = Type.Object(
  {
    instructions: Type.String({
      minLength: 1,
      description: "What to write in this call, and anything to fix from before",
    }),
  },
  CLOSED,
);

/** The writer's tool: NIM writes through `tool` from the writer's chat and these instructions. */
export function writtenOnNim(
  prompts: Prompts,
  nim: NimWriter,
  tool: HarnessTool,
): HarnessTool<typeof Instructions> {
  return {
    name: tool.name,
    label: tool.label,
    description: prompts.render("tools/written-on-nim.njk", { tool: tool.description }),
    parameters: Instructions,
    kind: "change",
    async execute(params, context) {
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
          instructions: params.instructions,
        }),
        timestamp: Date.now(),
      });
      const stream = nim.streamFn(context.run.id);
      const nimTool = { name: tool.name, description: tool.description, parameters: tool.parameters };
      const tries: string[] = [];
      for (let attempt = 1; attempt <= TRIES; attempt++) {
        const answer: AssistantMessage = await (
          await stream(
            nim.model,
            normalizeContext({ systemPrompt: context.run.systemPrompt, tools: [nimTool], messages }),
            { apiKey: nim.apiKey, reasoning: GEMINI_THINKING, signal: context.signal },
          )
        ).result();
        if (answer.stopReason === "error" || answer.stopReason === "aborted") {
          const why = answer.errorMessage ?? answer.stopReason;
          throw new ToolError(
            `${triesSoFar(tries)}The write didn't come back (${why}). Call ${tool.name} again.`,
          );
        }
        messages.push(answer);
        const calls = answer.content.filter((block): block is ToolCall => block.type === "toolCall");
        const [call, ...others] = calls;
        if (!call) {
          tries.push(`Try ${attempt} called no tool, and wrote:\n${textWritten(answer)}`);
          messages.push({ role: "user", content: `Call ${tool.name} with it.`, timestamp: Date.now() });
          continue;
        }
        for (const other of others) {
          messages.push(resultFor(other, "One call at a time: only the first was read.", true));
        }
        // What NIM wrote is kept whether or not it passes (the owner's rule: no output paid for twice).
        const written = `Try ${attempt}, as NIM wrote it:\n${JSON.stringify(call.arguments)}`;
        let output: ToolOutput;
        try {
          output = await tool.execute(
            checkValue(tool.parameters, call.arguments, `The call to ${tool.name}`),
            context,
          );
        } catch (error) {
          if (!(error instanceof ToolError) && !(error instanceof SchemaError)) throw error;
          tries.push(`${written}\nRefused: ${error.message}`);
          messages.push(resultFor(call, `${error.message}\nCall ${tool.name} again, fixed.`, true));
          continue;
        }
        tries.push(written);
        return { ...output, value: `${tries.join("\n\n")}\n\nStored:\n${textOf(output.value)}` };
      }
      throw new ToolError(
        `${triesSoFar(tries)}NIM's ${TRIES} tries were all refused. Call ${tool.name} again with what to fix.`,
      );
    },
  };
}

function triesSoFar(tries: string[]): string {
  if (tries.length === 0) return "";
  return `${tries.join("\n\n")}\n\n`;
}

function resultFor(call: ToolCall, text: string, isError: boolean): ToolResultMessage {
  return {
    role: "toolResult",
    toolCallId: call.id,
    toolName: call.name,
    content: [{ type: "text", text }],
    isError,
    timestamp: Date.now(),
  };
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
