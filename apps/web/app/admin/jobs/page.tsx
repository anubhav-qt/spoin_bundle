"use client";

/**
 * Job status (task 0045): each background job's last success and last error,
 * the generate and repair queues by status, and every failed job with its
 * error. Admin only, reached by URL like `/admin/repairs`. Failed topics are
 * retried or cancelled from `/admin/queue`; this page only reports.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api, type JobStatus } from "@/lib/api";

function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const STATUSES = ["pending", "running", "completed", "failed"] as const;

export default function AdminJobsPage() {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.adminJobs
      .status()
      .then((s) => {
        setStatus(s);
        setError(null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <main className="repairs-page">
      <div className="repairs-top">
        <h1>Job status</h1>
        <span className="repairs-devtag">/admin/jobs · admin</span>
      </div>
      {error ? <p className="repairs-error">{error}</p> : null}
      {status === null ? (
        <p className="repairs-lede">Loading…</p>
      ) : (
        <>
          <section className="queue-section">
            <h2 className="repairs-side-h">Background jobs</h2>
            {status.runs.length === 0 ? (
              <p className="repairs-lede">No background job has run yet.</p>
            ) : (
              <table className="jobs-table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Last success</th>
                    <th>Last error</th>
                  </tr>
                </thead>
                <tbody>
                  {status.runs.map((run) => (
                    <tr key={run.name}>
                      <td className="jobs-mono">{run.name}</td>
                      <td>{ago(run.last_ok_at)}</td>
                      <td>
                        {run.last_error ? (
                          <>
                            {ago(run.last_error_at)}: <code>{run.last_error}</code>
                          </>
                        ) : (
                          "none"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="queue-section">
            <h2 className="repairs-side-h">Queues</h2>
            <table className="jobs-table">
              <thead>
                <tr>
                  <th>Kind</th>
                  {STATUSES.map((s) => (
                    <th key={s}>{s}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {status.queues.map((q) => (
                  <tr key={q.kind}>
                    <td className="jobs-mono">{q.kind}</td>
                    {STATUSES.map((s) => (
                      <td key={s} data-hot={s === "failed" && q[s] > 0}>
                        {q[s]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="queue-section">
            <h2 className="repairs-side-h">Failed jobs</h2>
            {status.failed.length === 0 ? (
              <p className="repairs-lede">None.</p>
            ) : (
              <ul className="queue-list">
                {status.failed.map((f) => (
                  <li key={f.job_id} className="queue-row" data-state="failed">
                    <span className="queue-pos">✕</span>
                    <div className="queue-main">
                      <div className="queue-name">{f.topic_name}</div>
                      <div className="queue-meta">
                        <span>{f.kind}</span>
                        {f.card_id ? <span>card {f.card_id.slice(0, 8)}</span> : null}
                        <span>{f.attempts === 1 ? "1 attempt" : `${f.attempts} attempts`}</span>
                        <span>failed {ago(f.failed_at)}</span>
                      </div>
                      {f.last_error ? (
                        <div className="repairs-status" data-tone="fail">
                          <code>{f.last_error}</code>
                        </div>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  );
}
