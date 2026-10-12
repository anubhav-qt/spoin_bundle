import { eq } from "drizzle-orm";
import type { Db } from "../db/client.ts";
import { askConversation, card, topic } from "../db/schema.ts";
import type { Prompts } from "../prompts.ts";
import type { Chat } from "./chats.ts";
import { summaryInForce } from "./compaction.ts";
import { indiaTime } from "./india-time.ts";
import { readAnyRecord } from "./records.ts";
import type { RunTrigger } from "./schemas.ts";
import { readActionLog } from "./transcript.ts";

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

/** The run's opening message: the time in India, and what woke the chat, each record rendered from its own template. */
export async function openingMessageFor(
  db: Db,
  prompts: Prompts,
  triggers: RunTrigger[],
  now: Date,
): Promise<string> {
  const woken = await Promise.all(
    triggers.map(async (trigger) => {
      if (trigger.kind === "record")
        return { kind: "record", record: await readAnyRecord(db, trigger.record) };
      if (trigger.kind === "reader") return { ...trigger, card: await readerCard(db, trigger.card) };
      if (trigger.kind === "continuation") {
        // What the paused run already stored, so the run carrying it on doesn't do it again.
        const stored = (await readActionLog(db, trigger.run)).flatMap((entry) => entry.recordsWritten);
        return { ...trigger, stored };
      }
      return trigger;
    }),
  );
  return prompts.render("run.njk", { now: indiaTime(now), triggers: woken });
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
