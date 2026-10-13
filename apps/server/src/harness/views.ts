import type { Db, Tx } from "../db/client.ts";
import { type Chat, readChat } from "./chats.ts";
import { indiaTime } from "./india-time.ts";
import { readAnyRecord, readRecord } from "./records.ts";
import { type AnyRecord, type Author, QuestionRecord } from "./schemas.ts";

/**
 * Records as their templates show them: each with what the templates need that the record doesn't
 * hold. Who wrote this version, and who wrote the first, which stays a question's asker or an
 * answer's answerer after another chat changes it; both by role and topic rather than a chat id,
 * which says nothing to a model. When, in India time like the run's opening message. And for an
 * answer, the question it answers, so a chat woken by the answer needn't read the question first.
 */

type Conn = Db | Tx;

interface Address {
  role: Chat["role"];
  topic: string | null;
}

export type Writer =
  | ({ kind: "chat"; main?: Address } & Address)
  | { kind: "code"; component: string }
  | { kind: "owner" };

export type RecordView = AnyRecord & {
  writer: Writer;
  firstWriter: Writer;
  written: string;
  asked?: RecordView;
};

export async function viewsOf(db: Conn, records: AnyRecord[]): Promise<RecordView[]> {
  const writers = new Map<string, Writer>();
  const views: RecordView[] = [];
  for (const record of records) {
    views.push(await viewOf(db, record, writers));
  }
  return views;
}

async function viewOf(db: Conn, record: AnyRecord, writers: Map<string, Writer>): Promise<RecordView> {
  const writer = await writerOf(db, record.author, writers);
  let firstWriter = writer;
  if (record.version > 1) {
    const first = await readAnyRecord(db, { kind: record.kind, id: record.id, version: 1 });
    firstWriter = await writerOf(db, first.author, writers);
  }
  const view: RecordView = { ...record, writer, firstWriter, written: indiaTime(new Date(record.writtenAt)) };
  if (record.kind === "answer") {
    const question = await readRecord(db, QuestionRecord, record.body.question);
    view.asked = await viewOf(db, question, writers);
  }
  return view;
}

/** `writers` keeps the chats already looked up, since a list is mostly a few chats' records. */
async function writerOf(db: Conn, author: Author, writers: Map<string, Writer>): Promise<Writer> {
  if (author.kind !== "chat") return author;
  const known = writers.get(author.chatId);
  if (known) return known;
  const chat = await readChat(db, author.chatId);
  let writer: Writer = { kind: "chat", role: chat.role, topic: chat.topicId };
  if (chat.parentId) {
    const main = await readChat(db, chat.parentId);
    writer = { ...writer, main: { role: main.role, topic: main.topicId } };
  }
  writers.set(author.chatId, writer);
  return writer;
}
