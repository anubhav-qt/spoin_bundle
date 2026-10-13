import { RUNNING_ROLES, TOPIC_CHAT_ROLES } from "@spoin/shared/enums";
import { Type } from "typebox";
import type { Db } from "../db/client.ts";
import type { Prompts } from "../prompts.ts";
import { type Chat, findTopicChat, openChat } from "./chats.ts";
import { recordsStored } from "./outputs.ts";
import { createRecord, readLatestRecord, refOf } from "./records.ts";
import { AnswerRecord, type ChatAddress, CLOSED, Id, QuestionRecord, Text } from "./schemas.ts";
import { type HarnessTool, ToolError } from "./tools.ts";

/**
 * Passing a question between chats (Trotter's `ask` and `answer`, task 0045). The question wakes
 * the chat asked and each answer wakes the chat that asked (routing.ts), so a chat that doesn't
 * know yet answers so, and answers again once it does.
 */

type AskedRole = (typeof RUNNING_ROLES)[number];
type TopicRole = Extract<AskedRole, (typeof TOPIC_CHAT_ROLES)[number]>;

const AskParameters = Type.Object(
  {
    to: Type.Enum([...RUNNING_ROLES]),
    topic: Type.Optional(
      Type.String({
        format: "uuid",
        description: "The topic's id, to ask its tadpole or designer_toad",
      }),
    ),
    question: Text,
    reasoning: Text,
  },
  CLOSED,
);

export function askTool(prompts: Prompts): HarnessTool<typeof AskParameters> {
  return {
    name: "ask",
    label: "Ask another chat",
    description: prompts.render("tools/ask.njk", {}),
    parameters: AskParameters,
    kind: "change",
    async execute(params, context) {
      const { db, chat, author } = context;
      const asked = await askedChat(db, params.to, params.topic);
      if (asked.chat.id === chat.id) throw new ToolError("That is you: ask another chat.");
      const question = await createRecord(db, QuestionRecord, {
        kind: "question",
        author,
        body: { to: asked.address, question: params.question, reasoning: params.reasoning },
      });
      return recordsStored(db, prompts, [question]);
    },
  };
}

/** A topic's chat only once it has started, so a question never starts one; the others are made on first need. */
async function askedChat(
  db: Db,
  to: AskedRole,
  topic: string | undefined,
): Promise<{ chat: Chat; address: ChatAddress }> {
  if (isTopicRole(to)) {
    if (!topic) throw new ToolError(`Asking a ${to} takes its topic's id as topic.`);
    const chat = await findTopicChat(db, to, topic);
    if (!chat) throw new ToolError(`The ${to} of topic ${topic} hasn't started, so it can't be asked yet.`);
    return { chat, address: { role: to, topic } };
  }
  if (topic) throw new ToolError(`There is one ${to} for every topic: leave topic out.`);
  return { chat: await openChat(db, to), address: { role: to } };
}

function isTopicRole(role: AskedRole): role is TopicRole {
  return (TOPIC_CHAT_ROLES as readonly string[]).includes(role);
}

const AnswerParameters = Type.Object({ question: Id, answer: Text }, CLOSED);

export function answerTool(prompts: Prompts): HarnessTool<typeof AnswerParameters> {
  return {
    name: "answer",
    label: "Answer a question",
    description: prompts.render("tools/answer.njk", {}),
    parameters: AnswerParameters,
    kind: "change",
    async execute(params, context) {
      const { db, chat, author } = context;
      const question = await readLatestRecord(db, QuestionRecord, "question", params.question);
      if (!isAskedOf(question.body.to, chat)) {
        throw new ToolError(
          `Question ${question.id} was asked of another chat: you can answer only the questions asked of you.`,
        );
      }
      const answer = await createRecord(db, AnswerRecord, {
        kind: "answer",
        author,
        body: { question: refOf(question), answer: params.answer },
      });
      return recordsStored(db, prompts, [answer]);
    },
  };
}

function isAskedOf(to: ChatAddress, chat: Chat): boolean {
  let topic: string | null = null;
  if ("topic" in to) topic = to.topic;
  return to.role === chat.role && topic === chat.topicId;
}
