import { chunk, document } from "@spoin/frog/schema";
import type { AskEventOut } from "@spoin/shared";
import { asc, eq } from "drizzle-orm";
import { afterEach, describe, expect, test } from "vitest";
import { noAskChat } from "../src/ask/chat.ts";
import { answer } from "../src/ask/service.ts";
import { ToolError, topicTools } from "../src/ask/tools.ts";
import { askConversation, askMessage, askUsage, card, subtopic, topicEdge } from "../src/db/schema.ts";
import { askChat } from "./ask-chat.ts";
import { useCorpus } from "./corpus.ts";
import { makeTopic } from "./fixtures.ts";
import { type Client, client, deps, env, signedUp, userIdOf } from "./helpers.ts";

/*
 * AskAI (ADR-0077, amended by ADR-0106) through HTTP against the real database, with the
 * chat stood in: the thread, the stream, the sentinel, the daily cap, and the tools.
 */

const { db } = deps;
afterEach(() => askChat.reset());

/** A turn, its SSE body parsed into events; a refused request keeps its JSON body. */
async function ask(c: Client, topicId: string, body: object) {
  const res = await c.raw("POST", `/topics/${topicId}/ask`, JSON.stringify(body), "application/json");
  const text = await res.text();
  if (res.status !== 200)
    return { status: res.status, body: JSON.parse(text), events: [], headers: res.headers };
  const events = text
    .split("\n\n")
    .filter(Boolean)
    .map((block) => {
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      return { event, ...(data ? JSON.parse(data) : {}) } as AskEventOut;
    });
  return { status: 200, body: null, events, headers: res.headers };
}

async function reader() {
  const c = await signedUp();
  const made = await makeTopic();
  return { c, userId: await userIdOf(c), ...made };
}

const today = () => {
  const day = new Date();
  day.setUTCHours(0, 0, 0, 0);
  return day;
};

describe("the thread", () => {
  test("a first turn opens it, streams the answer, and counts", async () => {
    const { c, topic } = await reader();
    expect((await c.get(`/topics/${topic.id}/ask`)).body).toEqual({
      conversation_id: null,
      messages: [],
      spent: 0,
      limit: env.ASK_AI_DAILY_LIMIT,
    });

    const r = await ask(c, topic.id, { question: "What is a layer?" });
    expect(r.headers.get("content-type")).toMatch(/^text\/event-stream/);
    expect(r.headers.get("cache-control")).toBe("no-store");
    expect(r.events).toEqual([
      { event: "delta", text: "You asked: " },
      { event: "delta", text: "What is a layer?" },
      { event: "done" },
    ]);

    const thread = (await c.get(`/topics/${topic.id}/ask`)).body;
    expect(thread.conversation_id).toBe(askChat.turns[0]?.conversationId);
    expect(thread.spent).toBe(1);
    expect(thread.messages).toMatchObject([
      { role: "user", content: "What is a layer?", on_topic: true },
      { role: "assistant", content: "You asked: What is a layer?", on_topic: true },
    ]);
  });

  test("it carries on across turns, and starting over opens a fresh one with a fresh chat", async () => {
    const { c, userId, topic } = await reader();
    await ask(c, topic.id, { question: "One?" });
    await ask(c, topic.id, { question: "Two?" });
    const [first, second] = askChat.turns;
    expect(second?.conversationId).toBe(first?.conversationId);
    expect((await c.get(`/topics/${topic.id}/ask`)).body.messages).toHaveLength(4);

    expect((await c.post(`/topics/${topic.id}/ask/reset`)).status).toBe(204);
    expect((await c.get(`/topics/${topic.id}/ask`)).body).toMatchObject({
      conversation_id: null,
      messages: [],
    });

    await ask(c, topic.id, { question: "Three?" });
    expect(askChat.turns[2]?.conversationId).not.toBe(first?.conversationId);
    const rows = await db
      .select({ status: askConversation.status })
      .from(askConversation)
      .where(eq(askConversation.userId, userId));
    expect(rows.map((r) => r.status).sort()).toEqual(["active", "archived"]);
    // Starting over is not a refund.
    expect((await c.get(`/topics/${topic.id}/ask`)).body.spent).toBe(3);
  });

  test("another reader's thread on the same topic is their own", async () => {
    const { c, topic } = await reader();
    await ask(c, topic.id, { question: "Mine?" });
    const other = await signedUp();
    expect((await other.get(`/topics/${topic.id}/ask`)).body).toMatchObject({
      conversation_id: null,
      spent: 0,
    });
    await ask(other, topic.id, { question: "Theirs?" });
    expect(askChat.turns[1]?.conversationId).not.toBe(askChat.turns[0]?.conversationId);
  });
});

describe("what the chat is handed", () => {
  test("the question, the thread and this topic's tools, and nothing about the reader", async () => {
    const { c, topic } = await reader();
    await ask(c, topic.id, { question: "Why?" });
    const [turn] = askChat.turns;
    expect(Object.keys(turn ?? {}).sort()).toEqual(["card", "conversationId", "question", "tools"]);
    expect((await turn?.tools.outline())?.name).toBe(topic.canonicalName);
  });

  test("the card hint is only ever an active card of this topic, and anything else is no hint", async () => {
    const { c, topic, cards } = await reader();
    const [on, retired] = cards as [(typeof cards)[number], (typeof cards)[number]];
    await db.update(card).set({ status: "retired" }).where(eq(card.id, retired.id));
    const elsewhere = (await makeTopic()).cards[0];

    for (const card_id of [on.id, retired.id, elsewhere?.id, crypto.randomUUID(), null]) {
      expect((await ask(c, topic.id, { question: "This one?", card_id })).events.at(-1)).toEqual({
        event: "done",
      });
    }
    const hints = askChat.turns.map((t) => t.card);
    expect(hints[0]).toMatchObject({ id: on.id, canonicalTitle: on.canonicalTitle, body: on.body });
    expect(hints.slice(1)).toEqual([null, null, null, null]);
  });
});

describe("the refusal", () => {
  test("a reply that starts with OFF_TOPIC is the server's hint, never the model's prose, and it counts", async () => {
    const { c, topic } = await reader();
    askChat.reply = () => [" OFF_", "TOPIC: that is about cooking, which I could explain at length"];
    const r = await ask(c, topic.id, { question: "How do I bake bread?" });
    const hint = `That's outside this topic. It covers: ${topic.canonicalName}.`;
    expect(r.events).toEqual([{ event: "off_topic", hint }]);

    const thread = (await c.get(`/topics/${topic.id}/ask`)).body;
    expect(thread.spent).toBe(1);
    expect(thread.messages).toMatchObject([
      { role: "user", content: "How do I bake bread?", on_topic: true },
      { role: "assistant", content: hint, on_topic: false },
    ]);
  });

  test("the sentinel anywhere but the start is an answer", async () => {
    const { c, topic } = await reader();
    askChat.reply = () => ["Docker", " never says OFF_TOPIC."];
    expect((await ask(c, topic.id, { question: "Q?" })).events).toEqual([
      { event: "delta", text: "Docker" },
      { event: "delta", text: " never says OFF_TOPIC." },
      { event: "done" },
    ]);
  });

  test("a reply too short to tell apart from the sentinel is still an answer", async () => {
    const { c, topic } = await reader();
    askChat.reply = () => ["O", "FF"];
    expect((await ask(c, topic.id, { question: "Q?" })).events).toEqual([
      { event: "delta", text: "OFF" },
      { event: "done" },
    ]);
  });
});

describe("the daily cap", () => {
  test("a reader at the cap gets `limit` and the chat is never asked", async () => {
    const { c, userId, topic } = await reader();
    await db.insert(askUsage).values({ day: today(), userId, questionsSpent: env.ASK_AI_DAILY_LIMIT });
    expect((await ask(c, topic.id, { question: "One more?" })).events).toEqual([{ event: "limit" }]);
    expect(askChat.turns).toHaveLength(0);
    expect((await c.get(`/topics/${topic.id}/ask`)).body).toMatchObject({
      conversation_id: null,
      messages: [],
    });
  });

  test("it resets at midnight UTC", async () => {
    const { c, userId, topic } = await reader();
    const yesterday = new Date(today().getTime() - 86_400_000);
    await db.insert(askUsage).values({ day: yesterday, userId, questionsSpent: env.ASK_AI_DAILY_LIMIT });
    expect((await ask(c, topic.id, { question: "New day?" })).events.at(-1)).toEqual({ event: "done" });
    const rows = await db.select().from(askUsage).where(eq(askUsage.userId, userId));
    expect(rows.find((r) => r.day.getTime() === today().getTime())?.questionsSpent).toBe(1);
  });
});

describe("a failed turn", () => {
  test("keeps the question, ends what streamed with `error`, and costs nothing", async () => {
    const { c, topic } = await reader();
    askChat.reply = function* () {
      yield "Layers are ";
      throw new Error("provider down");
    };
    expect((await ask(c, topic.id, { question: "Layers?" })).events).toEqual([
      { event: "delta", text: "Layers are " },
      { event: "error", cause: "failed" },
    ]);
    const thread = (await c.get(`/topics/${topic.id}/ask`)).body;
    expect(thread.spent).toBe(0);
    expect(thread.messages).toMatchObject([{ role: "user", content: "Layers?" }]);
  });

  test("a chat that says nothing is an `error`, not an empty answer", async () => {
    const { c, topic } = await reader();
    for (const reply of [[], ["  ", "\n"]]) {
      askChat.reply = () => reply;
      expect((await ask(c, topic.id, { question: "Hello?" })).events).toEqual([
        { event: "error", cause: "empty" },
      ]);
    }
    expect((await c.get(`/topics/${topic.id}/ask`)).body.spent).toBe(0);
  });

  test("until the pi chat lands, every turn ends in `error`", async () => {
    const { userId, topic } = await reader();
    const events: AskEventOut[] = [];
    const t = { id: topic.id, name: topic.canonicalName };
    for await (const e of answer({ ...deps, askChat: noAskChat }, userId, t, "Anyone there?", null))
      events.push(e);
    expect(events).toEqual([{ event: "error", cause: "empty" }]);
  });
});

describe("what needs a status is answered before the stream", () => {
  test("signed out, an empty or overlong question, an unknown or malformed topic", async () => {
    const { c, topic } = await reader();
    expect((await ask(client(), topic.id, { question: "Q?" })).status).toBe(401);
    expect(await ask(c, topic.id, { question: "   " })).toMatchObject({
      status: 422,
      body: { detail: "Empty question" },
    });
    expect((await ask(c, topic.id, { question: "" })).status).toBe(422);
    expect((await ask(c, topic.id, { question: "x".repeat(1001) })).status).toBe(422);
    expect(await ask(c, crypto.randomUUID(), { question: "Q?" })).toMatchObject({
      status: 404,
      body: { detail: "Topic not found" },
    });
    expect((await ask(c, "not-a-uuid", { question: "Q?" })).status).toBe(422);
    expect(askChat.turns).toHaveLength(0);
  });
});

describe("the chat's tools read one topic's public material only", () => {
  const toolsFor = (topicId: string) =>
    topicTools(deps, topicId, { searchLimit: env.ASK_AI_CONTEXT_NEIGHBOURS });

  test("the outline lists the subtopics easy to advanced", async () => {
    const { topic, subtopics } = await makeTopic({ subtopicsPerTier: 2 });
    const outline = await toolsFor(topic.id).outline();
    expect(outline).toMatchObject({ name: topic.canonicalName, scope: "topic" });
    expect(outline.subtopics.map((s) => s.id)).toEqual(subtopics.map((s) => s.id));
    expect(outline.subtopics.map((s) => s.difficulty)).toEqual([
      "beginner",
      "beginner",
      "intermediate",
      "intermediate",
      "advanced",
      "advanced",
    ]);
  });

  test("cards and read leave out other topics and retired cards", async () => {
    const { topic, subtopics, cards } = await makeTopic();
    const other = await makeTopic();
    const [s] = subtopics;
    const inS = cards.filter((k) => k.subtopicId === s?.id);
    const [retired, ...live] = inS;
    await db
      .update(card)
      .set({ status: "retired" })
      .where(eq(card.id, retired?.id ?? ""));
    const tools = toolsFor(topic.id);

    expect((await tools.cards(s?.id ?? "")).map((k) => k.id).sort()).toEqual(live.map((k) => k.id).sort());
    // A real subtopic with nothing active is an answer, not an error.
    await db
      .update(card)
      .set({ status: "retired" })
      .where(eq(card.subtopicId, subtopics[1]?.id ?? ""));
    expect(await tools.cards(subtopics[1]?.id ?? "")).toEqual([]);

    expect(await tools.read([live[0]?.id ?? "", live[0]?.id ?? ""])).toEqual({
      cards: [expect.objectContaining({ id: live[0]?.id, body: live[0]?.body })],
    });
    const partial = await tools.read([
      live[0]?.id ?? "",
      retired?.id ?? "",
      other.cards[0]?.id ?? "",
      "card-7",
    ]);
    expect(partial).toEqual({
      cards: [expect.objectContaining({ id: live[0]?.id })],
      note: `Left out, not active cards in this topic: "${retired?.id}", "${other.cards[0]?.id}", "card-7".`,
    });
  });

  test("a wrong call is one short line saying how to call it right", async () => {
    const { topic } = await makeTopic();
    const other = await makeTopic();
    const tools = toolsFor(topic.id);
    const otherSubtopic = other.subtopics[0]?.id ?? "";
    const runaway = "x".repeat(5000);

    await expect(tools.cards("subtopic-1")).rejects.toThrow(
      new ToolError(`"subtopic-1" is not a subtopic id. outline() lists this topic's subtopics.`),
    );
    await expect(tools.cards(otherSubtopic)).rejects.toThrow(
      new ToolError(`No subtopic ${otherSubtopic} in this topic. outline() lists them.`),
    );
    await expect(tools.read([])).rejects.toThrow(
      new ToolError("Give at least one card id. search() and cards() list them."),
    );
    await expect(tools.read(["a", "b", "c", "d", "e"])).rejects.toThrow(
      new ToolError(
        `No active card in this topic has id "a", "b", "c" and 2 more. search() and cards() list them.`,
      ),
    );
    await expect(tools.search("  ")).rejects.toThrow(
      new ToolError("Give a query: what to look for, in words."),
    );
    await expect(toolsFor(crypto.randomUUID()).outline()).rejects.toThrow(
      new ToolError("This topic no longer exists."),
    );

    // Whatever the model sends, the error stays one short line.
    for (const call of [tools.cards(runaway), tools.read([runaway, runaway.repeat(2)])]) {
      const err = await call.catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ToolError);
      expect((err as Error).message.length).toBeLessThan(200);
      expect((err as Error).message).not.toContain("\n");
    }
  });

  test("search ranks this topic's active cards by meaning, in the embedder's own space", async () => {
    const { topic, cards } = await makeTopic();
    const other = await makeTopic();
    const embed = async (ids: string[], body: (i: number) => string, model = deps.embedder.modelName) => {
      for (const [i, id] of ids.entries()) {
        const text = body(i);
        const [v] = await deps.embedder.embedPassage([text]);
        await db
          .update(card)
          .set({ body: text, contentEmbedding: v, embeddingModel: model })
          .where(eq(card.id, id));
      }
    };
    const [best, retired, foreign, ...rest] = cards.map((k) => k.id);
    await embed(rest, (i) => `Filler card ${i} about networking and volumes.`);
    await embed([best ?? ""], () => "Docker layers are cached by content hash.");
    await embed([retired ?? ""], () => "Docker layers are cached by content hash, retired.");
    await db
      .update(card)
      .set({ status: "retired" })
      .where(eq(card.id, retired ?? ""));
    // The same words, stamped by another model: its vector is in another space.
    await embed([foreign ?? ""], () => "Docker layers are cached by content hash.", "qwen3-other");
    await embed([other.cards[0]?.id ?? ""], () => "Docker layers are cached by content hash.");

    const found = await toolsFor(topic.id).search("how are docker layers cached");
    expect(found).toHaveLength(env.ASK_AI_CONTEXT_NEIGHBOURS);
    expect(found[0]?.id).toBe(best);
    const ids = found.map((k) => k.id);
    for (const excluded of [retired, foreign, other.cards[0]?.id]) expect(ids).not.toContain(excluded);
  });
});

describe("the corpus tool reads what this topic and its related topics were written from", () => {
  const corpus = useCorpus();
  const toolsFor = (topicId: string) =>
    topicTools(deps, topicId, { searchLimit: env.ASK_AI_CONTEXT_NEIGHBOURS });

  /** One document per path, a section per heading, embedded as frog's ingester would. */
  async function deliver(docs: Record<string, Record<string, string>>) {
    for (const [i, [sourcePath, sections]] of Object.entries(docs).entries()) {
      const [d] = await corpus
        .insert(document)
        .values({
          title: sourcePath,
          source: `https://example.invalid/${sourcePath}`,
          sourcePath,
          kind: "topic_source",
          category: "computer science",
          scope: "topic",
          contentHash: String(i).padStart(64, "0"),
          ingestedAt: new Date(),
        })
        .returning();
      for (const [ordinal, [heading, body]] of Object.entries(sections).entries()) {
        const text = `${sourcePath} — ${heading}\n\n${body}`;
        const [v] = await deps.embedder.embedPassage([text]);
        await corpus.insert(chunk).values({
          documentId: (d as { id: string }).id,
          ordinal,
          text,
          heading,
          embedding: v as number[],
          embeddingModel: deps.embedder.modelName,
          topicTags: [],
        });
      }
    }
  }

  async function grounded(refs: string[]) {
    const made = await makeTopic();
    await db
      .update(subtopic)
      .set({ groundingRefs: refs })
      .where(eq(subtopic.id, made.subtopics[0]?.id ?? ""));
    return made.topic;
  }

  test("it ranks the grounding of this topic and of topics joined to it either way", async () => {
    await deliver({
      "a.md": {
        "Docker layers": "Docker layers are cached by content hash.",
        Volumes: "Volumes outlive containers.",
      },
      "b.md": { "Build cache": "A build reuses cached layers until a step changes." },
      "c.md": { Registries: "A registry stores images by digest." },
      "d.md": { "Docker layers": "Docker layers are cached by content hash." },
    });
    const own = await grounded(["a.md#Docker layers"]);
    const before = await grounded(["b.md#Build cache"]);
    const after = await grounded(["c.md#Registries"]);
    await grounded(["d.md#Docker layers"]);
    await db.insert(topicEdge).values([
      { fromTopicId: before.id, toTopicId: own.id },
      { fromTopicId: own.id, toTopicId: after.id },
    ]);

    const found = await toolsFor(own.id).passages?.("how are docker layers cached");
    expect(found?.[0]).toEqual({
      text: "a.md — Docker layers\n\nDocker layers are cached by content hash.",
      source: "https://example.invalid/a.md",
    });
    // Ungrounded sections and an unrelated topic's are out, however near the query.
    expect(found?.map((p) => p.source).sort()).toEqual(
      ["a.md", "b.md", "c.md"].map((p) => `https://example.invalid/${p}`),
    );
  });

  test("no grounding, or grounding that no longer resolves, finds nothing", async () => {
    await deliver({ "a.md": { "Docker layers": "Docker layers are cached by content hash." } });
    const bare = await makeTopic();
    expect(await toolsFor(bare.topic.id).passages?.("docker layers")).toEqual([]);
    const stale = await grounded(["a.md#Renamed heading"]);
    expect(await toolsFor(stale.id).passages?.("docker layers")).toEqual([]);
  });

  test("a wrong call is one short line, and no corpus means no tool", async () => {
    const { topic } = await makeTopic();
    await expect(toolsFor(topic.id).passages?.(" ")).rejects.toThrow(
      new ToolError("Give a query: what to look for, in words."),
    );
    expect(topicTools({ ...deps, universe: null }, topic.id, { searchLimit: 4 }).passages).toBeUndefined();
  });
});

test("an archived thread keeps its messages", async () => {
  const { c, topic } = await reader();
  await ask(c, topic.id, { question: "Keep me?" });
  const id = askChat.turns[0]?.conversationId ?? "";
  await c.post(`/topics/${topic.id}/ask/reset`);
  const kept = await db
    .select()
    .from(askMessage)
    .where(eq(askMessage.conversationId, id))
    .orderBy(asc(askMessage.createdAt));
  expect(kept.map((m) => m.role)).toEqual(["user", "assistant"]);
});
