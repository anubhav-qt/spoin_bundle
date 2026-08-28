"use client";

/**
 * The learning journal — not an account-settings screen.
 *
 * Reads top to bottom as one argument about the user's own consistency:
 *
 *   IDENTITY   who this is
 *   MOMENTUM   the streak, as a quiet figure rather than a trophy
 *   HISTORY    the month's shape (calendar grid + daily trend)
 *   TOTALS     the all-time numbers, deliberately last and smallest
 *
 * Shares the masthead / section / state vocabulary with Liked and Saved via
 * the `.collection-*` layer in globals.css — the three pages are one product,
 * so none of them owns a private copy of a header or an error state.
 *
 * **Every figure on this page is computed from data the API already returned.**
 * `/profile/me/stats` gives all-time totals plus one month of daily counts;
 * anything month-scoped here (cards this month, active days, busiest day) is
 * derived from `monthly_activity` client-side over at most 31 rows. Nothing is
 * estimated, projected or rounded into a nicer-sounding number, and there is
 * no second request — the brief's "never fabricate insights" is a hard line.
 *
 * Performance contract, same as the feed: no LLM calls, no generation. One GET
 * per month viewed, plus one authenticated fetch for the avatar image.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { type ProfileStatsOut, type User, api } from "@/lib/api";
import { useRefreshEffect } from "@/lib/refresh";
import { AvatarMark } from "./icons";
import { useAuth } from "./AuthProvider";
import { EditProfileModal } from "./EditProfileModal";

const WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] as const;

const MONTHS = [
  "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
  "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
] as const;

/** Four filled steps + empty. Thresholds are deliberately low: this is a
 *  reading app, not a commit log — 10 cards in a day is a heavy session. */
function intensityOf(cards: number): 0 | 1 | 2 | 3 | 4 {
  if (cards <= 0) return 0;
  if (cards <= 2) return 1;
  if (cards <= 5) return 2;
  if (cards <= 10) return 3;
  return 4;
}

function initialsOf(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "??";
  if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function plural(n: number, one: string, many: string) {
  return n === 1 ? one : many;
}

// ─── Avatar ───────────────────────────────────────────────────────────────────

/** Resolves the avatar image through an authenticated fetch (see
 *  `api.avatarObjectUrl`) and revokes the object URL on teardown. `version`
 *  is bumped by the parent after a save so a fresh upload re-resolves without
 *  a cache-busting query param in the render path. */
function useAvatarUrl(hasImage: boolean | undefined, version: number) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!hasImage) {
      setUrl(null);
      return;
    }
    let revoked = false;
    let objectUrl: string | null = null;

    void api
      .avatarObjectUrl()
      .then((next) => {
        if (revoked) {
          URL.revokeObjectURL(next);
          return;
        }
        objectUrl = next;
        setUrl(next);
      })
      // A failed avatar fetch falls back to the mark/initials below it. It is
      // never worth an error state of its own on this page.
      .catch(() => setUrl(null));

    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [hasImage, version]);

  return url;
}

// ─── Contribution grid ────────────────────────────────────────────────────────

interface GridProps {
  year: number;
  month: number; // 1-indexed
  byDate: Map<string, number>;
  selectedDay: number | null;
  onSelect: (day: number | null) => void;
}

function ContributionGrid({ year, month, byDate, selectedDay, onSelect }: GridProps) {
  const gridRef = useRef<HTMLDivElement>(null);

  const daysInMonth = new Date(year, month, 0).getDate();
  // JS weeks start Sunday; the grid starts Monday.
  const startOffset = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const cellCount = Math.ceil((startOffset + daysInMonth) / 7) * 7;

  // Roving tabindex: the grid is ONE tab stop, arrows move within it. 31
  // sequential tab stops between the month nav and the rest of the page would
  // make keyboard traversal of this page unusable.
  const [focusedDay, setFocusedDay] = useState(1);
  const activeDay = selectedDay ?? focusedDay;

  const countFor = (day: number) =>
    byDate.get(`${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`) ?? 0;

  const moveFocus = (day: number) => {
    const clamped = Math.min(Math.max(day, 1), daysInMonth);
    setFocusedDay(clamped);
    gridRef.current
      ?.querySelector<HTMLButtonElement>(`[data-day="${clamped}"]`)
      ?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent, day: number) => {
    const delta =
      event.key === "ArrowRight" ? 1
      : event.key === "ArrowLeft" ? -1
      : event.key === "ArrowDown" ? 7
      : event.key === "ArrowUp" ? -7
      : 0;

    if (delta !== 0) {
      event.preventDefault();
      moveFocus(day + delta);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      moveFocus(1);
    } else if (event.key === "End") {
      event.preventDefault();
      moveFocus(daysInMonth);
    }
  };

  return (
    <div className="contrib">
      <div className="contrib-weekdays" aria-hidden="true">
        {WEEKDAYS.map((d) => (
          <span key={d}>{d.charAt(0)}</span>
        ))}
      </div>

      <div
        ref={gridRef}
        className="contrib-grid"
        role="group"
        aria-label={`Daily activity for ${MONTHS[month - 1]} ${year}`}
      >
        {Array.from({ length: cellCount }, (_, i) => {
          const day = i - startOffset + 1;
          if (day < 1 || day > daysInMonth) {
            return <span key={`pad-${i}`} className="contrib-cell is-pad" aria-hidden="true" />;
          }

          const count = countFor(day);
          const selected = selectedDay === day;

          return (
            <button
              key={day}
              type="button"
              data-day={day}
              className="contrib-cell"
              data-level={intensityOf(count)}
              data-selected={selected}
              tabIndex={day === activeDay ? 0 : -1}
              aria-pressed={selected}
              // Carries the number, so the grid never depends on colour alone.
              aria-label={`${MONTHS[month - 1].slice(0, 3)} ${day} — ${count} ${plural(count, "card", "cards")} read`}
              onFocus={() => setFocusedDay(day)}
              onKeyDown={(e) => onKeyDown(e, day)}
              onClick={() => onSelect(selected ? null : day)}
            >
              <span className="contrib-cell-day" aria-hidden="true">{day}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─── Daily trend ──────────────────────────────────────────────────────────────

/** The month's daily counts as a baseline-anchored bar strip. Same numbers as
 *  the grid above, read along a different axis: the grid answers "which days
 *  of the week do I show up", this answers "was the month steady or spiky".
 *  No y-axis, no gridlines — the peak is labelled and that is the only
 *  magnitude a reader needs here. */
function TrendStrip({
  year,
  month,
  byDate,
  selectedDay,
  onSelect,
}: {
  year: number;
  month: number;
  byDate: Map<string, number>;
  selectedDay: number | null;
  onSelect: (day: number | null) => void;
}) {
  const daysInMonth = new Date(year, month, 0).getDate();
  const counts = Array.from({ length: daysInMonth }, (_, i) => {
    const day = i + 1;
    return byDate.get(`${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`) ?? 0;
  });
  const peak = Math.max(...counts, 0);

  if (peak === 0) return null;

  return (
    <div className="trend">
      <div className="trend-plot" role="group" aria-label="Daily totals across the month">
        {counts.map((count, i) => {
          const day = i + 1;
          return (
            <button
              key={day}
              type="button"
              className="trend-bar"
              data-selected={selectedDay === day}
              data-empty={count === 0}
              style={{ "--h": `${peak === 0 ? 0 : (count / peak) * 100}%` } as React.CSSProperties}
              aria-label={`${MONTHS[month - 1].slice(0, 3)} ${day} — ${count} ${plural(count, "card", "cards")} read`}
              onClick={() => onSelect(selectedDay === day ? null : day)}
              tabIndex={-1}
            />
          );
        })}
      </div>
      <div className="trend-axis" aria-hidden="true">
        <span>01</span>
        <span className="trend-peak">PEAK {peak}</span>
        <span>{String(daysInMonth).padStart(2, "0")}</span>
      </div>
    </div>
  );
}

// ─── Main view ────────────────────────────────────────────────────────────────

export function ProfileView() {
  const { user, applyUser, logout } = useAuth();

  const [stats, setStats] = useState<ProfileStatsOut | null>(null);
  const [error, setError] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [avatarVersion, setAvatarVersion] = useState(0);

  // Anchored once per mount so "is this the current month?" can't drift while
  // the page sits open, and so the render is not a function of Date.now().
  const [cursor, setCursor] = useState(() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() + 1 };
  });
  const today = useMemo(() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() + 1 };
  }, []);

  const { year, month } = cursor;
  const avatarUrl = useAvatarUrl(user?.has_avatar_image, avatarVersion);

  const load = useCallback(() => {
    setError(false);
    setStats(null);
    api
      .getProfileStats(year, month)
      .then(setStats)
      .catch(() => setError(true));
  }, [year, month]);

  useEffect(() => {
    if (!user) return;
    load();
  }, [user, load]);

  // Manual refresh, or an invalidation from elsewhere (a quiz pass moving
  // the streak, say) — re-fetches the currently viewed month.
  useRefreshEffect("profile", load);

  // Selecting a day is scoped to the month it was selected in.
  useEffect(() => setSelectedDay(null), [year, month]);

  const byDate = useMemo(
    () => new Map((stats?.monthly_activity ?? []).map((a) => [a.date, a.cards_read])),
    [stats],
  );

  /** Month-scoped figures, all summed from `monthly_activity` — see the file
   *  header. `activeDays` is the row count because the API only returns days
   *  that actually have events. */
  const monthFigures = useMemo(() => {
    const rows = stats?.monthly_activity ?? [];
    const cards = rows.reduce((sum, r) => sum + r.cards_read, 0);
    const busiest = rows.reduce<{ date: string; cards_read: number } | null>(
      (best, r) => (best === null || r.cards_read > best.cards_read ? r : best),
      null,
    );
    return { cards, activeDays: rows.length, busiest };
  }, [stats]);

  const isCurrentMonth = year === today.year && month === today.month;

  const stepMonth = (delta: -1 | 1) => {
    setCursor((c) => {
      const next = new Date(c.year, c.month - 1 + delta, 1);
      const ny = next.getFullYear();
      const nm = next.getMonth() + 1;
      if (ny > today.year || (ny === today.year && nm > today.month)) return c;
      return { year: ny, month: nm };
    });
  };

  const handleUserChanged = (next: User) => {
    applyUser(next);
    // Re-resolves the avatar object URL — the bytes behind
    // /profile/me/avatar/image changed even though its URL did not.
    setAvatarVersion((v) => v + 1);
  };

  if (!user) return null;

  const monthLabel = `${MONTHS[month - 1]} ${year}`;
  const selectedCount =
    selectedDay === null
      ? null
      : byDate.get(
          `${year}-${String(month).padStart(2, "0")}-${String(selectedDay).padStart(2, "0")}`,
        ) ?? 0;

  return (
    <div className="collection-view profile-view">
      {/* ── IDENTITY ─────────────────────────────────────────────────────── */}
      <header className="collection-header profile-identity">
        <div className="profile-identity-text">
          <p className="collection-eyebrow">PROFILE</p>
          <h1 className="collection-title">{user.display_name}</h1>
          <p className="collection-meta">
            {[
              user.age ? `${user.age} YEARS` : null,
              user.gender ? user.gender.toUpperCase() : null,
              user.is_guest ? "GUEST ACCOUNT" : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>

        <div className="profile-avatar" data-empty={!avatarUrl && !user.avatar_icon}>
          {avatarUrl ? (
            <img src={avatarUrl} alt="" />
          ) : user.avatar_icon ? (
            <span className="profile-avatar-mark">
              <AvatarMark mark={user.avatar_icon} />
            </span>
          ) : (
            <span className="profile-avatar-initials">{initialsOf(user.display_name)}</span>
          )}
        </div>
      </header>

      {/* Profile is the only account surface reachable from every viewport —
          `Sidebar` carries the same two controls but is `display:none` below
          900px, which left phone and tablet users with no way out of a
          session at all. Same actions, same `logout` from AuthProvider; the
          rail keeps its copy for the desktop muscle memory. */}
      <div className="collection-controls profile-identity-actions">
        <button type="button" className="collection-action" onClick={() => setIsEditing(true)}>
          EDIT PROFILE
        </button>
        {user.is_guest ? (
          <Link href="/claim" className="collection-action">
            SIGN UP
          </Link>
        ) : (
          <button type="button" className="collection-action collection-action-danger" onClick={logout}>
            LOG OUT
          </button>
        )}
      </div>

      <hr className="collection-rule" />

      {/* ── Error / loading ──────────────────────────────────────────────── */}
      {error ? (
        <div className="collection-state">
          <p className="collection-state-head">COULDN&apos;T LOAD YOUR ACTIVITY</p>
          <p className="collection-state-body">
            Your profile is fine — the numbers just didn&apos;t arrive.
          </p>
          <button type="button" className="collection-cta" onClick={load}>
            TRY AGAIN
          </button>
        </div>
      ) : stats === null ? (
        <div className="profile-skeleton" aria-hidden="true">
          <div className="profile-skeleton-figure" />
          <div className="profile-skeleton-grid" />
        </div>
      ) : (
        <>
          {/* ── MOMENTUM ─────────────────────────────────────────────────── */}
          <section className="profile-section" aria-labelledby="profile-momentum">
            <h2 className="collection-section-title" id="profile-momentum">
              MOMENTUM
            </h2>

            <div className="profile-momentum">
              <p className="profile-figure profile-figure-lead">
                <span className="profile-figure-value" data-quiet={stats.current_streak === 0}>
                  {stats.current_streak}
                </span>
                <span className="profile-figure-label">
                  {plural(stats.current_streak, "DAY STREAK", "DAY STREAK")}
                </span>
              </p>

              <p className="profile-narrative">
                {stats.current_streak === 0
                  ? "No streak running. One card today starts a new one."
                  : stats.current_streak === 1
                    ? "One day so far."
                    : `You've read something ${stats.current_streak} days running.`}
              </p>

              {stats.longest_streak > stats.current_streak ? (
                <p className="profile-aside">
                  BEST · {stats.longest_streak} {plural(stats.longest_streak, "DAY", "DAYS")}
                </p>
              ) : null}
            </div>
          </section>

          <hr className="collection-rule" />

          {/* ── HISTORY ──────────────────────────────────────────────────── */}
          <section className="profile-section" aria-labelledby="profile-history">
            <div className="profile-month-nav">
              <h2 className="collection-section-title" id="profile-history">
                {monthLabel}
              </h2>
              <div className="profile-month-steppers">
                <button
                  type="button"
                  className="profile-step"
                  onClick={() => stepMonth(-1)}
                  aria-label="Previous month"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 5.5 8 12l6.5 6.5" /></svg>
                </button>
                <button
                  type="button"
                  className="profile-step"
                  onClick={() => stepMonth(1)}
                  disabled={isCurrentMonth}
                  aria-label="Next month"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 5.5 16 12l-6.5 6.5" /></svg>
                </button>
              </div>
            </div>

            {monthFigures.cards > 0 ? (
              <p className="profile-narrative">
                {monthFigures.cards} {plural(monthFigures.cards, "card", "cards")} across{" "}
                {monthFigures.activeDays} {plural(monthFigures.activeDays, "day", "days")}
                {monthFigures.busiest && monthFigures.activeDays > 1
                  ? ` · busiest was ${MONTHS[month - 1].slice(0, 3)} ${Number(monthFigures.busiest.date.slice(8, 10))}`
                  : ""}
                .
              </p>
            ) : (
              <p className="profile-narrative profile-narrative-quiet">
                Nothing recorded {isCurrentMonth ? "yet this month" : "this month"}.
              </p>
            )}

            <ContributionGrid
              year={year}
              month={month}
              byDate={byDate}
              selectedDay={selectedDay}
              onSelect={setSelectedDay}
            />

            {/* Readout doubles as the touch-friendly replacement for hover. */}
            <p className="contrib-readout" role="status">
              {selectedDay === null ? (
                <span className="contrib-readout-hint">
                  Select a day for its count
                </span>
              ) : (
                <>
                  <span className="contrib-readout-date">
                    {MONTHS[month - 1].slice(0, 3)} {selectedDay}
                  </span>
                  <span className="contrib-readout-sep">·</span>
                  <span className="contrib-readout-count">
                    {selectedCount} {plural(selectedCount ?? 0, "CARD", "CARDS")} READ
                  </span>
                </>
              )}
            </p>

            <div className="contrib-legend" aria-hidden="true">
              <span className="contrib-legend-label">NONE</span>
              {[0, 1, 2, 3, 4].map((level) => (
                <span key={level} className="contrib-cell is-legend" data-level={level} />
              ))}
              <span className="contrib-legend-label">10+</span>
            </div>

            <TrendStrip
              year={year}
              month={month}
              byDate={byDate}
              selectedDay={selectedDay}
              onSelect={setSelectedDay}
            />
          </section>

          <hr className="collection-rule" />

          {/* ── TOTALS ───────────────────────────────────────────────────── */}
          <section className="profile-section" aria-labelledby="profile-totals">
            <h2 className="collection-section-title" id="profile-totals">
              ALL TIME
            </h2>
            <div className="profile-totals">
              <p className="profile-figure">
                <span className="profile-figure-value">{stats.total_cards_read}</span>
                <span className="profile-figure-label">
                  {plural(stats.total_cards_read, "CARD READ", "CARDS READ")}
                </span>
              </p>
              <p className="profile-figure">
                <span className="profile-figure-value">{stats.total_topics}</span>
                <span className="profile-figure-label">
                  {plural(stats.total_topics, "TOPIC EXPLORED", "TOPICS EXPLORED")}
                </span>
              </p>
            </div>
          </section>
        </>
      )}

      {isEditing && (
        <EditProfileModal
          user={user}
          onClose={() => setIsEditing(false)}
          onUserChanged={handleUserChanged}
        />
      )}
    </div>
  );
}
