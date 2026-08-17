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
  /** Re-fetches `/auth/me` — call after login/register/guest/claim/onboarding. */
  refresh: () => Promise<void>;
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
    if (!localStorage.getItem("spoin_access_token")) {
      setUser(null);
      setLoading(false);
      if (!PUBLIC_PATHS.has(pathname)) router.replace("/signup");
      return;
    }

    try {
      const me = await api.me();
      setUser(me);
      setLoading(false);
      const exempt = REDIRECT_EXEMPT_PATHS.has(pathname);
      if (!me.onboarding_complete && pathname !== ONBOARDING_PATH && !exempt) {
        router.replace(ONBOARDING_PATH);
      } else if (
        me.onboarding_complete &&
        !exempt &&
        (PUBLIC_PATHS.has(pathname) || pathname === ONBOARDING_PATH)
      ) {
        router.replace("/");
      }
    } catch {
      clearTokens();
      setUser(null);
      setLoading(false);
      if (!PUBLIC_PATHS.has(pathname)) router.replace("/signup");
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

  return <AuthContext.Provider value={{ user, refresh: load, logout }}>{children}</AuthContext.Provider>;
}
