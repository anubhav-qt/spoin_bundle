"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { ApiError, api, type AuthTokens } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";
import { GoogleSignInButton } from "@/components/GoogleSignInButton";
import { SpoinWave } from "@/components/SpoinWave";

function storeTokens(tokens: AuthTokens) {
  localStorage.setItem("spoin_access_token", tokens.access_token);
  localStorage.setItem("spoin_refresh_token", tokens.refresh_token);
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "That email or password doesn't look right.";
    if (err.status === 409) return "An account with that email already exists.";
    if (err.status === 429) return "Too many attempts. Try again in a minute.";
    return err.message;
  }
  return "Something went wrong. Please try again.";
}

interface Props {
  /** "register" is the primary/default surface (/signup); "login" is the
   *  secondary one (/login) reached via the footer link. */
  mode: "login" | "register";
}

export function AuthForm({ mode }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();
  const { user, refresh } = useAuth();

  // A signed-in guest hitting the register form is claiming their existing
  // account (same user_id, progress carries over), not starting a new one.
  const claiming = mode === "register" && !!user?.is_guest;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      if (mode === "login") {
        storeTokens(await api.login({ email, password }));
      } else if (claiming) {
        storeTokens(await api.claim({ email, password, display_name: name }));
      } else {
        storeTokens(await api.register({ email, password, display_name: name }));
      }
      await refresh();
      router.push("/");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  };

  const handleGuest = async () => {
    setError("");
    setLoading(true);
    try {
      storeTokens(await api.guest());
      await refresh();
      router.push("/");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleToken = async (idToken: string) => {
    setError("");
    setLoading(true);
    try {
      storeTokens(await api.googleAuth(idToken));
      await refresh();
      router.push("/");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  };

  const formVariants = {
    hidden: { opacity: 0, x: -10 },
    visible: { opacity: 1, x: 0, transition: { duration: 0.3, ease: "easeOut" } },
    exit: { opacity: 0, x: 10, transition: { duration: 0.2, ease: "easeIn" } },
  };

  const title = claiming
    ? "Save your progress."
    : mode === "login"
      ? "Welcome back."
      : "Create your account.";
  const subtitle = claiming
    ? "Add an email and password to keep your progress, or sign in to an existing account."
    : mode === "login"
      ? "Enter your details to access your feed."
      : "Join to start exploring knowledge.";

  return (
    <div className="auth-layout">
      <motion.div
        className="auth-panel"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "circOut" }}
      >
        <AnimatePresence mode="wait">
          <motion.div key={mode} variants={formVariants} initial="hidden" animate="visible" exit="exit">
            <div className="auth-header">
              <h1 className="auth-title">{title}</h1>
              <p className="auth-subtitle">{subtitle}</p>
            </div>

            <form className="auth-form" onSubmit={handleSubmit} noValidate>
              {mode === "register" && (
                <div className="auth-field">
                  <label className="auth-label" htmlFor="name">
                    Name
                  </label>
                  <input
                    id="name"
                    type="text"
                    className="auth-input"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    disabled={loading}
                    placeholder="Jane Doe"
                  />
                </div>
              )}

              <div className="auth-field">
                <label className="auth-label" htmlFor="email">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  className="auth-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  disabled={loading}
                  placeholder="jane@example.com"
                  autoComplete="email"
                />
              </div>

              <div className="auth-field">
                <label className="auth-label" htmlFor="password">
                  Password
                </label>
                <input
                  id="password"
                  type="password"
                  className="auth-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  disabled={loading}
                  placeholder="••••••••"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                />
              </div>

              {error && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} className="auth-error">
                  {error}
                </motion.div>
              )}

              <button type="submit" className="auth-button" disabled={loading}>
                {loading ? (
                  <SpoinWave variant="inline" label="Working" />
                ) : claiming ? (
                  "Save progress"
                ) : mode === "login" ? (
                  "Sign In"
                ) : (
                  "Create Account"
                )}
              </button>
            </form>

            <div className="auth-divider">or</div>

            <GoogleSignInButton onToken={handleGoogleToken} />

            {mode === "register" && !claiming && (
              <button
                type="button"
                className="auth-button auth-button-secondary"
                onClick={handleGuest}
                disabled={loading}
              >
                Continue as guest
              </button>
            )}

            <div className="auth-footer">
              {mode === "login" ? (
                <>
                  Don&apos;t have an account?{" "}
                  <Link className="auth-link" href="/signup">
                    Create one &rarr;
                  </Link>
                </>
              ) : (
                <>
                  Already have an account?{" "}
                  <Link className="auth-link" href="/login">
                    Sign in &rarr;
                  </Link>
                </>
              )}
            </div>
          </motion.div>
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
