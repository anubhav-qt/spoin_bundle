import type { Db } from "../db/client.ts";
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

/** A chat's instructions, from its role's template, with its summary once it has compacted. */
export async function systemPromptFor(db: Db, prompts: Prompts, chat: Chat): Promise<string> {
  const summary = (await summaryInForce(db, chat)) ?? null;
  return prompts.render(`${chat.role}.njk`, { summary });
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
