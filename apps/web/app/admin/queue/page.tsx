"use client";

/**
 * The topic queue (task 0045): every topic that is not live yet, with its
 * generate job. Admin only, reached by URL like `/admin/repairs`.
 *
 * The owner drags a waiting topic to where it should run. The page only says
 * where it was dropped (just ahead of which job, or last); the server picks
 * the priorities that put it there and answers with the whole queue, so what
 * is shown is always the order the worker will claim in. Dragging starts from
 * the handle, so a phone can still scroll the list.
 */

import { Reorder, useDragControls } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, type QueuedTopic } from "@/lib/api";

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const waitingIds = (rows: QueuedTopic[]) =>
  rows.filter((r) => r.status === "pending").map((r) => r.job_id);

function readers(n: number): string {
  if (n === 0) return "no readers waiting";
  return n === 1 ? "1 reader waiting" : `${n} readers waiting`;
}

function Meta({ row }: { row: QueuedTopic }) {
  return (
    <div className="queue-meta">
      <span>{row.slug}</span>
      <span>priority {row.priority}</span>
      <span>{readers(row.requesters)}</span>
      <span>added {ago(row.created_at)}</span>
      {row.attempts > 0 ? <span>{row.attempts === 1 ? "1 attempt" : `${row.attempts} attempts`}</span> : null}
    </div>
  );
}

function WaitingRow({
  row,
  position,
  busy,
  onDragStart,
  onDragEnd,
  onCancel,
}: {
  row: QueuedTopic;
  position: number;
  busy: boolean;
  onDragStart: () => void;
  onDragEnd: (jobId: string) => void;
  onCancel: (row: QueuedTopic) => void;
}) {
  const controls = useDragControls();
  return (
    <Reorder.Item
      value={row.job_id}
      dragListener={false}
      dragControls={controls}
      onDragStart={onDragStart}
      onDragEnd={() => onDragEnd(row.job_id)}
      className="queue-row"
      data-state="pending"
    >
      <button
        type="button"
        className="queue-handle"
        aria-label={`Drag ${row.name} to reorder`}
        disabled={busy}
        onPointerDown={(e) => controls.start(e)}
      >
        ⠿
      </button>
      <span className="queue-pos">{position}</span>
      <div className="queue-main">
        <div className="queue-name">{row.name}</div>
        <Meta row={row} />
      </div>
      <button
        type="button"
        className="repairs-btn repairs-btn-danger"
        disabled={busy}
        onClick={() => onCancel(row)}
      >
        Cancel
      </button>
    </Reorder.Item>
  );
}

export default function AdminQueuePage() {
  const [rows, setRows] = useState<QueuedTopic[] | null>(null);
  const [order, setOrder] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  // A poll landing mid-drag would yank the row out from under the pointer.
  const dragging = useRef(false);
  const orderRef = useRef<string[]>([]);
  const rowsRef = useRef<QueuedTopic[]>([]);

  const apply = useCallback((next: QueuedTopic[]) => {
    rowsRef.current = next;
    orderRef.current = waitingIds(next);
    setRows(next);
    setOrder(orderRef.current);
  }, []);

  const load = useCallback(() => {
    if (dragging.current) return;
    api.adminQueue
      .list()
      .then((next) => {
        if (dragging.current) return;
        apply(next);
        setError(null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [apply]);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  const act = useCallback(
    async (call: () => Promise<QueuedTopic[]>) => {
      setBusy(true);
      setError(null);
      try {
        apply(await call());
        return true;
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
        load();
        return false;
      } finally {
        setBusy(false);
      }
    },
    [apply, load],
  );

  const onReorder = useCallback((ids: string[]) => {
    orderRef.current = ids;
    setOrder(ids);
  }, []);

  const onDragEnd = useCallback(
    (jobId: string) => {
      dragging.current = false;
      const ids = orderRef.current;
      const before = waitingIds(rowsRef.current);
      if (ids.join() === before.join()) return;
      const at = ids.indexOf(jobId);
      void act(() => api.adminQueue.move(jobId, ids[at + 1] ?? null));
    },
    [act],
  );

  const add = useCallback(async () => {
    if (!name.trim()) return;
    if (await act(() => api.adminQueue.add(name.trim(), description))) {
      setName("");
      setDescription("");
    }
  }, [act, name, description]);

  const cancel = useCallback(
    (row: QueuedTopic) => {
      const n = row.requesters;
      const who =
        n === 0
          ? ""
          : n === 1
            ? " The reader who asked for it loses it from their topics."
            : ` The ${n} readers who asked for it lose it from their topics.`;
      if (!confirm(`Cancel “${row.name}”?${who}`)) return;
      void act(() => api.adminQueue.cancel(row.job_id));
    },
    [act],
  );

  const byId = new Map((rows ?? []).map((r) => [r.job_id, r]));
  const running = (rows ?? []).filter((r) => r.status === "running");
  const failed = (rows ?? []).filter((r) => r.status === "failed");

  return (
    <main className="repairs-page">
      <div className="repairs-top">
        <h1>Topic queue</h1>
        <span className="repairs-devtag">/admin/queue · admin</span>
      </div>

      <form
        className="queue-add"
        onSubmit={(e) => {
          e.preventDefault();
          void add();
        }}
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Add a topic by name"
          maxLength={120}
          aria-label="Topic name"
        />
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What it should cover — optional"
          aria-label="Description"
        />
        <button type="submit" className="repairs-btn repairs-btn-primary" disabled={busy || !name.trim()}>
          Add
        </button>
      </form>

      {error ? <p className="repairs-error">{error}</p> : null}

      {rows === null ? (
        <p className="repairs-lede">Loading…</p>
      ) : (
        <p className="repairs-lede">
          {running.length} running · {order.length} waiting · {failed.length} failed
        </p>
      )}

      {running.length > 0 ? (
        <section className="queue-section">
          <h2 className="repairs-side-h">Running</h2>
          <ul className="queue-list">
            {running.map((row) => (
              <li key={row.job_id} className="queue-row" data-state="running">
                <span className="queue-pos">▶</span>
                <div className="queue-main">
                  <div className="queue-name">{row.name}</div>
                  <Meta row={row} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {order.length > 0 ? (
        <section className="queue-section">
          <h2 className="repairs-side-h">Waiting, in the order they run</h2>
          <Reorder.Group axis="y" values={order} onReorder={onReorder} className="queue-list">
            {order.map((id, i) => {
              const row = byId.get(id);
              return row ? (
                <WaitingRow
                  key={id}
                  row={row}
                  position={i + 1}
                  busy={busy}
                  onDragStart={() => {
                    dragging.current = true;
                  }}
                  onDragEnd={onDragEnd}
                  onCancel={cancel}
                />
              ) : null;
            })}
          </Reorder.Group>
        </section>
      ) : null}

      {failed.length > 0 ? (
        <section className="queue-section">
          <h2 className="repairs-side-h">Failed</h2>
          <ul className="queue-list">
            {failed.map((row) => (
              <li key={row.job_id} className="queue-row" data-state="failed">
                <span className="queue-pos">✕</span>
                <div className="queue-main">
                  <div className="queue-name">{row.name}</div>
                  <Meta row={row} />
                  {row.last_error ? (
                    <div className="repairs-status" data-tone="fail">
                      <code>{row.last_error}</code>
                    </div>
                  ) : null}
                </div>
                <div className="queue-actions">
                  <button
                    type="button"
                    className="repairs-btn"
                    disabled={busy}
                    onClick={() => void act(() => api.adminQueue.retry(row.job_id))}
                  >
                    Retry
                  </button>
                  <button
                    type="button"
                    className="repairs-btn repairs-btn-danger"
                    disabled={busy}
                    onClick={() => cancel(row)}
                  >
                    Cancel
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {rows !== null && rows.length === 0 ? (
        <p className="repairs-lede">Nothing queued.</p>
      ) : null}
    </main>
  );
}
