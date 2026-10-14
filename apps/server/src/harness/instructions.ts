import { and, count, eq } from "drizzle-orm";
import type { Db } from "../db/client.ts";
import { askConversation, card, generationJob, topic, userTopic } from "../db/schema.ts";
import type { Prompts } from "../prompts.ts";
import { type Chat, readChat } from "./chats.ts";
import { summaryInForce } from "./compaction.ts";
import { indiaTime } from "./india-time.ts";
import { withoutRequestTag } from "./prompt-tags.ts";
import { listTopicRecords, readAnyRecord } from "./records.ts";
import { type ActionResult, MapRecord, type RunTrigger } from "./schemas.ts";
import { readActionLog, resultsCutOff } from "./transcript.ts";
import { viewsOf } from "./views.ts";

/**
 * What a chat is told for a run (Trotter's `instructions.ts`), rendered from prompts/ with data
 * read fresh from the store. The system prompt holds the role's standing instructions and the
 * chat's summary, which change seldom; what changes from run to run (the time, what woke the chat)
 * goes in the opening message.
 */

/**
 * A chat's instructions, from its role's template, with its topic if it has one (an AskAI chat's
 * is its thread's, a helper's its main chat's) and its summary once it has compacted. A helper's
 * come from its task's template; one started for its main chat's own work gets its main chat's,
 * told it is a helper.
 */
export async function systemPromptFor(db: Db, prompts: Prompts, chat: Chat): Promise<string> {
  const summary = (await summaryInForce(db, chat)) ?? null;
  if (chat.role === "helper" && chat.parentId) {
    const main = await readChat(db, chat.parentId);
    const topic = await topicOf(db, main);
    if (chat.task === "helper") return prompts.render(`${main.role}.njk`, { summary, topic, helper: true });
    const maps = await mapsOf(db, topic);
    return prompts.render(`helpers/${chat.task}.njk`, { summary, topic, main: main.role, maps });
  }
  return prompts.render(`${chat.role}.njk`, { summary, topic: await topicOf(db, chat) });
}

async function topicOf(
  db: Db,
  chat: Chat,
): Promise<{ id: string; name: string; description: string | null } | null> {
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
    .select({ id: topic.id, name: topic.canonicalName, description: topic.description })
    .from(topic)
    .where(eq(topic.id, topicId));
  return found ?? null;
}

/**
 * A topic's maps, so a writer whose brief names a map by its letter can read it. Without them the
 * first live run's writers guessed record kinds ("misconception_map", "document") to find them.
 */
async function mapsOf(db: Db, found: { id: string } | null) {
  if (!found) return [];
  return viewsOf(db, await listTopicRecords(db, MapRecord, "map", found.id));
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
  const cutOff = (await resultsCutOff(db, chat.id)).map((entry) => ({
    tool: entry.tool,
    arguments: JSON.stringify(entry.arguments),
    result: resultText(entry.result),
  }));
  return prompts.render("run.njk", { now: indiaTime(now), role: chat.role, triggers: woken, cutOff });
}

/** A logged call's result as the chat would have read it. */
function resultText(result: ActionResult): string {
  if (!result.ok) return `It failed: ${result.error}`;
  if (typeof result.value === "string") return result.value;
  return JSON.stringify(result.value);
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
  if (found.description) description = withoutRequestTag(found.description);
  return {
    name: withoutRequestTag(found.name),
    description,
    readers: followers?.readers ?? 0,
  };
}
