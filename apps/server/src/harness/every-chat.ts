import type { Prompts } from "../prompts.ts";
import { answerTool, askTool } from "./asking.ts";
import type { Chat } from "./chats.ts";
import { readingTools } from "./reading.ts";
import type { HarnessTool } from "./tools.ts";

/**
 * The tools every chat has (harness-tools.md), AskAI's excepted: ADR-0106 gives it no database
 * handle, so a reader's text can never reach a record or another chat. A helper only reads: it has
 * no address to be asked at, and it asks nothing, leaving what it can't settle to its report.
 */
export function everyChatTools(prompts: Prompts, chat: Chat): HarnessTool[] {
  if (chat.role === "helper") return readingTools(prompts);
  return [...readingTools(prompts), askTool(prompts), answerTool(prompts)];
}
