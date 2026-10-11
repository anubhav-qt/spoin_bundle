import type { AskChat, AskTurn } from "../src/ask/chat.ts";

type Reply = (turn: AskTurn) => Iterable<string>;

/**
 * The chat, stood in for. By default it answers in two chunks, the second the question
 * itself. A test that needs it to refuse, fail or say nothing sets `reply`; every turn
 * it is handed lands in `turns`, and `reset` puts both back.
 */
const standIn: Reply = (turn) => ["You asked: ", turn.question];

export const askChat: AskChat & { reply: Reply; turns: AskTurn[]; reset: () => void } = {
  reply: standIn,
  turns: [],
  reset() {
    this.reply = standIn;
    this.turns = [];
  },
  async *turn(turn) {
    this.turns.push(turn);
    yield* this.reply(turn);
  },
};
