import { and, count, eq } from "drizzle-orm";
import type { Db } from "../db/client.ts";
import { askConversation, card, generationJob, topic, userTopic } from "../db/schema.ts";
import type { Prompts } from "../prompts.ts";
import type { Chat } from "./chats.ts";
import { summaryInForce } from "./compaction.ts";
import { indiaTime } from "./india-time.ts";
import { readAnyRecord } from "./records.ts";
import type { RunTrigger } from "./schemas.ts";
import { readActionLog } from "./transcript.ts";
import { viewsOf } from "./views.ts";

/**
 * What a chat is told for a run (Trotter's `instructions.ts`), rendered from prompts/ with data
 * read fresh from the store. The system prompt holds the role's standing instructions and the
 * chat's summary, which change seldom; what changes from run to run (the time, what woke the chat)
 * goes in the opening message.
 */

/**
 * A chat's instructions, from its role's template, with its topic if it has one (an AskAI chat's
 * is its thread's) and its summary once it has compacted.
 */
export async function systemPromptFor(db: Db, prompts: Prompts, chat: Chat): Promise<string> {
  const summary = (await summaryInForce(db, chat)) ?? null;
  return prompts.render(`${chat.role}.njk`, { summary, topic: await topicOf(db, chat) });
}

async function topicOf(db: Db, chat: Chat): Promise<{ name: string; description: string | null } | null> {
  let topicId = chat.topicId;
  if (chat.askConversationId) {
    const [thread] = await db
      .select({ topicId: askConversation.topicId })
      .from(askConversation)
      .where(eq(askConversation.id, chat.askConversationId));
    topicId = thread?.topicId ?? null;
  }
  if (!topicId) return null;
  const [found] = await db
    .select({ name: topic.canonicalName, description: topic.description })
    .from(topic)
    .where(eq(topic.id, topicId));
  return found ?? null;
}

/**
 * The run's opening message: the time in India, and what woke the chat, each record rendered from
 * its own template. An AskAI chat's is only the reader's turn, or its own compaction's.
 */
export async function openingMessageFor(
  db: Db,
  prompts: Prompts,
  chat: Chat,
  triggers: RunTrigger[],
  now: Date,
): Promise<string> {
  const woken = await Promise.all(
    triggers.map(async (trigger) => {
      if (trigger.kind === "record") {
        const [record] = await viewsOf(db, [await readAnyRecord(db, trigger.record)]);
        return { kind: "record", record };
      }
      if (trigger.kind === "job") return { ...trigger, request: await requestOf(db, trigger.job) };
      if (trigger.kind === "reader") return { ...trigger, card: await readerCard(db, trigger.card) };
      if (trigger.kind === "continuation") {
        // What the paused run already stored, so the run carrying it on doesn't do it again.
        const stored = (await readActionLog(db, trigger.run)).flatMap((entry) => entry.recordsWritten);
        return { ...trigger, stored };
      }
      return trigger;
    }),
  );
  return prompts.render("run.njk", { now: indiaTime(now), role: chat.role, triggers: woken });
}

/** The card a reader was on, as they saw it; null when they were on none, or it has gone since. */
async function readerCard(db: Db, id: string | null) {
  if (!id) return null;
  const [found] = await db
    .select({
      title: card.title,
      canonicalTitle: card.canonicalTitle,
      summary: card.summary,
      body: card.body,
    })
    .from(card)
    .where(eq(card.id, id));
  return found ?? null;
}

/**
 * The tag `handovers/job.njk` wraps around a requested name and description, the requester's own
 * words: they can't close it, so they stay inside the part marked as data.
 */
const REQUEST_TAG = /<\s*\/?\s*request\b[^>]*>/gi;

/**
 * The topic name a generate job queued, as it was asked for, and how many readers follow it; null
 * once the job has gone, since the owner can cancel a name before toad_sage gets to it.
 */
async function requestOf(db: Db, jobId: string) {
  const [found] = await db
    .select({ name: topic.canonicalName, description: topic.description, topicId: topic.id })
    .from(generationJob)
    .innerJoin(topic, eq(topic.id, generationJob.topicId))
    .where(eq(generationJob.id, jobId));
  if (!found) return null;
  const [followers] = await db
    .select({ readers: count() })
    .from(userTopic)
    .where(and(eq(userTopic.topicId, found.topicId), eq(userTopic.isCustom, true)));
  let description: string | null = null;
  if (found.description) description = found.description.replace(REQUEST_TAG, "");
  return {
    name: found.name.replace(REQUEST_TAG, ""),
    description,
    readers: followers?.readers ?? 0,
  };
}
