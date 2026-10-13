import { randomUUID } from "node:crypto";
import { eq } from "drizzle-orm";
import type { Static, TSchema } from "typebox";
import { generationJob } from "../src/db/schema.ts";
import { type Chat, endRun, openChat, startRun } from "../src/harness/chats.ts";
import type { Author } from "../src/harness/schemas.ts";
import type { HarnessTool, ToolOutput } from "../src/harness/tools.ts";
import { type Client, deps, signedUp } from "./helpers.ts";
import { TEST_MODEL } from "./scripted-model.ts";

/** Calling toad_sage's tools in tests, on names readers asked for. */

const { db } = deps;

export const unique = () => randomUUID().slice(0, 8);

/** Calls a tool as toad_sage would, in a run of its own that ends with the call. */
export async function call<Parameters extends TSchema>(
  tool: HarnessTool<Parameters>,
  params: Static<Parameters>,
): Promise<ToolOutput> {
  const chat: Chat = await openChat(db, "toad_sage");
  const run = await startRun(db, {
    chatId: chat.id,
    model: TEST_MODEL.id,
    triggers: [{ kind: "schedule", schedule: "a test" }],
    systemPrompt: "",
  });
  const author: Author = { kind: "chat", chatId: chat.id, runId: run.id, model: TEST_MODEL.id };
  try {
    return await tool.execute(params, { db, chat, run, author, signal: new AbortController().signal });
  } finally {
    await endRun(db, run.id, { status: "done" });
  }
}

export function text(output: ToolOutput): string {
  if (typeof output.value !== "string") throw new Error("The tool handed back no text.");
  return output.value;
}

/** A name a reader asked for, waiting in the queue. */
export async function requested(
  name: string,
  options: { by?: Client; description?: string; entry?: string } = {},
) {
  const reader = options.by ?? (await signedUp());
  const response = await reader.post("/topics", {
    name,
    description: options.description,
    entry_difficulty: options.entry ?? "beginner",
  });
  if (response.status !== 201) throw new Error(`The request answered ${response.status}.`);
  const topicId: string = response.body.topic.id;
  const [job] = await db.select().from(generationJob).where(eq(generationJob.topicId, topicId));
  if (!job) throw new Error("No job.");
  return { reader, topicId, jobId: job.id };
}

/** An intake as toad_sage writes it. */
export const INTAKE = {
  subject: "Rust, the programming language",
  angle: "plain words for newcomers",
  scope: "topic" as const,
  category: "Programming Languages!",
  sub_category: "Systems",
  card_count: 60,
  brief: "Ownership, borrowing and the type system, without assuming another language.",
};

export function acceptance(jobId: string, name: string) {
  return { job: jobId, name, ...INTAKE };
}
