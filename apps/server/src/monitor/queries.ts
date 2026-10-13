import { sql } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type pg from "pg";
import { makePool } from "../db/client.ts";

/*
 * What the run monitor reads (task 0045): every chat of the pipeline, live, and AskAI's never.
 * The pool's transactions are READ ONLY, so the page can't write to the run it watches.
 */

type MonitorDb = NodePgDatabase;

export function connectMonitor(url: string): { pool: pg.Pool; db: MonitorDb } {
  const pool = makePool(url, { name: "monitor", max: 3, readOnly: true });
  return { pool, db: drizzle(pool) };
}

/** A transcript or record list is sent in pages, so a long chat doesn't come down at once. */
const PAGE = 300;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Every chat but AskAI's, with what it is doing now; the run's totals; each topic's progress. */
export async function readState(db: MonitorDb) {
  const chats = await db.execute(sql`
    SELECT c.id, c.role, c.task, c.parent_id AS "parentId", c.topic_id AS "topicId",
      t.canonical_name AS topic, c.created_at AS "createdAt",
      last_run.status AS "runStatus", last_run.model, last_run.started_at AS "runStartedAt",
      last_run.ended_at AS "runEndedAt", last_run.error AS "runError",
      runs.count AS runs,
      wakes.waiting, wakes.taken, wakes.next_due AS "nextDueAt",
      last_tool.tool AS "lastTool", last_tool.at AS "lastToolAt", tools.count AS "toolCalls",
      messages.count AS messages,
      calls.count AS "modelCalls", calls.failed AS "failedCalls",
      calls.prompt_tokens AS "promptTokens", calls.output_tokens AS "outputTokens",
      last_call.ok AS "lastCallOk", last_call.failure AS "lastCallFailure",
      last_call.started_at AS "lastCallAt"
    FROM chat c
    LEFT JOIN topic t ON t.id = c.topic_id
    LEFT JOIN LATERAL (
      SELECT status, model, started_at, ended_at, error FROM chat_run
      WHERE chat_id = c.id ORDER BY started_at DESC LIMIT 1
    ) last_run ON true
    LEFT JOIN LATERAL (SELECT count(*) FROM chat_run WHERE chat_id = c.id) runs ON true
    LEFT JOIN LATERAL (
      SELECT count(*) FILTER (WHERE status = 'waiting') AS waiting,
        count(*) FILTER (WHERE status = 'taken') AS taken,
        min(due_at) FILTER (WHERE status = 'waiting') AS next_due
      FROM wake WHERE chat_id = c.id
    ) wakes ON true
    LEFT JOIN LATERAL (
      SELECT a.tool, a.at FROM action_log a JOIN chat_run r ON r.id = a.run_id
      WHERE r.chat_id = c.id ORDER BY a.at DESC LIMIT 1
    ) last_tool ON true
    LEFT JOIN LATERAL (
      SELECT count(*) FROM action_log a JOIN chat_run r ON r.id = a.run_id WHERE r.chat_id = c.id
    ) tools ON true
    LEFT JOIN LATERAL (SELECT count(*) FROM chat_message WHERE chat_id = c.id) messages ON true
    LEFT JOIN LATERAL (
      SELECT count(*), count(*) FILTER (WHERE NOT m.ok) AS failed,
        coalesce(sum(m.prompt_tokens), 0) AS prompt_tokens,
        coalesce(sum(m.output_tokens), 0) AS output_tokens
      FROM model_call m JOIN chat_run r ON r.id = m.run_id WHERE r.chat_id = c.id
    ) calls ON true
    LEFT JOIN LATERAL (
      SELECT m.ok, m.failure, m.started_at FROM model_call m JOIN chat_run r ON r.id = m.run_id
      WHERE r.chat_id = c.id ORDER BY m.started_at DESC LIMIT 1
    ) last_call ON true
    WHERE c.role::text <> 'ask_ai'
    ORDER BY c.created_at
  `);

  const [clock] = (
    await db.execute(sql`
      SELECT now() AS now, min(r.started_at) AS "firstStartedAt", max(r.ended_at) AS "lastEndedAt"
      FROM chat_run r JOIN chat c ON c.id = r.chat_id
      WHERE c.role::text <> 'ask_ai'
    `)
  ).rows;

  const topics = await db.execute(sql`
    SELECT t.id, t.canonical_name AS name,
      (SELECT count(*) FROM subtopic s WHERE s.topic_id = t.id) AS subtopics,
      (SELECT coalesce(json_object_agg(stage, n), '{}') FROM (
        SELECT coalesce(gen_meta ->> 'stage', status::text) AS stage, count(*) AS n
        FROM card WHERE topic_id = t.id GROUP BY 1
      ) by_stage) AS cards,
      (SELECT count(*) FROM card WHERE topic_id = t.id AND visual_kind IS NOT NULL) AS "withArt",
      (SELECT coalesce(json_object_agg(stage, n), '{}') FROM (
        SELECT coalesce(q.gen_meta ->> 'stage', q.status::text) AS stage, count(*) AS n
        FROM question q JOIN subtopic s ON s.id = q.subtopic_id WHERE s.topic_id = t.id GROUP BY 1
      ) by_stage) AS questions
    FROM topic t
    WHERE t.id IN (SELECT topic_id FROM chat WHERE role = 'tadpole')
    ORDER BY t.canonical_name
  `);

  const records = await db.execute(sql`
    SELECT kind, count(DISTINCT id) AS count FROM harness_record
    WHERE author ->> 'chatId' IS NULL
      OR author ->> 'chatId' NOT IN (SELECT id::text FROM chat WHERE role::text = 'ask_ai')
    GROUP BY kind ORDER BY kind
  `);

  return { clock, chats: chats.rows, topics: topics.rows, records: records.rows };
}

/**
 * One chat: its runs, wakes, model calls, and the transcript and records it wrote past the ones the
 * page has. Undefined for AskAI's chats and for an id that isn't a chat.
 */
export async function readChat(db: MonitorDb, id: string, afterMessage: number, afterRecord: number) {
  if (!UUID.test(id)) return undefined;
  const [chat] = (
    await db.execute(sql`
      SELECT c.id, c.role, c.task, c.parent_id AS "parentId", t.canonical_name AS topic,
        c.created_at AS "createdAt"
      FROM chat c LEFT JOIN topic t ON t.id = c.topic_id
      WHERE c.id = ${id} AND c.role::text <> 'ask_ai'
    `)
  ).rows;
  if (!chat) return undefined;

  const runs = await db.execute(sql`
    SELECT r.id, r.status, r.model, r.triggers, r.started_at AS "startedAt", r.ended_at AS "endedAt",
      r.error, calls.count AS calls, calls.failed,
      calls.prompt_tokens AS "promptTokens", calls.output_tokens AS "outputTokens"
    FROM chat_run r
    LEFT JOIN LATERAL (
      SELECT count(*), count(*) FILTER (WHERE NOT ok) AS failed,
        coalesce(sum(prompt_tokens), 0) AS prompt_tokens, coalesce(sum(output_tokens), 0) AS output_tokens
      FROM model_call WHERE run_id = r.id
    ) calls ON true
    WHERE r.chat_id = ${id}
    ORDER BY r.started_at
  `);

  const wakes = await db.execute(sql`
    SELECT id, status, due_at AS "dueAt", trigger, tries, error, created_at AS "createdAt"
    FROM wake WHERE chat_id = ${id}
    ORDER BY created_at DESC LIMIT 50
  `);

  const calls = await db.execute(sql`
    SELECT m.started_at AS "startedAt", m.provider, m.model, m.ok, m.failure, m.reason,
      m.first_token_ms AS "firstTokenMs", m.total_ms AS "totalMs",
      m.prompt_tokens AS "promptTokens", m.output_tokens AS "outputTokens"
    FROM model_call m JOIN chat_run r ON r.id = m.run_id
    WHERE r.chat_id = ${id}
    ORDER BY m.started_at DESC LIMIT 50
  `);

  const messages = await db.execute(sql`
    SELECT seq, run_id AS "runId", message FROM chat_message
    WHERE chat_id = ${id} AND seq > ${afterMessage}
    ORDER BY seq LIMIT ${PAGE}
  `);

  const records = await db.execute(sql`
    SELECT seq, id, version, kind, status, written_at AS "writtenAt", reason, body FROM harness_record
    WHERE author ->> 'chatId' = ${id} AND seq > ${afterRecord}
    ORDER BY seq LIMIT ${PAGE}
  `);

  return {
    chat,
    runs: runs.rows,
    wakes: wakes.rows,
    calls: calls.rows,
    messages: messages.rows,
    records: records.rows,
  };
}

/** A run's instructions, which are long and so fetched only when asked for. */
export async function readRunPrompt(db: MonitorDb, runId: string): Promise<string | undefined> {
  if (!UUID.test(runId)) return undefined;
  const [run] = (
    await db.execute(sql`
      SELECT r.system_prompt AS prompt FROM chat_run r JOIN chat c ON c.id = r.chat_id
      WHERE r.id = ${runId} AND c.role::text <> 'ask_ai'
    `)
  ).rows;
  if (!run) return undefined;
  return String(run.prompt);
}
