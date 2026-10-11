"use client";

/**
 * The root-route resolver (docs/adr — auth strategy). Mounted once in the
 * root layout so it sees every navigation, not just the feed's:
 *
 *   no token / invalid token   -> /signup
 *   token, onboarding pending  -> /onboarding
 *   token, onboarding done     -> away from /signup, /login, /onboarding
 *
 * The session token lives in localStorage (see lib/api.ts), which only exists
 * client-side — this is why the gate is a client component doing a real
 * `api.me()` round trip on navigation, not middleware.ts reading a cookie.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, clearSession, hasSession, type User } from "@/lib/api";
import { SpoinWave } from "./SpoinWave";

const PUBLIC_PATHS = new Set(["/login", "/signup"]);
const ONBOARDING_PATH = "/onboarding";
//: /claim (the guest -> full-account form) stays reachable regardless of
//: onboarding state — a guest should be able to save their progress at any
//: point, not just after finishing the topic picker.
const REDIRECT_EXEMPT_PATHS = new Set(["/claim"]);

//: The operator pages (`/admin/repairs`, `/admin/[topic]/ascii-art`) sit outside
//: the learner flow entirely -- they are dev-only surfaces reached by typing a
//: URL, and an operator has no reason to have finished the topic picker. Without
//: this they bounce to onboarding and are simply unreachable on a fresh session,
//: which is what `/admin/repairs` has quietly been doing.
//:
//: A prefix rather than a Set entry because `/admin/[topic]/ascii-art` has no
//: fixed path to enumerate. Auth itself is unaffected -- an unauthenticated
//: visitor still gets sent to /signup above; this exempts the ONBOARDING
//: redirect only.
const ADMIN_PATH_PREFIX = "/admin/";

function isRedirectExempt(pathname: string): boolean {
  return REDIRECT_EXEMPT_PATHS.has(pathname) || pathname.startsWith(ADMIN_PATH_PREFIX);
}

interface AuthContextValue {
  user: User | null;
  /** Re-fetches `/auth/me` AND re-runs the route gate — call after
   *  login/register/guest/claim/onboarding, i.e. whenever where the user
   *  belongs may have changed.
   *
   *  Not for in-app profile edits: `refresh` is `load`, which flips `loading`
   *  back on, and a protected path renders the blocking loader instead of its
   *  children while that is true. That unmounts the whole AppShell, so every
   *  bit of its state — which view you were on, the topic filter, the feed —
   *  is destroyed and rebuilt. Saving your name from the profile page used to
   *  drop you back on the feed for exactly this reason. Use `applyUser`. */
  refresh: () => Promise<void>;
  /** Publish an already-fetched user (e.g. the one a PATCH just returned)
   *  without re-running the gate or a redundant `/auth/me` round trip. */
  applyUser: (user: User) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

function forgetUser() {
  clearSession();
  // Not this user's generations to watch anymore -- GenerationTrackerProvider
  // re-reads this key lazily on next mount, so clearing it directly here
  // (rather than threading a second context in) is enough.
  localStorage.removeItem("spoin_active_generations");
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const logout = useCallback(() => {
    // Ends the session on the server as well; never blocks leaving.
    void api.signOut().catch(() => undefined);
    forgetUser();
    setUser(null);
    router.push("/signup");
  }, [router]);

  const load = useCallback(async () => {
    // Re-arm the blocking loader on every navigation — otherwise a `loading`
    // left over `false` from the PREVIOUS pathname lets this render's
    // children (e.g. AppShell, which fires its own API calls on mount) paint
    // for one frame before a redirect below actually lands.
    setLoading(true);

    if (!hasSession()) {
      setUser(null);
      if (!PUBLIC_PATHS.has(pathname)) {
        router.replace("/signup");
        return; // stay "loading" — nothing here should render at this pathname
      }
      setLoading(false);
      return;
    }

    try {
      const me = await api.me();
      setUser(me);
      const exempt = isRedirectExempt(pathname);
      if (!me.onboarding_complete && pathname !== ONBOARDING_PATH && !exempt) {
        router.replace(ONBOARDING_PATH);
        return;
      }
      if (
        me.onboarding_complete &&
        !me.is_guest &&
        !exempt &&
        (PUBLIC_PATHS.has(pathname) || pathname === ONBOARDING_PATH)
      ) {
        router.replace("/");
        return;
      }
      setLoading(false);
    } catch {
      forgetUser();
      setUser(null);
      if (!PUBLIC_PATHS.has(pathname)) {
        router.replace("/signup");
        return;
      }
      setLoading(false);
    }
  }, [pathname, router]);

  useEffect(() => {
    load();
    // Deliberately only on pathname change — `load` closes over it already,
    // and re-running on every render would refetch `/auth/me` constantly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Public pages render immediately (no flash); protected pages block until
  // the token is checked so they never render with a null user. A deep link
  // straight to the feed lands here first — hold the SpoinWave until the
  // whole authed page is ready, then swap it for the page in one paint.
  if (loading && !PUBLIC_PATHS.has(pathname)) {
    return <SpoinWave variant="page" />;
  }

  return (
    <AuthContext.Provider value={{ user, refresh: load, applyUser: setUser, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
