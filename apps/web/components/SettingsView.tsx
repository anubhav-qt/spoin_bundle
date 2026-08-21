"use client";

/**
 * Settings — a typeset control panel, not a dashboard.
 *
 * Structurally a document: section rules, a label/description/control row, and
 * nothing wrapped in its own floating card. It shares the `.collection-*`
 * masthead and rule vocabulary with Liked / Saved / Profile so it reads as the
 * same product rather than a bolted-on preferences screen.
 *
 * **Every row here maps to something that actually exists.** The sections the
 * brief sketched that this app has no machinery for are absent rather than
 * faked:
 *
 *   - Notifications — there is no delivery system of any kind in the codebase
 *     (no scheduler, no push registration, no mail transport), so a toggle
 *     would be a switch wired to nothing.
 *   - Change password / security — `password_hash` exists but no endpoint
 *     changes it; inventing one is authentication functionality, not settings.
 *   - Global difficulty — difficulty in Spoin is per-topic and progression
 *     driven (`DIFFICULTY_MIX`, ADR-0010, plus each topic's own tier). A
 *     global override would be a rewrite of feed selection wearing a
 *     settings-row costume, so difficulty is surfaced per topic instead.
 *   - Delete account — no endpoint, and CLAUDE.md gates destructive
 *     operations behind explicit approval.
 *
 * Two persistence layers, matching what each preference is:
 *   - Daily goal  -> server, via the existing PATCH /profile/me (it is
 *                    learning data and should follow the account).
 *   - Theme/font/motion -> localStorage + a <body> attribute, the pattern the
 *                    palette and font pickers already use.
 *
 * Serving layer only: one PATCH per goal change, one GET for export. No LLM.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api, type Topic } from "@/lib/api";
import { getReducedMotion, setReducedMotion, subscribeReducedMotion } from "@/lib/motionPreference";
import { useAuth } from "./AuthProvider";
import { FontPicker } from "./FontPicker";
import { ThemePicker } from "./ThemePicker";
import { TopicDiscoveryModal } from "./TopicDiscoveryModal";
import { ArrowIcon, CheckIcon } from "./icons";

/** Matches `daily_card_goal`'s server-side bounds (schemas.py, ge=1 le=200).
 *  The picker offers steps; the endpoint remains the authority. */
const GOAL_STEPS = [5, 10, 20, 30, 50] as const;

/** Both packages carry the same version (apps/web/package.json,
 *  apps/api/pyproject.toml). Read at build time rather than hardcoded twice. */
const VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "0.1.0";

type SaveState = "idle" | "saving" | "saved" | "error";

// ─── Row primitives ───────────────────────────────────────────────────────────

function Row({
  title,
  description,
  htmlFor,
  children,
}: {
  title: string;
  description?: string;
  /** Set when the control is a single labelable element, so the whole title
   *  acts as its label. Omitted for groups, which carry their own labelling. */
  htmlFor?: string;
  children: React.ReactNode;
}) {
  const Title = htmlFor ? "label" : "span";
  return (
    <div className="settings-row">
      <div className="settings-row-text">
        <Title className="settings-row-title" {...(htmlFor ? { htmlFor } : {})}>
          {title}
        </Title>
        {description ? <p className="settings-row-desc">{description}</p> : null}
      </div>
      <div className="settings-row-control">{children}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const id = `settings-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return (
    <section className="settings-section" aria-labelledby={id}>
      <h2 className="collection-section-title" id={id}>
        {title}
      </h2>
      <hr className="collection-rule" />
      <div className="settings-rows">{children}</div>
    </section>
  );
}

/** A read-only value, styled as a value rather than a disabled input — there
 *  is no endpoint to change it, and a greyed-out field implies otherwise. */
function ReadOnlyValue({ children, muted = false }: { children: React.ReactNode; muted?: boolean }) {
  return <span className="settings-value" data-muted={muted}>{children}</span>;
}

/** A real checkbox under the paint: it keeps the label association, the
 *  keyboard behaviour and the focus ring without re-implementing any of it. */
function Switch({
  id,
  checked,
  onChange,
  describedBy,
}: {
  id: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  describedBy?: string;
}) {
  return (
    <span className="settings-switch">
      <input
        id={id}
        type="checkbox"
        className="settings-switch-input"
        checked={checked}
        aria-describedby={describedBy}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="settings-switch-track" aria-hidden="true">
        <span className="settings-switch-thumb" />
      </span>
      {/* State in text, not colour alone. */}
      <span className="settings-switch-state" aria-hidden="true">
        {checked ? "ON" : "OFF"}
      </span>
    </span>
  );
}

// ─── View ─────────────────────────────────────────────────────────────────────

interface Props {
  topics: Topic[];
  onNavigateProfile: () => void;
  /** AppShell owns the followed-topics list; following from here has to tell
   *  it, or the rails go stale until a reload. */
  onTopicFollowed: (topic: Topic) => void;
}

export function SettingsView({ topics, onNavigateProfile, onTopicFollowed }: Props) {
  const { user, applyUser } = useAuth();

  const [goal, setGoal] = useState<number>(user?.daily_card_goal ?? 10);
  const [goalState, setGoalState] = useState<SaveState>("idle");
  const [goalError, setGoalError] = useState("");

  const [motion, setMotion] = useState(false);
  const [topicsOpen, setTopicsOpen] = useState(false);

  const [exportState, setExportState] = useState<SaveState>("idle");
  const [exportError, setExportError] = useState("");

  // Read after mount: the attribute is set by a pre-hydration script, so
  // reading it during render would disagree with the server's markup.
  useEffect(() => {
    setMotion(getReducedMotion());
    return subscribeReducedMotion(() => setMotion(getReducedMotion()));
  }, []);

  useEffect(() => {
    if (user?.daily_card_goal !== undefined) setGoal(user.daily_card_goal);
  }, [user?.daily_card_goal]);

  const chooseGoal = useCallback(
    async (next: number) => {
      const previous = goal;
      // Optimistic: the pills are the feedback, so they move first and roll
      // back if the write fails. No page reload, no spinner over the control.
      setGoal(next);
      setGoalState("saving");
      setGoalError("");
      try {
        applyUser(await api.updateProfile({ daily_card_goal: next }));
        setGoalState("saved");
      } catch (cause) {
        setGoal(previous);
        setGoalState("error");
        setGoalError(cause instanceof ApiError ? cause.message : "Couldn't save that.");
      }
    },
    [goal, applyUser],
  );

  // Clear the "saved" tick after a beat; errors stay until the next attempt.
  useEffect(() => {
    if (goalState !== "saved") return;
    const timer = setTimeout(() => setGoalState("idle"), 1600);
    return () => clearTimeout(timer);
  }, [goalState]);

  const runExport = async () => {
    if (exportState === "saving") return;
    setExportState("saving");
    setExportError("");
    try {
      const data = await api.exportData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `spoin-export-${data.exported_at.slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setExportState("saved");
    } catch (cause) {
      setExportState("error");
      setExportError(cause instanceof ApiError ? cause.message : "Couldn't build your export.");
    }
  };

  useEffect(() => {
    if (exportState !== "saved") return;
    const timer = setTimeout(() => setExportState("idle"), 2400);
    return () => clearTimeout(timer);
  }, [exportState]);

  if (!user) return null;

  return (
    <div className="collection-view settings-view">
      <header className="collection-header">
        <p className="collection-eyebrow">SETTINGS</p>
        <h1 className="collection-title">Tune Spoin to how you read.</h1>
      </header>

      <hr className="collection-rule" />

      {/* ── ACCOUNT ──────────────────────────────────────────────────────── */}
      <Section title="ACCOUNT">
        <Row title="Profile" description="Your name, avatar, and the rest of your details.">
          <button type="button" className="settings-link" onClick={onNavigateProfile}>
            OPEN
            <span className="settings-link-icon">
              <ArrowIcon />
            </span>
          </button>
        </Row>

        <Row
          title="Email"
          description={
            user.is_guest
              ? "This session is a guest account. Sign up to keep it."
              : "Sign-in address. Changing it isn't supported yet."
          }
        >
          <ReadOnlyValue muted={user.is_guest}>{user.email ?? "NO EMAIL"}</ReadOnlyValue>
        </Row>
      </Section>

      {/* ── LEARNING ─────────────────────────────────────────────────────── */}
      <Section title="LEARNING">
        <Row title="Daily goal" description="Cards you're aiming to read each day.">
          <div className="settings-choice" role="radiogroup" aria-label="Daily card goal">
            {GOAL_STEPS.map((step) => (
              <button
                key={step}
                type="button"
                role="radio"
                aria-checked={goal === step}
                className="collection-pill settings-choice-pill"
                data-active={goal === step}
                disabled={goalState === "saving"}
                onClick={() => void chooseGoal(step)}
              >
                {step}
              </button>
            ))}
            <span className="settings-feedback" role="status">
              {goalState === "saving" ? (
                <span className="settings-feedback-text">SAVING</span>
              ) : goalState === "saved" ? (
                <>
                  <span className="settings-feedback-icon">
                    <CheckIcon />
                  </span>
                  <span className="settings-feedback-text">SAVED</span>
                </>
              ) : null}
            </span>
          </div>
          {goalError ? <p className="settings-error">{goalError}</p> : null}
        </Row>

        <Row
          title="Difficulty"
          description="Set per topic, not globally — each topic advances on its own as you cover it."
        >
          <button type="button" className="settings-link" onClick={onNavigateProfile}>
            {topics.length} {topics.length === 1 ? "TOPIC" : "TOPICS"}
          </button>
        </Row>

        <Row title="Topics" description="Browse the corpus and follow what you want in your feed.">
          <button type="button" className="settings-link" onClick={() => setTopicsOpen(true)}>
            MANAGE
            <span className="settings-link-icon">
              <ArrowIcon />
            </span>
          </button>
        </Row>
      </Section>

      {/* ── APPEARANCE ───────────────────────────────────────────────────── */}
      <Section title="APPEARANCE">
        <Row title="Palette" description="Five grounds. Or mix your own.">
          <ThemePicker />
        </Row>

        <Row title="Reading face" description="The type the cards are set in.">
          <FontPicker />
        </Row>

        <Row
          title="Reduced motion"
          description="Cut animations and transitions. Your system setting is always respected on its own."
          htmlFor="settings-reduced-motion"
        >
          <Switch
            id="settings-reduced-motion"
            checked={motion}
            onChange={(next) => setReducedMotion(next)}
          />
        </Row>
      </Section>

      {/* ── DATA ─────────────────────────────────────────────────────────── */}
      <Section title="DATA">
        <Row
          title="Export your data"
          description="Your topics, notes, likes, saves and activity, as one JSON file."
        >
          <button
            type="button"
            className="settings-link"
            onClick={() => void runExport()}
            disabled={exportState === "saving"}
          >
            {exportState === "saving" ? "BUILDING…" : exportState === "saved" ? "DOWNLOADED" : "EXPORT"}
            {exportState === "idle" || exportState === "error" ? (
              <span className="settings-link-icon">
                <ArrowIcon />
              </span>
            ) : null}
          </button>
          {exportError ? <p className="settings-error">{exportError}</p> : null}
        </Row>
      </Section>

      {/* ── ABOUT ────────────────────────────────────────────────────────── */}
      <Section title="ABOUT">
        <Row title="Spoin" description="Made for curious people.">
          <ReadOnlyValue>VERSION {VERSION}</ReadOnlyValue>
        </Row>
      </Section>

      {topicsOpen ? (
        <TopicDiscoveryModal
          onClose={() => setTopicsOpen(false)}
          onFollowed={onTopicFollowed}
        />
      ) : null}
    </div>
  );
}
