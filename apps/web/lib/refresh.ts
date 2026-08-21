"use client";

import { useEffect, useRef } from "react";

/**
 * Cross-view cache invalidation.
 *
 * Every shell view (Feed, Notes, Liked, Saved, Profile) fetches once when
 * first visited and then stays mounted for the rest of the session — see
 * AppShell's `visited` set — so switching between Home/Notes/Liked/Saved no
 * longer refetches on its own. This module is what still gets a view's data
 * back in sync when it actually goes stale: either the header's refresh
 * control (scoped to whichever view is open) or a mutation made elsewhere in
 * the app that a currently-mounted-but-not-visible view needs to know about
 * (e.g. liking a card in the feed staling the Liked view's list).
 */

export type RefreshScope = "feed" | "notes" | "liked" | "saved" | "profile" | "settings";

type Listener = () => void;

const listeners: Record<RefreshScope, Set<Listener>> = {
  feed: new Set(),
  notes: new Set(),
  liked: new Set(),
  saved: new Set(),
  profile: new Set(),
  settings: new Set(),
};

const ALL_SCOPES: readonly RefreshScope[] = ["feed", "notes", "liked", "saved", "profile", "settings"];

/** Marks one or more scopes stale — every view currently subscribed via
 *  `useRefreshEffect` re-runs its loader right away, whether or not it's the
 *  view the user is looking at. Pass "all" after something that invalidates
 *  everything at once (the dev-reset easter egg). */
export function invalidate(scopes: RefreshScope | "all" | readonly RefreshScope[]): void {
  const list: readonly RefreshScope[] =
    scopes === "all" ? ALL_SCOPES : typeof scopes === "string" ? [scopes] : scopes;
  for (const scope of list) {
    for (const fn of listeners[scope]) fn();
  }
}

export function subscribeRefresh(scope: RefreshScope, fn: Listener): () => void {
  listeners[scope].add(fn);
  return () => {
    listeners[scope].delete(fn);
  };
}

/** Re-runs `onRefresh` whenever `scope` is invalidated. Does NOT run on
 *  mount — the view's own effect already owns the initial load; this only
 *  owns re-loading after the fact. `onRefresh` is read through a ref that's
 *  updated every render, so a stale closure (e.g. one capturing last
 *  render's filter/sort state) is never the one that actually runs. */
export function useRefreshEffect(scope: RefreshScope, onRefresh: () => void): void {
  const handler = useRef(onRefresh);
  handler.current = onRefresh;

  useEffect(() => subscribeRefresh(scope, () => handler.current()), [scope]);
}
