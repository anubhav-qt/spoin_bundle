import type { CardFull, TopicTools } from "./tools.ts";

/**
 * One reader's turn in their AskAI thread on a topic. It carries no user id and no
 * database handle: everything the chat can read comes through `tools`, which hold
 * only the topic's public material, so a successful injection buys an off-topic
 * answer and never data (ADR-0077's invariant).
 */
export interface AskTurn {
  /**
   * The thread, one per reader per topic. The chat keeps its own transcript and
   * compaction under this id, so the server never resends the thread; after a reset
   * the id is new and so is the chat.
   */
  conversationId: string;
  /** Untrusted: the chat presents it as the reader's message, never as instructions. */
  question: string;
  /** The card the reader is on, already checked to be an active card of this topic. */
  card: CardFull | null;
  /** A `ToolError`'s message goes back to the chat as that call's result, so it can call again right. */
  tools: TopicTools;
}

/**
 * AskAI's chat (ADR-0106 amending ADR-0077): a harness chat per reader per topic
 * (`harness-chat.ts`). It answers from the tools and the thread so far, or replies with
 * exactly `OFF_TOPIC`, which the server turns into a refusal of its own wording.
 */
export interface AskChat {
  /**
   * The answer, streamed. Single-item by design, ADR-0077's one sanctioned exception to
   * ADR-0005: a turn is one reader at their own time, with nothing to batch.
   */
  turn(turn: AskTurn): AsyncIterable<string>;
}

/** For a process with neither a proxy nor a NIM key: nothing answers, and every turn ends in `error`. */
export const noAskChat: AskChat = {
  async *turn() {},
};
