"use client";

/**
 * Reconciles the client's appearance-preference cache against the server
 * (ADR-0070). Mounted once inside `AuthProvider` so it sees every `/auth/me`.
 *
 * The inline script in `app/layout.tsx` has already painted from the
 * `localStorage` cache before this runs — this is the second half: once the
 * `/auth/me` payload arrives with `preferences`, apply the server value (if it
 * differs from the cache), register any imported `@font-face`s, and rewrite the
 * cache. Renders nothing.
 */

import { useEffect } from "react";
import { hydrateFromCache, reconcile } from "@/lib/preferences";
import { useAuth } from "./AuthProvider";

export function PreferencesSync() {
  const { user } = useAuth();

  useEffect(() => {
    hydrateFromCache();
  }, []);

  useEffect(() => {
    if (user?.preferences) reconcile(user.preferences);
  }, [user?.preferences]);

  return null;
}
