"use client";

/**
 * B14 / ADR-0076 — operator triage for reported cards. Dev-only: the
 * `/admin/repairs` endpoints are `env`-gated on the API (task 0035 is the real
 * admin-role gate). A plain Next route reached by URL, no nav entry — same
 * spirit as the archived `/admin/quota` page.
 *
 * The card is rendered here and screenshotted client-side with `html-to-image`
 * (the same call the card's Share button uses) so a Fix carries a picture of
 * the defect to the repair model. Once a repair lands the entry stays, showing
 * the new version with a before/after toggle, until dismissed.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, type RepairCard, type RepairQueueItem } from "@/lib/api";

const REASON_LABEL: Record<string, string> = {
  art: "art",
  diagram: "diagram",
  code_block: "code block",
  formatting: "formatting",
  other: "other",
};

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function CardRender({ card, innerRef }: { card: RepairCard; innerRef?: React.Ref<HTMLDivElement> }) {
  const art = card.visual_slots?.art;
  return (
    <div className="card repairs-card" ref={innerRef}>
      <div className="card-title">{card.canonical_title}</div>
      <div className="card-summary">{card.summary}</div>
      <div className="card-body repairs-card-body">{card.body}</div>
      {art ? (
        <pre className="repairs-ascii">{art}</pre>
      ) : null}
      {card.visual_slots?.alt ? (
        <div className="repairs-ascii-cap">{card.visual_slots.alt}</div>
      ) : null}
    </div>
  );
}

function QueueEntry({ item, onChanged }: { item: RepairQueueItem; onChanged: () => void }) {
  const beforeRef = useRef<HTMLDivElement>(null);
  const [form, setForm] = useState<null | "fix" | "remake">(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<"before" | "after">(item.after ? "after" : "before");

  const shot = useCallback(async (): Promise<Blob> => {
    const el = beforeRef.current;
    if (!el) throw new Error("card not mounted");
    const { toBlob } = await import("html-to-image");
    const blob = await toBlob(el, {
      pixelRatio: 2,
      backgroundColor: getComputedStyle(document.body).backgroundColor || "#edf0ea",
      // The page links a cross-origin Google Fonts stylesheet; html-to-image's
      // font-embedding step reads `sheet.cssRules` on it and throws a
      // SecurityError. The repair reference image doesn't need embedded fonts.
      skipFonts: true,
      cacheBust: true,
    });
    if (!blob) throw new Error("could not render the card");
    return blob;
  }, []);

  const run = useCallback(
    async (mode: "fix" | "remake") => {
      setBusy(true);
      setErr(null);
      try {
        if (mode === "fix") {
          await api.adminRepairs.fix(item.card_id, await shot(), text);
        } else {
          if (!text.trim()) {
            setErr("A remake needs a description of what to make instead.");
            setBusy(false);
            return;
          }
          await api.adminRepairs.remake(item.card_id, text, await shot().catch(() => null));
        }
        setForm(null);
        setText("");
        onChanged();
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [item.card_id, text, shot, onChanged],
  );

  const del = useCallback(async () => {
    if (!confirm("Retire this card from every feed?")) return;
    setBusy(true);
    try {
      await api.adminRepairs.delete(item.card_id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }, [item.card_id, onChanged]);

  const dismiss = useCallback(async () => {
    setBusy(true);
    try {
      await api.adminRepairs.dismiss(item.card_id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }, [item.card_id, onChanged]);

  const revert = useCallback(async () => {
    if (!confirm("Undo this repair? The original version goes back live.")) return;
    setBusy(true);
    try {
      await api.adminRepairs.revert(item.card_id);
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [item.card_id, onChanged]);

  const repair = item.latest_repair;
  const shown = view === "after" && item.after ? item.after : item.before;

  return (
    <div className="repairs-entry" data-state={item.state}>
      <div className="repairs-left">
        {item.after ? (
          <div className="repairs-toggle">
            <button
              type="button"
              data-active={view === "before"}
              onClick={() => setView("before")}
            >
              Before · v{item.before.version}
            </button>
            <button
              type="button"
              data-active={view === "after"}
              onClick={() => setView("after")}
            >
              After · v{item.after.version}
            </button>
          </div>
        ) : null}
        <CardRender card={shown} innerRef={view === "before" ? beforeRef : undefined} />
      </div>

      <div className="repairs-side">
        {item.report_count > 0 ? (
          <>
            <div className="repairs-side-h">
              Reports <span className="repairs-count">{item.report_count}</span>
            </div>
            {item.reports.map((r, i) => (
              <div key={i} className="repairs-report">
                <div className="repairs-report-top">
                  <span className="repairs-reason">{REASON_LABEL[r.reason] ?? r.reason}</span>
                  <span className="repairs-when">{ago(r.created_at)}</span>
                </div>
                {r.note ? (
                  <div className="repairs-report-note">{r.note}</div>
                ) : (
                  <div className="repairs-report-note repairs-report-none">no note</div>
                )}
              </div>
            ))}
          </>
        ) : null}

        {repair && repair.status === "running" ? (
          <div className="repairs-status" data-tone="run">
            A {repair.mode} is running — this card stays here until it resolves.
          </div>
        ) : null}
        {repair && repair.status === "failed" ? (
          <div className="repairs-status" data-tone="fail">
            Last {repair.mode} failed: <code>{repair.error}</code>
          </div>
        ) : null}
        {repair && repair.status === "done" ? (
          <div className="repairs-status" data-tone="done">
            {repair.mode === "fix" ? "Fixed" : "Remade"} {ago(repair.created_at)}.
          </div>
        ) : null}
        {repair && repair.status === "pending" ? (
          <div className="repairs-status" data-tone="run">
            {repair.mode} queued — waiting for the worker.
          </div>
        ) : null}

        {err ? <div className="repairs-status" data-tone="fail">{err}</div> : null}

        <div className="repairs-actions">
          {item.state === "open" && !(repair && ["pending", "running"].includes(repair.status)) ? (
            <>
              <button
                type="button"
                className="repairs-btn"
                data-active={form === "fix"}
                disabled={busy}
                onClick={() => setForm(form === "fix" ? null : "fix")}
              >
                Fix
              </button>
              <button
                type="button"
                className="repairs-btn"
                data-active={form === "remake"}
                disabled={busy}
                onClick={() => setForm(form === "remake" ? null : "remake")}
              >
                Remake
              </button>
              <button
                type="button"
                className="repairs-btn repairs-btn-danger"
                disabled={busy}
                onClick={() => void del()}
              >
                Delete
              </button>
            </>
          ) : null}
          {item.state === "resolved" ? (
            <>
              {item.after && item.latest_repair?.status === "done" ? (
                <button
                  type="button"
                  className="repairs-btn"
                  disabled={busy}
                  onClick={() => void revert()}
                >
                  Revert to original
                </button>
              ) : null}
              <button
                type="button"
                className="repairs-btn repairs-btn-primary"
                disabled={busy}
                onClick={() => void dismiss()}
              >
                {item.after ? "Keep new card" : "Dismiss"}
              </button>
            </>
          ) : null}
        </div>

        {form ? (
          <div className="repairs-form">
            <label className="repairs-form-lbl">
              {form === "fix" ? "Guidance for the repair — optional" : "What to make instead — required"}
            </label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              placeholder={
                form === "fix"
                  ? "e.g. redraw the ASCII so arrows align; keep the prose."
                  : "Describe the replacement card: what it should teach and how."
              }
            />
            <div className="repairs-form-actions">
              <span className="repairs-hint">
                {form === "fix"
                  ? "Renders this card to a PNG and sends it with the request."
                  : "Regenerates from scratch through the full quality gate."}
              </span>
              <button
                type="button"
                className="repairs-btn repairs-btn-primary"
                disabled={busy || (form === "remake" && !text.trim())}
                onClick={() => void run(form)}
              >
                {busy ? "…" : form === "fix" ? "Send fix" : "Send remake"}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function AdminRepairsPage() {
  const [items, setItems] = useState<RepairQueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.adminRepairs
      .list()
      .then((rows) => {
        setItems(rows);
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
        <h1>Repair queue</h1>
        <span className="repairs-devtag">/admin/repairs · dev only</span>
      </div>
      {error ? <p className="repairs-error">{error}</p> : null}
      {items === null ? (
        <p className="repairs-lede">Loading…</p>
      ) : items.length === 0 ? (
        <p className="repairs-lede">Nothing flagged.</p>
      ) : (
        <>
          <p className="repairs-lede">
            {items.filter((i) => i.state === "open").length} open ·{" "}
            {items.filter((i) => i.state === "resolved").length} resolved
          </p>
          {items.map((it) => (
            <QueueEntry key={it.card_id} item={it} onChanged={load} />
          ))}
        </>
      )}
    </main>
  );
}
