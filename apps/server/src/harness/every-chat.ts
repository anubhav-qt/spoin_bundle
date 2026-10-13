import type { Prompts } from "../prompts.ts";
import { answerTool, askTool } from "./asking.ts";
import type { Chat } from "./chats.ts";
import { readingTools } from "./reading.ts";
import type { HarnessTool } from "./tools.ts";

/**
 * The tools every chat has (harness-tools.md), AskAI's excepted: ADR-0106 gives it no database
 * handle, so a reader's text can never reach a record or another chat. A helper only reads: it has
 * no address to be asked at, and it asks nothing, leaving what it can't settle to its report.
 * designer_toad doesn't read records: list_art_requests gives it every card it draws, and reading
 * spent its calls on plans, drafts and its own old art (ADR-0109).
 */
export function everyChatTools(prompts: Prompts, chat: Chat): HarnessTool[] {
  if (chat.role === "helper") return readingTools(prompts);
  if (chat.role === "designer_toad") return [askTool(prompts), answerTool(prompts)];
  return [...readingTools(prompts), askTool(prompts), answerTool(prompts)];
}
