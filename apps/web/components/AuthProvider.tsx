"use client";

/**
 * The root-route resolver (docs/adr — auth strategy). Mounted once in the
 * root layout so it sees every navigation, not just the feed's:
 *
 *   no token / invalid token   -> /signup
 *   token, onboarding pending  -> /onboarding
 *   token, onboarding done     -> away from /signup, /login, /onboarding
 *
 * Tokens live in localStorage (see lib/api.ts), which only exists client-side
 * — this is why the gate is a client component doing a real `api.me()` round
 * trip on navigation, not middleware.ts reading a cookie.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, type User } from "@/lib/api";

const PUBLIC_PATHS = new Set(["/login", "/signup"]);
const ONBOARDING_PATH = "/onboarding";
//: /claim (the guest -> full-account form) stays reachable regardless of
//: onboarding state — a guest should be able to save their progress at any
//: point, not just after finishing the topic picker.
const REDIRECT_EXEMPT_PATHS = new Set(["/claim"]);

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

function clearTokens() {
  localStorage.removeItem("spoin_access_token");
  localStorage.removeItem("spoin_refresh_token");
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
    router.push("/signup");
  }, [router]);

  const load = useCallback(async () => {
    // Re-arm the blocking loader on every navigation — otherwise a `loading`
    // left over `false` from the PREVIOUS pathname lets this render's
    // children (e.g. AppShell, which fires its own API calls on mount) paint
    // for one frame before a redirect below actually lands.
    setLoading(true);

    if (!localStorage.getItem("spoin_access_token")) {
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
      const exempt = REDIRECT_EXEMPT_PATHS.has(pathname);
      if (!me.onboarding_complete && pathname !== ONBOARDING_PATH && !exempt) {
        router.replace(ONBOARDING_PATH);
        return;
      }
      if (me.onboarding_complete && !exempt && (PUBLIC_PATHS.has(pathname) || pathname === ONBOARDING_PATH)) {
        router.replace("/");
        return;
      }
      setLoading(false);
    } catch {
      clearTokens();
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
  // the token is checked so they never render with a null user.
  if (loading && !PUBLIC_PATHS.has(pathname)) {
    return (
      <div
        className="auth-layout"
        style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}
      >
        <div className="auth-loader" style={{ transform: "scale(1.5)" }} />
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ user, refresh: load, applyUser: setUser, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
