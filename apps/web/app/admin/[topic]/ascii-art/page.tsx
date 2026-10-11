"use client";

/**
 * ADR-0104 — operator review of one topic's ASCII scenes, as a card stack.
 *
 * Admin only: the `/admin/ascii` endpoints answer 403 to anyone without the
 * admin role (ADR-0106). A plain Next route reached by URL, no nav entry --
 * the same spirit as `/admin/repairs`, which this page hands its
 * rejections to rather than growing a second repair path.
 *
 * Why a stack and not a table: ADR-0104 made the drawing structurally correct
 * by construction (it is copied from a hand-verified library entry, so it
 * cannot arrive skewed), which leaves exactly one question per scene -- does
 * this picture carry this card's idea. That is a judgement on a rendered
 * image, made fastest one at a time with two exits, and slowest in a grid of
 * forty.
 *
 * Design source of truth: docs/design/mockups/ascii-art-review/.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";

import { ApiError, api, type AsciiScene } from "@/lib/api";

type Verdict = "kept" | "sent";

interface Decision {
  index: number;
  verdict: Verdict;
}

/** How far a card must travel before the release counts as a decision. */
const COMMIT_PX = 120;

export default function AsciiArtReviewPage() {
  const params = useParams<{ topic: string }>();
  const topicSlug = params?.topic ?? "";

  const [scenes, setScenes] = useState<AsciiScene[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [i, setI] = useState(0);
  const [log, setLog] = useState<Decision[]>([]);
  const [edits, setEdits] = useState<Record<string, { art: string; alt: string }>>({});
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showSource, setShowSource] = useState(false);

  const grabX = useRef(0);

  useEffect(() => {
    if (!topicSlug) return;
    let live = true;
    api.adminAscii
      .list(topicSlug)
      .then((rows) => {
        if (live) setScenes(rows);
      })
      .catch((e) => {
        if (live) setErr(e instanceof ApiError ? e.message : String(e));
      });
    return () => {
      live = false;
    };
  }, [topicSlug]);

  const current = scenes && i < scenes.length ? scenes[i] : null;

  /** The card's art as it now stands: the operator's edit if there is one. */
  const liveArt = useMemo(() => {
    if (!current) return "";
    return edits[current.card_id]?.art ?? current.art;
  }, [current, edits]);

  const liveAlt = useMemo(() => {
    if (!current) return "";
    return edits[current.card_id]?.alt ?? current.alt;
  }, [current, edits]);

  const widest = useMemo(
    () => liveArt.split("\n").reduce((m, l) => Math.max(m, l.length), 0),
    [liveArt],
  );

  const decide = useCallback(
    async (verdict: Verdict) => {
      if (!current || busy) return;
      setBusy(true);
      setErr(null);
      try {
        if (verdict === "kept") {
          await api.adminAscii.keep(current.card_id, liveArt, liveAlt);
        } else {
          await api.adminAscii.reject(current.card_id);
        }
        setLog((l) => [...l, { index: i, verdict }]);
        setI((n) => n + 1);
        setDx(0);
      } catch (e) {
        // A failed write must NOT advance the stack -- the card would look
        // reviewed while still carrying the scene the operator rejected.
        setErr(e instanceof ApiError ? e.message : String(e));
        setDx(0);
      } finally {
        setBusy(false);
      }
    },
    [current, busy, liveArt, liveAlt, i],
  );

  /**
   * Steps the stack back one card WITHOUT undoing the server write. Keeping a
   * scene is idempotent, so re-deciding it is safe; a rejection already sits in
   * the repairs queue, which is where an operator would undo it. Saying that
   * here is better than implying this button reaches the database.
   */
  const stepBack = useCallback(() => {
    if (!log.length || busy) return;
    setI(log[log.length - 1].index);
    setLog((l) => l.slice(0, -1));
    setDx(0);
  }, [log, busy]);

  /**
   * Records an edit to the card currently on top. Seeded from what is on screen
   * so editing one field never blanks the other -- `edits` holds a whole
   * {art, alt} pair per card, and a partial patch would otherwise write
   * `undefined` into the half being left alone.
   */
  const setEdit = useCallback(
    (cardId: string, patch: Partial<{ art: string; alt: string }>) => {
      setEdits((e) => {
        const base = e[cardId] ?? { art: liveArt, alt: liveAlt };
        return { ...e, [cardId]: { ...base, ...patch } };
      });
    },
    [liveArt, liveAlt],
  );

  // -- keyboard -----------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target as HTMLElement | null)?.tagName ?? "";
      if (tag === "TEXTAREA" || tag === "INPUT") return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        void decide("kept");
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        void decide("sent");
      } else if (e.key === "u" || e.key === "U") {
        e.preventDefault();
        stepBack();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [decide, stepBack]);

  // -- drag ---------------------------------------------------------------
  useEffect(() => {
    if (!dragging) return;
    const move = (e: MouseEvent) => setDx(e.clientX - grabX.current);
    const up = () => {
      setDragging(false);
      setDx((d) => {
        if (d > COMMIT_PX) void decide("kept");
        else if (d < -COMMIT_PX) void decide("sent");
        return d > COMMIT_PX || d < -COMMIT_PX ? d : 0;
      });
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
    return () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    };
  }, [dragging, decide]);

  const kept = log.filter((l) => l.verdict === "kept").length;
  const sent = log.filter((l) => l.verdict === "sent").length;

  if (err && !scenes) {
    return (
      <div className="aa-page">
        <div className="aa-error">{err}</div>
      </div>
    );
  }
  if (!scenes) {
    return (
      <div className="aa-page">
        <div className="aa-lede">loading {topicSlug}…</div>
      </div>
    );
  }

  return (
    <div className="aa-page">
      <div className="aa-top">
        <h1>ascii art review</h1>
        <span className="aa-devtag">admin</span>
        <span className="aa-spacer" />
        <span className="aa-progress">
          {log.length} of {scenes.length} reviewed
        </span>
      </div>
      <p className="aa-lede">
        /admin/{topicSlug}/ascii-art · library art is copied verbatim; you are editing the composed
        scene
      </p>

      <div className="aa-rail">
        {scenes.map((s, n) => {
          const d = log.find((l) => l.index === n);
          return (
            <div
              key={s.card_id}
              className="aa-pip"
              data-verdict={d ? d.verdict : "none"}
              data-current={n === i ? "true" : "false"}
            />
          );
        })}
      </div>

      {err ? <div className="aa-error">{err}</div> : null}

      {current ? (
        <div className="aa-grid">
          <div className="aa-stack">
            <div className="aa-peek" style={{ transform: "translateY(16px) scale(0.972)", opacity: 0.5 }} />
            <div className="aa-peek" style={{ transform: "translateY(8px) scale(0.986)", opacity: 0.75 }} />

            <div
              className="aa-card"
              data-dragging={dragging ? "true" : "false"}
              style={{ transform: `translateX(${dx}px) rotate(${dx * 0.035}deg)` }}
              onMouseDown={(e) => {
                grabX.current = e.clientX;
                setDragging(true);
              }}
            >
              <div
                className="aa-wash"
                style={{
                  background: dx > 0 ? "var(--good)" : "var(--accent)",
                  opacity: Math.min(Math.abs(dx) / 380, 0.16),
                }}
              />

              <div className="aa-card-head">
                <div className="aa-card-titles">
                  <div className="aa-card-title">{current.title}</div>
                  <div className="aa-card-canon">{current.canonical_title}</div>
                </div>
                <span className="aa-chip">{current.difficulty}</span>
              </div>

              <div className="aa-ruler-row">
                <span className="aa-eyebrow">scene</span>
                <div className="aa-ruler">....|....10...|....20...|....30...|....40</div>
                <span className="aa-width" data-over={widest > current.max_width ? "true" : "false"}>
                  {widest > current.max_width
                    ? `${widest} cols — over budget`
                    : `${widest} / ${current.max_width} cols`}
                </span>
              </div>

              {/*
                The scene is ALWAYS editable and styled to be indistinguishable
                from the rendered art -- same font, size, line-height, padding,
                border and ground. There is no edit mode, so the picture never
                disappears to be edited and nothing swaps out from under the
                reviewer; they just type into it. `onMouseDown` stops the drag
                so selecting a run of text does not throw the card off the stack.
              */}
              <textarea
                className="aa-edit aa-art-edit"
                rows={Math.max(liveArt.split("\n").length, 8)}
                value={liveArt}
                spellCheck={false}
                onMouseDown={(e) => e.stopPropagation()}
                onChange={(e) => setEdit(current.card_id, { art: e.target.value })}
              />
              <div className="aa-editrow">
                {current.library_art ? (
                  <button
                    className="aa-btn"
                    data-active={showSource ? "true" : "false"}
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={() => setShowSource((v) => !v)}
                  >
                    {showSource ? "hide library original" : "library original"}
                  </button>
                ) : null}
                <span className="aa-hint">lines over 40 columns are flagged, never auto-cut</span>
              </div>
              {showSource && current.library_art ? (
                <pre className="aa-art aa-art-source">{current.library_art}</pre>
              ) : null}

              <div className="aa-meta">
                <div className="aa-meta-row">
                  <span className="aa-eyebrow aa-eyebrow-alt">alt</span>
                  <textarea
                    className="aa-edit aa-alt-edit"
                    rows={Math.max(Math.ceil(liveAlt.length / 64), 2)}
                    value={liveAlt}
                    placeholder="alt caption"
                    onMouseDown={(e) => e.stopPropagation()}
                    onChange={(e) => setEdit(current.card_id, { alt: e.target.value })}
                  />
                </div>
                <div className="aa-meta-row">
                  <span className="aa-eyebrow">src</span>
                  <span className="aa-src">{current.src_id ?? "— free-drawn (pre-ADR-0104)"}</span>
                  {current.library_title ? (
                    <span className="aa-src-title">{current.library_title}</span>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="aa-actions">
              <button className="aa-btn" data-tone="repair" disabled={busy} onClick={() => void decide("sent")}>
                ← send to repairs
              </button>
              <span className="aa-spacer" />
              <span className="aa-hint">drag the card, or</span>
              <span className="aa-kbd">←</span>
              <span className="aa-kbd">→</span>
              <span className="aa-kbd">U</span>
              <span className="aa-spacer" />
              <button className="aa-btn" data-tone="accept" disabled={busy} onClick={() => void decide("kept")}>
                keep as new →
              </button>
            </div>
          </div>

          <div className="aa-side">
            <div className="aa-panel">
              <div className="aa-side-h">what the swipes do</div>
              <div className="aa-side-body">
                <div className="aa-side-row">
                  <span className="aa-kbd" data-tone="accept">→</span>
                  <span>Writes the scene and the caption as they now stand back to the card. Both are live — just type in them.</span>
                </div>
                <div className="aa-side-row">
                  <span className="aa-kbd" data-tone="repair">←</span>
                  <span>
                    Files an <code>art</code> report, so the card shows up in{" "}
                    <a href="/admin/repairs">/admin/repairs</a>.
                  </span>
                </div>
                <div className="aa-side-row">
                  <span className="aa-kbd">U</span>
                  <span>Steps back a card. The write already landed — re-decide it here, or undo a rejection in repairs.</span>
                </div>
              </div>
            </div>

            <div className="aa-panel">
              <div className="aa-side-h">this session</div>
              <div className="aa-stats">
                <div><span>kept</span><span data-tone="accept">{kept}</span></div>
                <div><span>to repairs</span><span data-tone="repair">{sent}</span></div>
                <div><span>edited</span><span>{Object.keys(edits).length}</span></div>
                <div className="aa-stats-total"><span>remaining</span><span>{scenes.length - log.length}</span></div>
              </div>
            </div>

            {scenes.slice(i + 1, i + 4).length ? (
              <div className="aa-panel">
                <div className="aa-side-h">up next</div>
                <div className="aa-next">
                  {scenes.slice(i + 1, i + 4).map((s, n) => (
                    <div key={s.card_id} className="aa-next-row">
                      <span className="aa-next-num">{String(i + n + 2).padStart(2, "0")}</span>
                      <span className="aa-next-title">{s.title}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="aa-done">
          <pre>{"      /\\_/\\\n     ( -.- )   all reviewed.\n      > ^ <"}</pre>
          <div className="aa-done-h">
            {scenes.length ? "Nothing left in this topic" : "This topic has no ASCII scenes"}
          </div>
          <div className="aa-done-sub">
            {kept} kept · {sent} sent to repairs · {Object.keys(edits).length} edited
          </div>
          <div className="aa-done-actions">
            <button
              className="aa-btn"
              onClick={() => {
                setI(0);
                setLog([]);
              }}
            >
              review again
            </button>
            <a className="aa-btn" data-tone="repair" href="/admin/repairs">
              open /admin/repairs
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
