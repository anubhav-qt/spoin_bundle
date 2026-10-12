import { type Api, estimateContextTokens, estimateTextTokens, type Message, type Model } from "@spoin/pi-ai";
import type { Db } from "../db/client.ts";
import { type Chat, readRun } from "./chats.ts";
import { listLatestRecords } from "./records.ts";
import { CompactionSummaryRecord, type CompactionSummaryRecord as Summary } from "./schemas.ts";
import { lastSeqOfRun, readTranscript, type TranscriptMessage } from "./transcript.ts";

/**
 * Compaction (Trotter's ADR 0014, copied exactly per task 0045): once a chat's context reaches its
 * limit, the chat saves what isn't stored and writes a short summary. From then on the model reads
 * its instructions, with the summary in them, and only the messages after the run the summary
 * covers. The whole transcript stays stored.
 */

/** A chat compacts at `atTokens`, or at `atWindowShare` of its model's window if that is smaller. */
export interface CompactionSettings {
  atTokens: number;
  atWindowShare: number;
}

export const COMPACTION_SETTINGS: CompactionSettings = { atTokens: 400_000, atWindowShare: 0.6 };

/** The longest a summary may be, in tokens. */
export const SUMMARY_MAX_TOKENS = 2_000;

/** The context size, in tokens, at which a chat on this model compacts. */
export function compactionLimit(model: Model<Api>, settings: CompactionSettings): number {
  return Math.min(settings.atTokens, Math.floor(model.contextWindow * settings.atWindowShare));
}

/** The latest version of the chat's summary, whatever its status. */
export async function findSummary(db: Db, chat: Chat): Promise<Summary | undefined> {
  const summaries = await listLatestRecords(db, CompactionSummaryRecord, "compaction_summary");
  return summaries.find((summary) => summary.body.chatId === chat.id);
}

/** The summary the chat goes on from: its latest version, unless that was rejected. */
export async function summaryInForce(db: Db, chat: Chat): Promise<Summary | undefined> {
  const summary = await findSummary(db, chat);
  return summary?.status === "active" ? summary : undefined;
}

/** The part of the chat's transcript the model reads: all of it, or what came after the run its summary covers. */
export async function contextMessages(db: Db, chat: Chat): Promise<TranscriptMessage[]> {
  const summary = await summaryInForce(db, chat);
  let afterSeq = 0;
  if (summary) afterSeq = await lastSeqOfRun(db, await readRun(db, summary.body.throughRun));
  return (await readTranscript(db, chat.id, afterSeq)).map((entry) => entry.message);
}

/**
 * How many tokens the model reads: the count the provider gave for its last answer, plus an
 * estimate of what came after it. Give `systemPrompt` for messages read from the transcript, which
 * doesn't hold it; a run's live context holds it as a message.
 */
export function contextTokens(messages: readonly Message[], systemPrompt = ""): number {
  const estimate = estimateContextTokens(messages);
  // With no answer to count from, the instructions haven't been counted either.
  if (estimate.lastUsageIndex === null) return estimate.tokens + estimateTextTokens(systemPrompt);
  return estimate.tokens;
}
