"use client";

/**
 * B4 — a read surface for `GET /admin/quota` (quota_report.py). Dev-only: the
 * endpoint is `env`-gated on the API (404 in production until task 0035's
 * admin-role gate). A plain Next route, not a shell view — reached by URL, no
 * nav entry.
 *
 * ADR-0065's three terminal conditions are shown as THREE separate tiles, never
 * one "status: OK": "daily budget spent", "minute-throttled" and "models
 * parked" have different cures.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api, type QuotaCell, type QuotaStatus } from "@/lib/api";

function groupByPoolAndModel(cells: QuotaCell[]): Array<{
  pool: string;
  models: Array<{ model: string; cells: QuotaCell[] }>;
}> {
  const pools = new Map<string, Map<string, QuotaCell[]>>();
  for (const cell of cells) {
    let byModel = pools.get(cell.pool);
    if (!byModel) {
      byModel = new Map();
      pools.set(cell.pool, byModel);
    }
    const list = byModel.get(cell.model) ?? [];
    list.push(cell);
    byModel.set(cell.model, list);
  }
  const order = ["thinking", "generator", "other"];
  return [...pools.entries()]
    .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
    .map(([pool, byModel]) => ({
      pool,
      models: [...byModel.entries()]
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([model, modelCells]) => ({
          model,
          cells: [...modelCells].sort((a, b) => a.key_index - b.key_index),
        })),
    }));
}

/** Non-linear so a lightly-used cell still reads as "touched". */
function cellFill(cell: QuotaCell): string {
  if (cell.exhausted_at) return "var(--accent)";
  if (cell.requests_spent === 0) return "var(--bg-3)";
  const frac = cell.daily_ceiling ? cell.requests_spent / cell.daily_ceiling : 0;
  if (frac >= 0.66) return "var(--fg)";
  if (frac >= 0.25) return "var(--fg-2)";
  return "var(--fg-3)";
}

const POOL_LABEL: Record<string, string> = {
  thinking: "Thinking ladder",
  generator: "Generator ladder",
  other: "Retired / off-ladder",
};
const POOL_SUB: Record<string, string> = {
  thinking: "curriculum · judging · grading",
  generator: "cards · questions",
  other: "no longer in a configured ladder",
};

export default function AdminQuotaPage() {
  const [data, setData] = useState<QuotaStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.adminQuota());
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setError("Sign in to view quota state.");
      } else if (cause instanceof ApiError && cause.status === 404) {
        setError("This surface is disabled here (production, or no admin role — task 0035).");
      } else {
        setError("Couldn’t load quota state.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const keyCount = data ? new Set(data.cells.map((c) => c.key_index)).size : 0;
  const modelCount = data ? new Set(data.cells.map((c) => c.model)).size : 0;
  const parkedModels = new Set(data?.parked_models.map((p) => p.model));

  return (
    <div className="quota-page">
      <p className="quota-eyebrow">Quota</p>
      <h1 className="quota-title">Today’s key × model budget.</h1>

      {loading ? (
        <p className="quota-meta">Reading…</p>
      ) : error ? (
        <div className="quota-state">
          <p>{error}</p>
          <button type="button" className="quota-retry" onClick={() => void load()}>
            Try again
          </button>
        </div>
      ) : data ? (
        <>
          <p className="quota-meta">
            {new Date(data.day).toUTCString().slice(0, 16)} · read{" "}
            {new Date(data.generated_at).toISOString().slice(11, 16)} UTC · {keyCount} keys ×{" "}
            {modelCount} models · {data.cells_total} cells
          </p>

          <hr className="quota-rule" />

          <div className="quota-rollups">
            <div className="quota-tile">
              <div className="quota-tile-label">Daily budget spent</div>
              <div className="quota-tile-value">
                {data.cells_daily_exhausted}
                <span className="quota-tile-of"> / {data.cells_total}</span>
              </div>
              <div className="quota-tile-note">cells at their daily ceiling</div>
            </div>
            <div className="quota-tile">
              <div className="quota-tile-label">Minute-throttled</div>
              <div className="quota-tile-value">{data.cells_minute_throttled}</div>
              <div className="quota-tile-note">cooling down, daily room left</div>
            </div>
            <div className="quota-tile" data-warn={data.models_parked > 0}>
              <div className="quota-tile-label">Models parked</div>
              <div className="quota-tile-value">{data.models_parked}</div>
              <div className="quota-tile-note">provider outage, out of rotation</div>
            </div>
          </div>

          <hr className="quota-rule" />

          {groupByPoolAndModel(data.cells).map(({ pool, models }) => (
            <section key={pool} className="quota-pool">
              <div className="quota-pool-head">
                <span className="quota-eyebrow">{POOL_LABEL[pool] ?? pool}</span>
                <span className="quota-pool-sub">{POOL_SUB[pool] ?? ""}</span>
              </div>
              <div className="quota-models">
                {models.map(({ model, cells }) => {
                  const spent = cells.reduce((s, c) => s + c.requests_spent, 0);
                  const ceiling = cells.reduce((s, c) => s + (c.daily_ceiling ?? 0), 0);
                  const perKey = cells[0]?.daily_ceiling;
                  const parked = parkedModels.has(model);
                  return (
                    <div key={model} className="quota-model" data-parked={parked}>
                      <div className="quota-model-name">
                        <span>{model}</span>
                        {parked ? <span className="quota-parked-pill">parked</span> : null}
                        <span className="quota-model-sub">
                          {cells.length} {cells.length === 1 ? "key" : "keys"}
                          {perKey ? ` · ${perKey}/day each` : ""}
                        </span>
                      </div>
                      <div
                        className="quota-keystrip"
                        style={{ gridTemplateColumns: `repeat(${cells.length}, 1fr)` }}
                        title="one square per key"
                      >
                        {cells.map((cell) => (
                          <span
                            key={cell.key_index}
                            className="quota-keycell"
                            data-parked={parked}
                            data-throttled={
                              cell.cooldown_until
                                ? new Date(cell.cooldown_until) > new Date(data.generated_at)
                                : false
                            }
                            style={{ background: parked ? undefined : cellFill(cell) }}
                            title={`key ${cell.key_index}: ${cell.requests_spent}${
                              cell.daily_ceiling ? ` / ${cell.daily_ceiling}` : ""
                            }`}
                          />
                        ))}
                      </div>
                      <div className="quota-model-total mono">
                        {parked ? (
                          "—"
                        ) : (
                          <>
                            {spent.toLocaleString()}
                            <span className="quota-tile-of">
                              {" "}
                              / {ceiling.toLocaleString()}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}

          <hr className="quota-rule" />

          <div className="quota-pool-head">
            <span className="quota-eyebrow">Parked models</span>
          </div>
          {data.parked_models.length === 0 ? (
            <p className="quota-meta">None — every model is in rotation.</p>
          ) : (
            <div className="quota-parked-list">
              {data.parked_models.map((p) => (
                <div key={p.model} className="quota-parked-row">
                  <span className="mono quota-parked-model">{p.model}</span>
                  <span className="mono quota-parked-when">
                    since {new Date(p.excluded_at).toISOString().slice(11, 16)} · clears ~
                    {new Date(p.expires_at).toISOString().slice(11, 16)}
                  </span>
                  <span className="quota-parked-reason">{p.reason}</span>
                </div>
              ))}
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
