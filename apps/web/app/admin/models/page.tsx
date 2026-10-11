"use client";

/**
 * Model accounts (task 0045): CLIProxyAPI's signed-in accounts and the models it
 * serves, read live, and each model's calls over the last day from `model_call`,
 * Gemini and NIM alike. Admin only, reached by URL like `/admin/jobs`; it only
 * reports.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api, type ModelAccounts } from "@/lib/api";

function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function seconds(ms: number | null): string {
  return ms === null ? "–" : `${(ms / 1000).toFixed(1)}s`;
}

function tokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export default function AdminModelsPage() {
  const [status, setStatus] = useState<ModelAccounts | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.adminModels
      .status()
      .then((s) => {
        setStatus(s);
        setError(null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <main className="repairs-page">
      <div className="repairs-top">
        <h1>Model accounts</h1>
        <span className="repairs-devtag">/admin/models · admin</span>
      </div>
      {error ? <p className="repairs-error">{error}</p> : null}
      {status === null ? (
        <p className="repairs-lede">Loading…</p>
      ) : (
        <>
          <section className="queue-section">
            <h2 className="repairs-side-h">CLIProxyAPI accounts</h2>
            {status.proxy_error ? (
              <div className="repairs-status" data-tone="fail">
                <code>{status.proxy_error}</code>
              </div>
            ) : status.accounts.length === 0 ? (
              <p className="repairs-lede">No account is signed in.</p>
            ) : (
              <table className="jobs-table">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Status</th>
                    <th>Calls</th>
                    <th>Failed</th>
                  </tr>
                </thead>
                <tbody>
                  {status.accounts.map((a) => (
                    <tr key={a.account}>
                      <td className="jobs-mono">
                        {a.account} · {a.provider}
                      </td>
                      <td data-hot={a.disabled || a.unavailable}>
                        {a.disabled ? "disabled" : a.unavailable ? "unavailable" : a.status}
                        {a.status_message ? (
                          <>
                            : <code>{a.status_message}</code>
                          </>
                        ) : null}
                      </td>
                      <td>{a.succeeded}</td>
                      <td data-hot={a.failed > 0}>{a.failed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {status.served.length > 0 ? (
              <p className="repairs-lede">
                Serves: <span className="jobs-mono">{status.served.join(", ")}</span>
              </p>
            ) : null}
          </section>

          <section className="queue-section">
            <h2 className="repairs-side-h">NVIDIA NIM</h2>
            <p className="repairs-lede">
              {status.nim_configured
                ? "The key is set: Kimi K3, then Nemotron 3 Ultra while it is down."
                : "NVIDIA_NIM_API_KEY is not set, so the NIM leg is off."}
            </p>
          </section>

          <section className="queue-section">
            <h2 className="repairs-side-h">Calls, last {status.window_hours} hours</h2>
            {status.stats.length === 0 ? (
              <p className="repairs-lede">No model has been called.</p>
            ) : (
              <table className="jobs-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Calls</th>
                    <th>Failures</th>
                    <th>Last success</th>
                    <th>Last failure</th>
                    <th>First token</th>
                    <th>Tokens in / out</th>
                  </tr>
                </thead>
                <tbody>
                  {status.stats.map((m) => (
                    <tr key={`${m.provider}/${m.model}`}>
                      <td className="jobs-mono">
                        {m.model} · {m.provider}
                      </td>
                      <td>
                        {m.ok} of {m.calls}
                      </td>
                      <td data-hot={m.failures.length > 0}>
                        {m.failures.length === 0
                          ? "none"
                          : m.failures.map((f) => `${f.kind} ${f.count}`).join(", ")}
                      </td>
                      <td>{ago(m.last_ok_at)}</td>
                      <td>
                        {m.last_failure ? (
                          <>
                            {ago(m.last_failure_at)}, {m.last_failure.kind}
                            {m.last_failure.reason ? (
                              <>
                                : <code>{m.last_failure.reason}</code>
                              </>
                            ) : null}
                          </>
                        ) : (
                          "none"
                        )}
                      </td>
                      <td>{seconds(m.median_first_token_ms)}</td>
                      <td>
                        {tokens(m.prompt_tokens)} / {tokens(m.output_tokens)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </main>
  );
}
