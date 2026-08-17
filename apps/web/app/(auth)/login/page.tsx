"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "@/lib/api";

export default function AuthPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      if (mode === "login") {
        const data = await api.login({ email, password });
        localStorage.setItem("spoin_access_token", data.access_token);
        localStorage.setItem("spoin_refresh_token", data.refresh_token);
        router.push("/");
      } else {
        const data = await api.register({ email, password, display_name: name });
        localStorage.setItem("spoin_access_token", data.access_token);
        localStorage.setItem("spoin_refresh_token", data.refresh_token);
        router.push("/");
      }
    } catch (err: any) {
      if (err.status === 401) {
        setError("That email or password doesn't look right.");
      } else if (err.status === 409) {
        setError("An account with that email already exists.");
      } else {
        setError(err.message || "Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  const formVariants = {
    hidden: { opacity: 0, x: -10 },
    visible: { opacity: 1, x: 0, transition: { duration: 0.3, ease: "easeOut" } },
    exit: { opacity: 0, x: 10, transition: { duration: 0.2, ease: "easeIn" } },
  };

  return (
    <div className="auth-layout">
      <motion.div
        className="auth-panel"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "circOut" }}
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={mode}
            variants={formVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
          >
            <div className="auth-header">
              <h1 className="auth-title">
                {mode === "login" ? "Welcome back." : "Create your account."}
              </h1>
              <p className="auth-subtitle">
                {mode === "login"
                  ? "Enter your details to access your feed."
                  : "Join to start exploring knowledge."}
              </p>
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
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  className="auth-error"
                >
                  {error}
                </motion.div>
              )}

              <button type="submit" className="auth-button" disabled={loading}>
                {loading && <span className="auth-loader" />}
                {loading
                  ? mode === "login"
                    ? "Signing in..."
                    : "Creating..."
                  : mode === "login"
                    ? "Sign In"
                    : "Create Account"}
              </button>
            </form>

            <div className="auth-footer">
              {mode === "login" ? (
                <>
                  Don&apos;t have an account?{" "}
                  <button
                    type="button"
                    className="auth-link"
                    onClick={() => {
                      setMode("register");
                      setError("");
                    }}
                  >
                    Create one &rarr;
                  </button>
                </>
              ) : (
                <>
                  Already have an account?{" "}
                  <button
                    type="button"
                    className="auth-link"
                    onClick={() => {
                      setMode("login");
                      setError("");
                    }}
                  >
                    Sign in &rarr;
                  </button>
                </>
              )}
            </div>
          </motion.div>
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
