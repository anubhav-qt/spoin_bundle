import type { AskConversationOut, AskEventOut } from "@spoin/shared";
import { and, asc, eq, sql } from "drizzle-orm";
import type { Deps } from "../context.ts";
import type { Db } from "../db/client.ts";
import { askConversation, askMessage, askUsage, topic } from "../db/schema.ts";
import { notFound } from "../lib/errors.ts";
import { iso } from "../lib/wire.ts";
import { log } from "../log.ts";
import { activeCards, topicTools } from "./tools.ts";

/*
 * AskAI (ADR-0077, amended by ADR-0106): one persistent thread per reader per topic,
 * answered by a chat of its own. The server keeps the thread the reader sees, the daily
 * cap and the refusal; the chat keeps its memory and reads the topic through tools.
 */

type Ctx = Pick<Deps, "db" | "universe" | "env" | "embedder" | "askChat">;

const OFF_TOPIC = "OFF_TOPIC";

const utcDay = () => {
  const day = new Date();
  day.setUTCHours(0, 0, 0, 0);
  return day;
};

async function spentToday(db: Db, userId: string): Promise<number> {
  const [row] = await db
    .select({ n: askUsage.questionsSpent })
    .from(askUsage)
    .where(and(eq(askUsage.day, utcDay()), eq(askUsage.userId, userId)));
  return row?.n ?? 0;
}

async function activeConversation(db: Db, userId: string, topicId: string): Promise<string | null> {
  const [row] = await db
    .select({ id: askConversation.id })
    .from(askConversation)
    .where(
      and(
        eq(askConversation.userId, userId),
        eq(askConversation.topicId, topicId),
        eq(askConversation.status, "active"),
      ),
    );
  return row?.id ?? null;
}

async function openConversation(db: Db, userId: string, topicId: string): Promise<string> {
  const existing = await activeConversation(db, userId, topicId);
  if (existing) return existing;
  const [made] = await db
    .insert(askConversation)
    .values({ userId, topicId })
    .onConflictDoNothing()
    .returning({ id: askConversation.id });
  if (made) return made.id;
  // A concurrent first turn won the one-active-thread index; this turn joins its thread.
  const won = await activeConversation(db, userId, topicId);
  if (!won) throw new Error("the active ask conversation vanished");
  return won;
}

// -- reads ----------------------------------------------------------------------

export async function conversation(ctx: Ctx, userId: string, topicId: string): Promise<AskConversationOut> {
  const { db } = ctx;
  const id = await activeConversation(db, userId, topicId);
  const messages = id
    ? await db
        .select({
          role: askMessage.role,
          content: askMessage.content,
          onTopic: askMessage.onTopic,
          createdAt: askMessage.createdAt,
        })
        .from(askMessage)
        .where(eq(askMessage.conversationId, id))
        .orderBy(asc(askMessage.createdAt))
    : [];
  return {
    conversation_id: id,
    messages: messages.map((m) => ({
      role: m.role,
      content: m.content,
      on_topic: m.onTopic,
      created_at: iso(m.createdAt),
    })),
    spent: await spentToday(db, userId),
    limit: ctx.env.ASK_AI_DAILY_LIMIT,
  };
}

/** The topic a turn is about; checked before the stream opens, so a miss is a plain 404. */
export async function askedTopic(db: Db, topicId: string): Promise<{ id: string; name: string }> {
  const [t] = await db
    .select({ id: topic.id, name: topic.canonicalName })
    .from(topic)
    .where(eq(topic.id, topicId));
  if (!t) throw notFound("Topic");
  return t;
}

// -- writes ---------------------------------------------------------------------

/** "Start over": the thread is archived and the next turn opens a fresh one, with a fresh chat. */
export async function reset(db: Db, userId: string, topicId: string): Promise<void> {
  await db
    .update(askConversation)
    .set({ status: "archived" })
    .where(
      and(
        eq(askConversation.userId, userId),
        eq(askConversation.topicId, topicId),
        eq(askConversation.status, "active"),
      ),
    );
}

/**
 * Whether the leading text so far is the chat's refusal, an answer, or too short to tell.
 * Anything that starts with the sentinel is a refusal, however the chat chunked it.
 */
function verdict(text: string): "refused" | "answer" | "undecided" {
  const lead = text.trimStart();
  if (lead.length < OFF_TOPIC.length) return OFF_TOPIC.startsWith(lead) ? "undecided" : "answer";
  return lead.startsWith(OFF_TOPIC) ? "refused" : "answer";
}

/**
 * The reader's reply, written after the turn: the answer, or for a refusal the server's
 * own hint, never the model's prose. Either way the turn reached the model, so it counts
 * against the day's cap; a failed turn does not.
 */
async function record(db: Db, userId: string, conversationId: string, content: string, onTopic: boolean) {
  const now = new Date();
  await db.transaction(async (tx) => {
    await tx.insert(askMessage).values({ conversationId, role: "assistant", content, onTopic });
    await tx
      .update(askConversation)
      .set({ lastMessageAt: now })
      .where(eq(askConversation.id, conversationId));
    await tx
      .insert(askUsage)
      .values({ day: utcDay(), userId, questionsSpent: 1 })
      .onConflictDoUpdate({
        target: [askUsage.day, askUsage.userId],
        set: { questionsSpent: sql`${askUsage.questionsSpent} + 1` },
      });
  });
}

/**
 * One turn, as the events the route streams. The chat's leading text is held back until
 * it cannot be the `OFF_TOPIC` sentinel, so a refusal is never shown as prose.
 */
export async function* answer(
  ctx: Ctx,
  userId: string,
  t: { id: string; name: string },
  question: string,
  cardId: string | null | undefined,
): AsyncGenerator<AskEventOut> {
  const { db, env } = ctx;
  if ((await spentToday(db, userId)) >= env.ASK_AI_DAILY_LIMIT) {
    yield { event: "limit" };
    return;
  }

  const conversationId = await openConversation(db, userId, t.id);
  const tools = topicTools(ctx, t.id, { searchLimit: env.ASK_AI_CONTEXT_NEIGHBOURS });
  // Any card that is not an active one of this topic is no hint at all.
  const [card] = cardId ? await activeCards(db, t.id, [cardId]) : [];
  // Written first, so the question survives a stream that dies mid-answer.
  await db.insert(askMessage).values({ conversationId, role: "user", content: question });

  let lead = "";
  let decided = false;
  let refused = false;
  const parts: string[] = [];
  try {
    for await (const chunk of ctx.askChat.turn({ conversationId, question, card: card ?? null, tools })) {
      let text = chunk;
      if (!decided) {
        lead += chunk;
        const v = verdict(lead);
        if (v === "undecided") continue;
        if (v === "refused") {
          refused = true;
          break;
        }
        decided = true;
        text = lead;
      }
      parts.push(text);
      yield { event: "delta", text };
    }
  } catch (err) {
    log.warn({ err, conversationId }, "ask turn failed");
    yield { event: "error", cause: "failed" };
    return;
  }

  if (refused) {
    const hint = `That's outside this topic. It covers: ${t.name}.`;
    await record(db, userId, conversationId, hint, false);
    yield { event: "off_topic", hint };
    return;
  }
  // A stream that ended before it could be told apart was too short to be the sentinel.
  if (!decided && lead.trim()) {
    parts.push(lead);
    yield { event: "delta", text: lead };
  }
  const text = parts.join("").trim();
  if (!text) {
    yield { event: "error", cause: "empty" };
    return;
  }
  await record(db, userId, conversationId, text, true);
  yield { event: "done" };
}
