"use client";

/**
 * Persistent-but-dismissible nudge for guests (docs/adr on guest identity).
 * `sessionStorage`, not `localStorage`, for the dismissed flag -- it must
 * come back on a fresh tab/session, not stay dismissed forever.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";

const DISMISS_KEY = "spoin-guest-notice-dismissed";

export function GuestNotice() {
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    setDismissed(sessionStorage.getItem(DISMISS_KEY) === "1");
  }, []);

  if (!user?.is_guest || dismissed) return null;

  return (
    <div className="guest-notice" role="status">
      <span>Sign up to save this session&apos;s taste profile and progress.</span>
      <Link href="/claim" className="guest-notice-link">
        Sign up
      </Link>
      <button
        type="button"
        className="guest-notice-dismiss"
        aria-label="Dismiss"
        onClick={() => {
          sessionStorage.setItem(DISMISS_KEY, "1");
          setDismissed(true);
        }}
      >
        &times;
      </button>
    </div>
  );
}
