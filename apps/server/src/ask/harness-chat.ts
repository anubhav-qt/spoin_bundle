import type { AgentEvent, StreamFn, ThinkingLevel } from "@spoin/pi-agent";
import { type Api, type AssistantMessage, type JsonValue, type Model, Type } from "@spoin/pi-ai";
import type { Static, TSchema } from "typebox";
import type { Db } from "../db/client.ts";
import { openAskChat, type Run } from "../harness/chats.ts";
import type { CompactionSettings } from "../harness/compaction.ts";
import { CLOSED, Text } from "../harness/schemas.ts";
import type { HarnessTool } from "../harness/tools.ts";
import { wakeChat } from "../harness/wake-chat.ts";
import { log } from "../log.ts";
import type { Prompts } from "../prompts.ts";
import type { AskChat, AskTurn } from "./chat.ts";
import { ToolError, type TopicTools } from "./tools.ts";

/*
 * AskAI's chat on the harness (task 0045): each reader's thread is a harness chat, `ask_ai`, and
 * each turn is a run of it, so it keeps Trotter's transcript, action log and compaction like any
 * chat. Everything it writes streams to the reader as it's written, a paragraph per message, its
 * compaction runs' excepted. The chat reads the topic only through the turn's tools.
 */

export interface HarnessAskChatOptions {
  db: Db;
  prompts: Prompts;
  /** The model a turn runs on: Gemini, or NIM's top model in a process with no proxy. */
  model: () => Promise<Model<Api>>;
  thinkingLevel: ThinkingLevel;
  apiKey: string;
  /** How the model is called, given each run (`geminiThenNim`). Tests pass a stand-in. */
  streamFn: (run: Run) => StreamFn;
  /** When the chat compacts; the defaults unless given. */
  compaction?: CompactionSettings;
}

export function harnessAskChat(options: HarnessAskChatOptions): AskChat {
  return { turn: (turn) => answer(options, turn) };
}

/**
 * One turn, as the text the chat writes. A reader who leaves, or a turn the server refuses on its
 * first words, stops the run. A turn whose run didn't finish throws, so the server says it failed.
 */
async function* answer(options: HarnessAskChatOptions, turn: AskTurn): AsyncGenerator<string> {
  const { db, prompts } = options;
  const chat = await openAskChat(db, turn.conversationId);
  const stop = new AbortController();
  const written: string[] = [];
  let heard: (() => void) | undefined;
  let wroteAny = false;
  // How much of the message being written has been passed on.
  let passedOn = 0;

  const pass = (text: string) => {
    if (!text) return;
    written.push(passedOn === 0 && wroteAny ? `\n\n${text}` : text);
    passedOn += text.length;
    wroteAny = true;
    heard?.();
  };
  const onEvent = (event: AgentEvent, run: Run) => {
    if (run.triggers[0]?.kind === "compaction") return;
    if (event.type === "message_start" && event.message.role === "assistant") passedOn = 0;
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      pass(event.assistantMessageEvent.delta);
    }
    // An answer that came whole, as NIM's do, has had no deltas: what's left of it goes now.
    if (event.type === "message_end" && event.message.role === "assistant") {
      pass(textOf(event.message).slice(passedOn));
    }
  };

  let ended = false;
  let failure: unknown;
  let runs: Run[] = [];
  const model = await options.model();
  const woken = wakeChat({
    db,
    prompts,
    chat,
    model,
    thinkingLevel: options.thinkingLevel,
    triggers: [{ kind: "reader", question: turn.question, card: turn.card?.id ?? null }],
    apiKey: options.apiKey,
    tools: askTools(turn.tools, prompts),
    // It stores nothing but its summary.
    compactionTools: [],
    compaction: options.compaction,
    streamFn: options.streamFn,
    signal: stop.signal,
    onEvent,
  }).then(
    (all) => {
      runs = all;
    },
    (error: unknown) => {
      failure = error;
    },
  );
  void woken.finally(() => {
    ended = true;
    heard?.();
  });

  try {
    while (true) {
      const next = written.shift();
      if (next !== undefined) {
        yield next;
        continue;
      }
      if (ended) break;
      await new Promise<void>((resolve) => {
        heard = resolve;
      });
      heard = undefined;
    }
  } finally {
    if (!ended) {
      stop.abort();
      await woken;
    }
  }

  if (failure) throw failure;
  const last = runs.at(-1);
  if (last?.status !== "done") {
    throw new Error(last?.error ?? `The turn's run ended ${last?.status ?? "before it started"}.`);
  }
}

function textOf(message: AssistantMessage): string {
  return message.content.map((block) => (block.type === "text" ? block.text : "")).join("");
}

/** The tools' results are plain rows and strings. */
const asJson = (value: unknown) => value as JsonValue;

/**
 * The turn's topic tools as harness tools, all reads. A `ToolError` reaches the chat as it is; any
 * other failure is logged, and the chat gets one short line.
 */
function askTools(tools: TopicTools, prompts: Prompts): HarnessTool[] {
  const read = <Parameters extends TSchema>(
    name: string,
    label: string,
    parameters: Parameters,
    call: (params: Static<Parameters>) => Promise<unknown>,
  ): HarnessTool<Parameters> => ({
    name,
    label,
    description: prompts.render(`tools/${name}.njk`, {}),
    parameters,
    kind: "read",
    async execute(params) {
      try {
        return { value: asJson(await call(params)), dataSeen: [], recordsWritten: [] };
      } catch (error) {
        if (error instanceof ToolError) throw error;
        log.error({ err: error, tool: name }, "an AskAI tool failed");
        throw new Error(`${name} failed. Call it again, or answer from what you have.`);
      }
    },
  });
  const query = Type.Object({ query: Text }, CLOSED);
  const all: HarnessTool[] = [
    read("outline", "Outline", Type.Object({}, CLOSED), () => tools.outline()),
    read("cards", "Cards", Type.Object({ subtopic_id: Text }, CLOSED), (params) =>
      tools.cards(params.subtopic_id),
    ),
    read("read", "Read cards", Type.Object({ card_ids: Type.Array(Text) }, CLOSED), (params) =>
      tools.read(params.card_ids),
    ),
    read("search", "Search cards", query, (params) => tools.search(params.query)),
  ];
  const { passages } = tools;
  if (passages) {
    all.push(read("passages", "Search sources", query, (params) => passages.call(tools, params.query)));
  }
  return all;
}
