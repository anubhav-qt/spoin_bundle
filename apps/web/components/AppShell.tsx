"use client";

/**
 * Owns everything the three-column shell needs to share across columns: which
 * topics the user follows, their progress, and which are currently filtered to.
 *
 * This used to live inside Feed.tsx, back when the topic rail was part of the
 * feed's own masthead. Now the right rail's TopicRail and InsightsPanel both
 * need the same state, so it moved up one level. Feed itself keeps everything
 * that is purely about the card thread.
 */

import { useCallback, useEffect, useState } from "react";
import { flushSync } from "react-dom";
import { MotionConfig } from "framer-motion";

import { api, type DailyGoalOut, type Difficulty, type Topic } from "@/lib/api";
import { engagement } from "@/lib/engagement";
import { getReducedMotion, subscribeReducedMotion } from "@/lib/motionPreference";
import { invalidate } from "@/lib/refresh";
import type { TopicProgress } from "@/lib/types";
import { CustomCursor } from "./CustomCursor";
import { Feed } from "./Feed";
import { FocusToggle } from "./FocusToggle";
import { GuestNotice } from "./GuestNotice";
import { LikedView } from "./LikedView";
import { MobileTopBar } from "./MobileTopBar";
import { NotesView } from "./NotesView";
import { ProfileView } from "./ProfileView";
import { RightRail } from "./RightRail";
import { SavedView } from "./SavedView";
import { SettingsView } from "./SettingsView";
import { Sidebar, type ShellView } from "./Sidebar";
import { TopicRail } from "./TopicRail";
import { UndoToast } from "./UndoToast";

function toTopicProgress(p: {
  current_difficulty: Difficulty;
  coverage: number;
  quiz_unlocked: boolean;
  mastered: boolean;
  tier_quiz_passed: boolean[];
}): TopicProgress {
  return {
    currentDifficulty: p.current_difficulty,
    coverage: p.coverage,
    quizUnlocked: p.quiz_unlocked,
    mastered: p.mastered,
    quizTiersPassed: p.tier_quiz_passed.filter(Boolean).length,
  };
}

export function AppShell() {
  const [topics, setTopics] = useState<Topic[]>([]);
  // Settings' reduced-motion switch. CSS covers transitions and keyframes, but
  // Framer Motion drives its animations through per-frame inline styles that
  // no stylesheet rule can reach — MotionConfig is the only way in. Read after
  // mount: the attribute is applied by a pre-hydration script, so reading it
  // during render would disagree with the server's markup.
  const [reducedMotion, setReducedMotionState] = useState(false);
  const [progress, setProgress] = useState<Record<string, TopicProgress>>({});
  const [selected, setSelected] = useState<string[]>([]);
  // The right rail's daily-goal ring. Starts at the DB default (0 of 10)
  // rather than `null`, so the ring renders immediately as an empty track
  // instead of popping in once `/profile/me/today` resolves.
  const [dailyGoal, setDailyGoal] = useState<DailyGoalOut>({ cards_read: 0, goal: 10 });
  // Session-local, not server state: which cards have been marked seen so
  // far, so InsightsPanel can show a count that only grows once per card
  // even if a card gets marked seen more than once in a session.
  const [readCardIds, setReadCardIds] = useState<Set<string>>(new Set());
  // Hides both rails, leaving just the feed. Neither rail carries state
  // worth preserving across the toggle, so this is plain UI state — not
  // persisted, not lifted any further than it needs to be.
  const [focusMode, setFocusMode] = useState(false);
  // Below 1150px, `.rail-right` stops rendering inline and becomes a sheet
  // (slide-over on tablet, bottom sheet on phone) that this toggles. Above
  // that width the CSS ignores `data-open` entirely and keeps the rail
  // always visible inline, so this state simply never gets set there — the
  // trigger button that flips it is itself CSS-hidden on desktop.
  const [railOpen, setRailOpen] = useState(false);
  // Bumped on every dev-reset (Sidebar's wordmark easter egg) and used as a
  // `key` on Feed/RightRail below — the simplest correct way to guarantee
  // every bit of client-side state derived from the old server state (feed
  // position, Discover's fetched list, in-flight card sets) gets thrown away
  // rather than trying to individually invalidate each one.
  const [resetCount, setResetCount] = useState(0);
  const [view, setView] = useState<ShellView>("feed");
  // Every one of Home/Notes/Liked/Saved/Profile/Settings fetches once, the
  // first time the user actually opens it, and then stays mounted (hidden,
  // not unmounted) for the rest of the session — see the render below.
  // Switching between them is a pure visibility toggle, no refetch; the only
  // things that DO trigger a refetch are the header's refresh control and
  // lib/refresh's invalidation calls after a mutation (see Feed/NotesView/
  // LikedView/SavedView/ProfileView's `useRefreshEffect`).
  const [visited, setVisited] = useState<ReadonlySet<ShellView>>(() => new Set(["feed"]));
  useEffect(() => {
    setVisited((current) => (current.has(view) ? current : new Set(current).add(view)));
  }, [view]);

  const loadTopics = useCallback(async () => {
    const list = await api.topics();
    setTopics(list);

    const entries = await Promise.all(
      list.map(async (topic) => {
        const p = await api.progress(topic.id);
        return [topic.id, toTopicProgress(p)] as const;
      }),
    );
    setProgress(Object.fromEntries(entries));
  }, []);

  useEffect(() => {
    void loadTopics();
  }, [loadTopics]);

  const refreshProgress = useCallback(async (topicId: string) => {
    const p = await api.progress(topicId);
    setProgress((current) => ({ ...current, [topicId]: toTopicProgress(p) }));
  }, []);

  const refreshDailyGoal = useCallback(async () => {
    setDailyGoal(await api.getTodayProgress());
  }, []);

  useEffect(() => {
    void refreshDailyGoal();
  }, [refreshDailyGoal]);

  // Called when a card gets marked seen, so InsightsPanel's session count and
  // the topic's progress both reflect it immediately instead of only as of
  // the last full page load.
  //
  // The seen-triggering event (dwell_complete/explicit_complete) is sent via
  // `lib/engagement`'s fire-and-forget buffer, not awaited by Card.tsx before
  // it calls this. Fetching `/topics/{id}/progress` right away used to race
  // that write: the GET would frequently land and resolve before the POST
  // had been processed, so the coverage bar read back the OLD number and
  // only self-corrected on a full reload minutes later (by which point the
  // write had long since landed). Waiting on `engagement.whenIdle()` first
  // sequences this refetch after that write actually completes, without
  // making the read itself synchronous with the write (ADR-0011's "don't
  // read your own writes" is about ranking/serving decisions, not this kind
  // of explicit, idempotent "refresh what I just did" UI action).
  const onCardSeen = useCallback(
    (cardId: string, topicId: string) => {
      setReadCardIds((current) => {
        if (current.has(cardId)) return current;
        const next = new Set(current).add(cardId);
        void engagement.whenIdle().then(() => {
          void refreshProgress(topicId);
          void refreshDailyGoal();
        });
        return next;
      });
    },
    [refreshProgress, refreshDailyGoal],
  );

  // Both rails swap for entirely different DOM (rail <-> empty spacer, and
  // FocusToggle jumps from inline to fixed-position) when this flips, so a
  // plain CSS transition can't bridge it — there's nothing shared to
  // interpolate between. A View Transition snapshots before/after and
  // cross-fades the two, which works across that kind of structural swap.
  // Falls back to an instant flip on browsers without support.
  const setFocusModeAnimated = useCallback((next: boolean) => {
    if (typeof document === "undefined" || !("startViewTransition" in document)) {
      setFocusMode(next);
      return;
    }
    // The feed keeps mutating DOM on its own (Framer Motion's layout
    // animations, IntersectionObserver-driven focus changes) independent of
    // this toggle, which can abort an in-flight transition's snapshot —
    // the browser then rejects `.ready`/`.finished` with InvalidStateError.
    // The rail swap itself already completed by then; this is a best-effort
    // cosmetic transition, so a rejection here is expected and safe to drop
    // rather than surfacing as an unhandled rejection.
    const transition = document.startViewTransition(() => {
      flushSync(() => setFocusMode(next));
    });
    transition.ready.catch(() => {});
    transition.finished.catch(() => {});
  }, []);

  const toggleTopic = (topicId: string) => {
    setSelected((current) =>
      current.includes(topicId) ? current.filter((id) => id !== topicId) : [...current, topicId],
    );
  };

  // Called after a successful follow (from RequestTopicBox or
  // TopicDiscoveryModal), so the newly-subscribed topic shows up in the
  // filter/progress box without a full reload.
  const onFollowed = useCallback(async (topic: Topic) => {
    setTopics((current) => (current.some((t) => t.id === topic.id) ? current : [...current, topic]));
    const p = await api.progress(topic.id);
    setProgress((current) => ({ ...current, [topic.id]: toTopicProgress(p) }));
    invalidate("feed");
  }, []);

  // TopicStatsModal's color picker (ADR-0034) calls this after a successful
  // PATCH — updates the local topics list so the feed re-renders that
  // topic's cards with the new hue immediately, no full reload.
  const onTopicColorChanged = useCallback((topicId: string, accentHue: number | null) => {
    setTopics((current) => current.map((t) => (t.id === topicId ? { ...t, accent_hue: accentHue } : t)));
  }, []);

  // Drops a topic from every piece of local state that mirrors the server's
  // subscription list, mirroring `onFollowed` in reverse -- the shared tail
  // end of both an explicit unfollow and a cancelled generation request
  // (GenerationProgressPanel), which has already removed the subscription
  // server-side itself and just needs the client to catch up.
  const removeTopicLocally = useCallback((topicId: string) => {
    setTopics((current) => current.filter((t) => t.id !== topicId));
    setProgress((current) => {
      const { [topicId]: _removed, ...rest } = current;
      return rest;
    });
    setSelected((current) => current.filter((id) => id !== topicId));
    invalidate("feed");
  }, []);

  // Called after a successful unfollow (TopicsProgressBox's modal).
  const onUnfollowed = useCallback(
    async (topicId: string) => {
      await api.unsubscribeTopic(topicId);
      removeTopicLocally(topicId);
    },
    [removeTopicLocally],
  );

  const onReset = useCallback(async () => {
    const list = await api.resetDemo();
    setTopics(list);
    const entries = await Promise.all(
      list.map(async (topic) => {
        const p = await api.progress(topic.id);
        return [topic.id, toTopicProgress(p)] as const;
      }),
    );
    setProgress(Object.fromEntries(entries));
    setSelected([]);
    setReadCardIds(new Set());
    setResetCount((count) => count + 1);
    // Every view's server-backed data is gone, not just the feed's — Notes/
    // Liked/Saved/Profile need to refetch next time they're looked at too.
    invalidate("all");
  }, []);

  const onRefresh = useCallback(() => {
    invalidate(view);
  }, [view]);

  // The rail sheet closes itself on navigation -- switching views while it's
  // open would otherwise leave it floating over the new view with no
  // relevance to what's now on screen.
  const navigateAndCloseRail = useCallback((next: ShellView) => {
    setView(next);
    setRailOpen(false);
  }, []);

  // Entering focus mode unmounts both `RightRail` and `MobileTopBar`
  // entirely (replaced by an aria-hidden spacer / nothing at all) -- if the
  // sheet was open on mobile, leaving `railOpen` true would reopen it the
  // moment focus mode exits and `RightRail` remounts.
  const enterFocus = useCallback(() => {
    setRailOpen(false);
    setFocusModeAnimated(true);
  }, [setFocusModeAnimated]);

  useEffect(() => {
    setReducedMotionState(getReducedMotion());
    return subscribeReducedMotion(() => setReducedMotionState(getReducedMotion()));
  }, []);

  return (
    /* "user" also honours prefers-reduced-motion on its own, so the OS setting
       keeps working when this switch is off. */
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <CustomCursor />
      <GuestNotice />
      <UndoToast />
      {/* ≤680px only (CSS-hidden above) -- merges `Sidebar`'s topbar and
          `RightRail`'s theme/font/focus/goal row into one fixed bar, since a
          phone has no vertical rail to host either inline. Sits outside
          `.app-grid` like `GuestNotice`/`UndoToast` above -- it's a fixed
          overlay, not a grid column -- and, like both rails, disappears in
          focus mode rather than floating over a feed that's supposed to be
          the only thing on screen. */}
      {focusMode ? null : (
        <MobileTopBar
          onReset={() => void onReset()}
          onRefresh={onRefresh}
          view={view}
          dailyGoal={dailyGoal}
          onEnterFocus={enterFocus}
        />
      )}
      <div className="app-grid" data-focused={focusMode}>
        {/* Both rails keep reserving their grid track even when hidden — an
            empty spacer, not a removed column — so toggling focus mode never
            reflows the center column sideways. */}
        {focusMode ? (
          <div className="rail-left" aria-hidden="true" />
        ) : (
          <Sidebar
            onReset={() => void onReset()}
            onRefresh={onRefresh}
            view={view}
            onNavigate={navigateAndCloseRail}
            onOpenRail={() => setRailOpen(true)}
          />
        )}
        <div className="shell">
          {/* Each view mounts once, the first time it's visited, and then stays
              mounted (hidden via the `hidden` attribute, never unmounted) so
              switching back to it never refetches on its own. */}
          <div hidden={view !== "feed"}>
            {/* CSS-only ≤680px (see `.mobile-topic-strip`) -- `RightRail`'s
                own `TopicRail` is the same filter, but below 1150px it's a
                tap into the sheet away. This puts it back at zero taps on a
                phone, which is the direct answer to "no way to ... apply
                filters ... from the right rail" on mobile. Stateless (props
                only, no fetch of its own), so a second mounted copy is safe --
                exactly one of the two is ever visible at a given width. Hidden
                in focus mode, same reasoning as `MobileTopBar` above. */}
            {!focusMode && topics.length > 0 ? (
              <div className="mobile-topic-strip">
                <TopicRail topics={topics} selected={selected} onToggle={toggleTopic} />
              </div>
            ) : null}
            <Feed key={resetCount} topics={topics} selected={selected} onCardSeen={onCardSeen} />
          </div>
          {visited.has("notes") ? (
            <div hidden={view !== "notes"}>
              <NotesView topics={topics} onNavigateHome={() => setView("feed")} />
            </div>
          ) : null}
          {visited.has("liked") ? (
            <div hidden={view !== "liked"}>
              <LikedView topics={topics} onNavigateHome={() => setView("feed")} />
            </div>
          ) : null}
          {visited.has("saved") ? (
            <div hidden={view !== "saved"}>
              <SavedView topics={topics} onNavigateHome={() => setView("feed")} />
            </div>
          ) : null}
          {visited.has("profile") ? (
            <div hidden={view !== "profile"}>
              <ProfileView onNavigate={navigateAndCloseRail} />
            </div>
          ) : null}
          {visited.has("settings") ? (
            <div hidden={view !== "settings"}>
              <SettingsView
                topics={topics}
                onNavigateProfile={() => setView("profile")}
                onTopicFollowed={onFollowed}
                onTopicRemoved={removeTopicLocally}
              />
            </div>
          ) : null}
        </div>
        {focusMode ? (
          <>
            <div className="rail-right" aria-hidden="true" />
            <FocusToggle focused onToggle={() => setFocusModeAnimated(false)} />
          </>
        ) : (
          <RightRail
            key={resetCount}
            topics={topics}
            progress={progress}
            selected={selected}
            onToggle={toggleTopic}
            onFollowed={onFollowed}
            onEnterFocus={enterFocus}
            onProgressChanged={refreshProgress}
            onTopicColorChanged={onTopicColorChanged}
            onUnfollowed={onUnfollowed}
            onTopicRemoved={removeTopicLocally}
            dailyGoal={dailyGoal}
            open={railOpen}
            onClose={() => setRailOpen(false)}
          />
        )}
      </div>
    </MotionConfig>
  );
}
