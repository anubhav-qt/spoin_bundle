import {
  Agent,
  type AgentEvent,
  type AgentToolResult,
  type AgentTurnContext,
  type StreamFn,
  type ThinkingLevel,
} from "@spoin/pi-agent";
import { type Api, type AssistantMessage, contentText, type Model } from "@spoin/pi-ai";
import type { Db } from "../db/client.ts";
import { type Chat, endRun, type Run, type RunEnd, startRun } from "./chats.ts";
import { contextMessages, contextTokens } from "./compaction.ts";
import type { Author, RunTrigger } from "./schemas.ts";
import { type HarnessTool, type ToolOutput, toAgentTool } from "./tools.ts";
import { type ActionLogEntry, appendActionLogEntry, appendMessage } from "./transcript.ts";

export interface RunChatInput {
  db: Db;
  chat: Chat;
  model: Model<Api>;
  thinkingLevel: ThinkingLevel;
  triggers: RunTrigger[];
  /** The chat's instructions for this run, rendered from its template. */
  systemPrompt: string;
  /** The run's opening message, rendered from its template: what woke the chat. */
  prompt: string;
  tools: HarnessTool[];
  apiKey: string;
  /** How the model is called, given the run, so each call's row names it. Tests pass a stand-in. */
  streamFn: (run: Run) => StreamFn;
  /** Stops the run: the model stops and the run ends as stopped. */
  signal?: AbortSignal;
  /** Hears every event of the run once it's stored, so a caller can show the run as it happens. */
  onEvent?: (event: AgentEvent) => void;
  /** Once the chat's context reaches this many tokens, the run ends paused at its next step boundary, so the chat can compact. */
  pauseAtTokens?: number;
}

/** A tool call as the model made it, kept until the call finishes and is logged. */
interface MadeCall {
  arguments: unknown;
  reasoning: string;
}

/**
 * One run of a chat (Trotter's `run-chat.ts`, task 0045): the model reads the chat's transcript
 * since its last compaction and the new prompt, then calls tools until it's done. Every message is
 * stored as it ends and every tool call is logged as it finishes, so a run cut off halfway still
 * leaves its record. Returns the ended run.
 */
export async function runChat(input: RunChatInput): Promise<Run> {
  const { db, chat } = input;
  const history = await contextMessages(db, chat);
  const run = await startRun(db, {
    chatId: chat.id,
    model: input.model.id,
    triggers: input.triggers,
    systemPrompt: input.systemPrompt,
  });
  const author: Author = { kind: "chat", chatId: chat.id, runId: run.id, model: input.model.id };
  const outputs = new Map<string, ToolOutput>();
  const onOutput = (toolCallId: string, output: ToolOutput) => outputs.set(toolCallId, output);
  let paused = false;

  const agent = new Agent({
    initialState: {
      systemPrompt: input.systemPrompt,
      model: input.model,
      thinkingLevel: input.thinkingLevel,
      tools: input.tools.map((tool) => toAgentTool(tool, { db, chat, run, author }, onOutput)),
      messages: history,
    },
    streamFn: input.streamFn(run),
    getApiKey: () => input.apiKey,
    sessionId: chat.id,
    finishTurn: (turn) => {
      if (shouldPause(turn, input.pauseAtTokens)) {
        paused = true;
        return { action: "end" };
      }
      return undefined;
    },
  });
  agent.subscribe(recordEvents(db, run, outputs));
  if (input.onEvent) agent.subscribe(input.onEvent);

  const stop = () => agent.abort();
  input.signal?.addEventListener("abort", stop, { once: true });
  try {
    await agent.prompt(input.prompt);
  } catch (error) {
    // The loop reports model failures as messages; reaching here means storing the run itself failed.
    return endRun(db, run.id, { status: "failed", error: errorText(error) });
  } finally {
    input.signal?.removeEventListener("abort", stop);
  }
  if (paused) return endRun(db, run.id, { status: "paused" });
  return endRun(db, run.id, endOf(agent.state.messages));
}

/** A run pauses after a turn whose tool calls leave the context at the limit or past it, since the model would go on. */
function shouldPause(turn: AgentTurnContext, pauseAtTokens: number | undefined): boolean {
  if (pauseAtTokens === undefined) return false;
  if (turn.toolResults.length === 0) return false;
  return contextTokens(turn.context.messages) >= pauseAtTokens;
}

/** Stores each message as it ends and logs each tool call as it finishes. */
function recordEvents(db: Db, run: Run, outputs: Map<string, ToolOutput>) {
  const madeCalls = new Map<string, MadeCall>();
  return async (event: AgentEvent) => {
    if (event.type === "message_end") {
      // The system prompt is kept on the run, not in the transcript.
      if (event.message.role === "system") return;
      await appendMessage(db, run, event.message);
      if (event.message.role === "assistant") rememberCalls(event.message, madeCalls);
      return;
    }
    if (event.type === "tool_execution_end") {
      const madeCall = madeCalls.get(event.toolCallId);
      if (!madeCall) {
        throw new Error(`Tool call ${event.toolCallId} finished, but no assistant message made it.`);
      }
      const result: AgentToolResult<unknown> = event.result;
      await appendActionLogEntry(db, {
        runId: run.id,
        toolCallId: event.toolCallId,
        tool: event.toolName,
        arguments: madeCall.arguments,
        reasoning: madeCall.reasoning,
        ...outcomeOf(outputs.get(event.toolCallId), result),
      });
    }
  };
}

function rememberCalls(message: AssistantMessage, madeCalls: Map<string, MadeCall>): void {
  const reasoning = reasoningOf(message);
  for (const block of message.content) {
    if (block.type === "toolCall") madeCalls.set(block.id, { arguments: block.arguments, reasoning });
  }
}

/** The model's own words in the message that made the calls: its visible thinking, then its text. */
function reasoningOf(message: AssistantMessage): string {
  const parts: string[] = [];
  for (const block of message.content) {
    if (block.type === "thinking" && !block.redacted) parts.push(block.thinking);
    if (block.type === "text") parts.push(block.text);
  }
  return parts.join("\n\n").trim();
}

type Outcome = Pick<ActionLogEntry, "result" | "dataSeen" | "recordsWritten">;

/** A tool that ran hands back its output; anything else (bad arguments, an unknown tool, a throw) is an error. */
function outcomeOf(output: ToolOutput | undefined, result: AgentToolResult<unknown>): Outcome {
  if (output) {
    return {
      result: { ok: true, value: output.value },
      dataSeen: output.dataSeen,
      recordsWritten: output.recordsWritten,
    };
  }
  const error = contentText(result.content) || "The tool failed without saying why.";
  return { result: { ok: false, error }, dataSeen: [], recordsWritten: [] };
}

function endOf(messages: readonly { role: string }[]): RunEnd {
  const last = messages.findLast((message): message is AssistantMessage => message.role === "assistant");
  if (!last) return { status: "failed", error: "The model never answered." };
  if (last.stopReason === "aborted") return { status: "stopped" };
  if (last.stopReason === "error") {
    return { status: "failed", error: last.errorMessage ?? "The model answered with an error." };
  }
  return { status: "done" };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
