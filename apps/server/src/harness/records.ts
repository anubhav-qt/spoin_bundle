import { and, asc, desc, eq, sql } from "drizzle-orm";
import type { Static, TSchema } from "typebox";
import type { Db, Tx } from "../db/client.ts";
import { harnessRecord } from "../db/schema.ts";
import { pgCode, UNIQUE_VIOLATION } from "../lib/errors.ts";
import { checkValue } from "./check.ts";
import {
  type AnyRecord,
  type Author,
  isRecordKind,
  RECORD_SCHEMAS,
  type RecordKind,
  type RecordRef,
  type RecordStatus,
} from "./schemas.ts";

/**
 * Every version of every record (Trotter's ADR 0023, 0024, on Postgres). Nothing is overwritten: a
 * change, a retirement or an undo is a new version that follows the latest, keeps its id and kind,
 * says why it changed, and on an undo names the earlier version it puts back. Each call takes the
 * kind's schema and checks every version with it on the way in and on the way out.
 */

export class StoreError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StoreError";
  }
}

/** The record moved on since the writer read it: nothing was stored, and the writer reads it again. */
export class RecordConflictError extends StoreError {
  constructor(message: string) {
    super(message);
    this.name = "RecordConflictError";
  }
}

type Conn = Db | Tx;
type Row = typeof harnessRecord.$inferSelect;

export interface FirstVersion {
  kind: string;
  author: Author;
  body: unknown;
  /** Active unless given. */
  status?: RecordStatus;
}

export interface NextVersion {
  /** The version the writer read. It must still be the latest. */
  from: RecordRef;
  status: RecordStatus;
  author: Author;
  reason: string;
  body: unknown;
}

export interface Undo {
  /** The version the writer read. It must still be the latest. */
  from: RecordRef;
  /** The earlier version to put back. */
  to: number;
  author: Author;
  reason: string;
}

/** Stores a new record as its version 1. */
export async function createRecord<Schema extends TSchema>(
  db: Conn,
  schema: Schema,
  first: FirstVersion,
): Promise<Static<Schema>> {
  const record = checkValue(
    schema,
    {
      id: crypto.randomUUID(),
      version: 1,
      kind: first.kind,
      status: first.status ?? "active",
      writtenAt: new Date().toISOString(),
      author: first.author,
      body: first.body,
    },
    `The new ${first.kind}`,
  );
  await insertVersion(db, record);
  return record;
}

/** Stores the next version of a record: a change, a retirement or a rejection. */
export async function changeRecord<Schema extends TSchema>(
  db: Conn,
  schema: Schema,
  next: NextVersion,
): Promise<Static<Schema>> {
  const latest = await readLatestRow(db, next.from.id);
  checkFollowsLatest(latest, next.from);
  const version = latest.version + 1;
  const record = checkValue(
    schema,
    {
      id: latest.id,
      version,
      kind: latest.kind,
      status: next.status,
      writtenAt: new Date().toISOString(),
      author: next.author,
      reason: next.reason,
      body: next.body,
    },
    `Version ${version} of ${latest.kind} ${latest.id}`,
  );
  await insertVersion(db, record);
  return record;
}

/** Stores the next version as a copy of an earlier one, its body and its status: an undo. */
export async function revertRecord<Schema extends TSchema>(
  db: Conn,
  schema: Schema,
  undo: Undo,
): Promise<Static<Schema>> {
  const latest = await readLatestRow(db, undo.from.id);
  checkFollowsLatest(latest, undo.from);
  if (latest.version === 1) {
    throw new StoreError(
      `${latest.kind} ${latest.id} has only version 1, so there's nothing earlier to put back.`,
    );
  }
  if (undo.to < 1 || undo.to >= latest.version) {
    throw new StoreError(
      `An undo puts back an earlier version: ${latest.kind} ${latest.id} has versions 1 to ${latest.version - 1} before its latest.`,
    );
  }
  const [target] = await db
    .select()
    .from(harnessRecord)
    .where(and(eq(harnessRecord.id, latest.id), eq(harnessRecord.version, undo.to)));
  if (!target) throw new StoreError(`Record ${latest.id} has no version ${undo.to}.`);
  const version = latest.version + 1;
  const record = checkValue(
    schema,
    {
      id: latest.id,
      version,
      kind: latest.kind,
      status: target.status,
      writtenAt: new Date().toISOString(),
      author: undo.author,
      reason: undo.reason,
      revertsTo: undo.to,
      body: target.body,
    },
    `Version ${version} of ${latest.kind} ${latest.id}`,
  );
  await insertVersion(db, record);
  return record;
}

/** One exact version, as it was written. */
export async function readRecord<Schema extends TSchema>(
  db: Conn,
  schema: Schema,
  ref: RecordRef,
): Promise<Static<Schema>> {
  const [row] = await db
    .select()
    .from(harnessRecord)
    .where(
      and(
        eq(harnessRecord.id, ref.id),
        eq(harnessRecord.version, ref.version),
        eq(harnessRecord.kind, ref.kind),
      ),
    );
  if (!row) throw new StoreError(`There is no version ${ref.version} of ${ref.kind} ${ref.id}.`);
  return checkRow(schema, row, `Stored ${ref.kind} ${ref.id} version ${ref.version}`);
}

/** The latest version of a record. */
export async function readLatestRecord<Schema extends TSchema>(
  db: Conn,
  schema: Schema,
  kind: string,
  id: string,
): Promise<Static<Schema>> {
  const [row] = await db
    .select()
    .from(harnessRecord)
    .where(and(eq(harnessRecord.id, id), eq(harnessRecord.kind, kind)))
    .orderBy(desc(harnessRecord.version))
    .limit(1);
  if (!row) throw new StoreError(`There is no ${kind} ${id}.`);
  return checkRow(schema, row, `Stored ${kind} ${id}`);
}

/** Every version of a record, oldest first. */
export async function readRecordHistory<Schema extends TSchema>(
  db: Conn,
  schema: Schema,
  kind: string,
  id: string,
): Promise<Static<Schema>[]> {
  const rows = await db
    .select()
    .from(harnessRecord)
    .where(and(eq(harnessRecord.id, id), eq(harnessRecord.kind, kind)))
    .orderBy(asc(harnessRecord.version));
  return rows.map((row) => checkRow(schema, row, `Stored ${kind} ${id}`));
}

/** The latest version of every record of a kind, least recently written first; only those with `status` when given. */
export async function listLatestRecords<Schema extends TSchema>(
  db: Conn,
  schema: Schema,
  kind: string,
  status?: RecordStatus,
): Promise<Static<Schema>[]> {
  const latest = sql`${harnessRecord.version} = (SELECT max(r.version) FROM harness_record r WHERE r.id = ${harnessRecord.id})`;
  const rows = await db
    .select()
    .from(harnessRecord)
    .where(and(eq(harnessRecord.kind, kind), latest, status ? eq(harnessRecord.status, status) : undefined))
    .orderBy(asc(harnessRecord.seq));
  return rows.map((row) => checkRow(schema, row, `A stored ${kind}`));
}

/** One exact version of a record whose kind is known only by name. */
export async function readAnyRecord(db: Conn, ref: RecordRef): Promise<AnyRecord> {
  return readRecord(db, RECORD_SCHEMAS[recordKindOf(ref.kind)], ref);
}

export function recordKindOf(kind: string): RecordKind {
  if (isRecordKind(kind)) return kind;
  throw new StoreError(
    `There's no kind of record called ${kind}. The kinds are: ${Object.keys(RECORD_SCHEMAS).join(", ")}.`,
  );
}

/** The reference that cites this exact version. */
export function refOf(record: { kind: string; id: string; version: number }): RecordRef {
  return { kind: record.kind, id: record.id, version: record.version };
}

interface Stored {
  id: string;
  version: number;
  kind: string;
  status: RecordStatus;
  writtenAt: string;
  author: Author;
  reason?: string;
  revertsTo?: number;
  body: unknown;
}

async function insertVersion(db: Conn, record: Stored): Promise<void> {
  try {
    await db.insert(harnessRecord).values({
      id: record.id,
      version: record.version,
      kind: record.kind,
      status: record.status,
      writtenAt: new Date(record.writtenAt),
      author: record.author,
      reason: record.reason ?? null,
      revertsTo: record.revertsTo ?? null,
      body: record.body,
    });
  } catch (error) {
    // Two writers read the same latest version; the second one's version already exists.
    if (pgCode(error) === UNIQUE_VIOLATION) {
      throw new RecordConflictError(
        `${record.kind} ${record.id} moved on to version ${record.version} meanwhile. Read it again before changing it.`,
      );
    }
    throw error;
  }
}

async function readLatestRow(db: Conn, id: string): Promise<Row> {
  const [row] = await db
    .select()
    .from(harnessRecord)
    .where(eq(harnessRecord.id, id))
    .orderBy(desc(harnessRecord.version))
    .limit(1);
  if (!row) throw new StoreError(`There is no record ${id}.`);
  return row;
}

function checkFollowsLatest(latest: Row, from: RecordRef): void {
  if (latest.kind !== from.kind)
    throw new StoreError(`Record ${latest.id} is a ${latest.kind}, not a ${from.kind}.`);
  if (latest.version !== from.version) {
    throw new RecordConflictError(
      `${latest.kind} ${latest.id} is at version ${latest.version} now, not ${from.version}. Read it again before changing it.`,
    );
  }
}

function checkRow<Schema extends TSchema>(schema: Schema, row: Row, what: string): Static<Schema> {
  const record: Record<string, unknown> = {
    id: row.id,
    version: row.version,
    kind: row.kind,
    status: row.status,
    writtenAt: row.writtenAt.toISOString(),
    author: row.author,
    body: row.body,
  };
  if (row.reason !== null) record.reason = row.reason;
  if (row.revertsTo !== null) record.revertsTo = row.revertsTo;
  return checkValue(schema, record, what);
}
