import { randomBytes } from "node:crypto";
import { normalizeTopicText } from "@spoin/frog/normalize";
import type { TopicBatchItemOut, TopicOut, TopicRequestIn } from "@spoin/shared";
import { eq } from "drizzle-orm";
import type { Deps } from "../context.ts";
import type { Tx } from "../db/client.ts";
import { feedPlan, generationJob, topic, topicAlias } from "../db/schema.ts";
import { HttpError } from "../lib/errors.ts";
import { followTopic, pickHues } from "./service.ts";
import { slugify } from "./slug.ts";

/*
 * A user typing a topic by name. No model is called here: the request path only does
 * what code can decide. An exact alias match subscribes at once; a miss becomes a
 * pending topic, the requester's custom subscription and a generate job, and toad_sage
 * takes it from there: it validates the name, merges it into an existing topic or
 * rejects it with a reason the user sees, or hands it to the curriculum tadpole.
 * A pending topic has no subtopics, so it stays out of everyone else's lists until it
 * is live (ADR-0053).
 */

type Ctx = Pick<Deps, "db" | "env" | "embedder">;
type Topic = typeof topic.$inferSelect;
type Request = TopicRequestIn;

/** A real user waiting outranks speculative work. */
const USER_REQUEST_PRIORITY = 10;

/** How a new name is queued: its job's priority, and who decided its alias. */
export type Queueing = { priority: number; decidedBy: string };

/** The word-count rule is a constraint, so code enforces it; null when the name passes. */
export function nameProblem(ctx: Pick<Deps, "env">, name: string): string | null {
  if (!name) return "Topic name is required";
  const max = ctx.env.CUSTOM_TOPIC_MAX_WORDS;
  if (name.split(/\s+/u).length > max) return `Keep it short: ${max} words or fewer`;
  return null;
}

async function byAlias(tx: Tx, normalized: string): Promise<Topic | null> {
  const [hit] = await tx
    .select({ topic })
    .from(topicAlias)
    .innerJoin(topic, eq(topic.id, topicAlias.topicId))
    .where(eq(topicAlias.normalizedText, normalized));
  return hit?.topic ?? null;
}

/**
 * The topic this name resolves to, minting a pending one on a miss. Safe against the
 * same new name arriving twice at once: the loser of the alias insert adopts the
 * winner's topic and drops its own.
 */
export async function resolve(
  tx: Tx,
  name: string,
  description: string,
  queueing: Queueing,
): Promise<{ topic: Topic; created: boolean }> {
  const normalized = normalizeTopicText(name);
  const known = await byAlias(tx, normalized);
  if (known) return { topic: known, created: false };

  const base = slugify(name);
  const insert = (slug: string) =>
    tx
      .insert(topic)
      .values({ slug, canonicalName: name, description: description || null })
      .onConflictDoNothing({ target: topic.slug })
      .returning();
  let [minted] = await insert(base);
  // A taken slug belongs to a different name (the alias missed), so this one gets a suffix.
  if (!minted) [minted] = await insert(`${base}-${randomBytes(3).toString("hex")}`);
  if (!minted) throw new Error("topic insert returned nothing");

  const [alias] = await tx
    .insert(topicAlias)
    .values({ normalizedText: normalized, rawText: name, topicId: minted.id, decidedBy: queueing.decidedBy })
    .onConflictDoNothing({ target: topicAlias.normalizedText })
    .returning();
  if (!alias) {
    await tx.delete(topic).where(eq(topic.id, minted.id));
    const winner = await byAlias(tx, normalized);
    if (!winner) throw new Error("alias conflict without an alias");
    return { topic: winner, created: false };
  }

  await tx
    .insert(generationJob)
    .values({
      topicId: minted.id,
      kind: "generate",
      status: "pending",
      priority: queueing.priority,
      progress: { topic_name: name },
    })
    .onConflictDoNothing();
  return { topic: minted, created: true };
}

type Outcome = TopicBatchItemOut;

/** One transaction for every row; each row reports its own outcome. */
async function requestAll(ctx: Ctx, userId: string, items: Request[], guest: boolean): Promise<Outcome[]> {
  if (guest) throw new HttpError(403, "Sign up to request a custom topic");
  const names = items.map((i) => i.name.trim());

  return ctx.db.transaction(async (tx) => {
    const out: Outcome[] = [];
    let followedAny = false;
    for (const [index, item] of items.entries()) {
      const name = names[index] as string;
      const problem = nameProblem(ctx, name);
      if (problem) {
        out.push({ request_index: index, status: "rejected", topic: null, detail: problem });
        continue;
      }
      const { topic: t, created } = await resolve(tx, name, item.description?.trim() ?? "", {
        priority: USER_REQUEST_PRIORITY,
        decidedBy: "request",
      });
      const [hue = null] = await pickHues(tx, ctx.embedder, userId, [t]);
      // The user's own words become their label for it, whichever topic it resolved to.
      const followed: TopicOut | null = await followTopic(tx, userId, t, {
        displayName: name,
        isCustom: true,
        entry: item.entry_difficulty,
        hue,
      });
      if (!followed) {
        out.push({ request_index: index, status: "already_subscribed", topic: null, detail: null });
        continue;
      }
      followedAny = true;
      out.push({
        request_index: index,
        status: created ? "generating" : "subscribed",
        topic: followed,
        detail: null,
      });
    }
    if (followedAny) await tx.delete(feedPlan).where(eq(feedPlan.userId, userId));
    return out;
  });
}

export async function requestTopic(
  ctx: Ctx,
  userId: string,
  item: Request,
  guest: boolean,
): Promise<{ topic: TopicOut; status: "generating" | "subscribed" }> {
  const [o] = await requestAll(ctx, userId, [item], guest);
  if (!o) throw new Error("no outcome for a single request");
  if (o.status === "rejected") throw new HttpError(422, o.detail ?? "Invalid topic name");
  if (o.status === "already_subscribed" || !o.topic) throw new HttpError(409, "Already subscribed");
  return { topic: o.topic, status: o.status };
}

export const requestTopics = (ctx: Ctx, userId: string, items: Request[], guest: boolean) =>
  requestAll(ctx, userId, items, guest);
