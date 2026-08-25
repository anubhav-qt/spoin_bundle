/**
 * The left rail: wordmark and nav. Everything except "Deep Dive" is real
 * now; that one stays a stub (rendered, `aria-disabled`, no click handler)
 * until the surface exists. "Explore" moved out in favor of the right
 * rail's topic discovery (ADR-0015, reworked into a modal by ADR-0036),
 * which replaces it with a real (if simple) feature rather than another stub.
 *
 * The wordmark doubles as a dev-only reset easter egg (`onReset`, wired to
 * POST /dev/reset — see api/routers/dev.py). Deliberately not a labeled
 * button anywhere in the three rails, per how it was asked for: standalone,
 * discoverable only by clicking the thing that's always on screen anyway.
 */

import Link from "next/link";
import { useAuth } from "./AuthProvider";
import {
  BookmarkIcon,
  GearIcon,
  HeartIcon,
  HomeIcon,
  LayersIcon,
  NoteIcon,
  RefreshIcon,
  SlidersIcon,
  UserIcon,
  LogoutIcon,
} from "./icons";

const STUBS = [{ label: "Deep Dive", icon: LayersIcon }] as const;

export type ShellView = "feed" | "notes" | "liked" | "saved" | "profile" | "settings";

export const VIEW_LABEL: Record<ShellView, string> = {
  feed: "home",
  notes: "notes",
  liked: "liked",
  saved: "saved",
  profile: "profile",
  settings: "settings",
};

interface Props {
  onReset: () => void;
  /** Refreshes whichever view is currently open — the header control next to
   *  the wordmark, not the dev-reset easter egg the wordmark itself is. */
  onRefresh: () => void;
  view: ShellView;
  onNavigate: (view: ShellView) => void;
  /** Opens the right rail as a sheet/slide-over -- reachable via the
   *  "Topics" nav item below 1150px (a normal labeled row 681-1150px, a
   *  pill item in the mobile nav ≤680px). CSS-hidden above 1150px, where
   *  the rail is already visible inline and opening it makes no sense. */
  onOpenRail: () => void;
}

export function Sidebar({ onReset, onRefresh, view, onNavigate, onOpenRail }: Props) {
  const { user, logout } = useAuth();

  return (
    <nav className="rail-left" aria-label="Primary">
      <div className="sidebar-topbar">
        <button type="button" className="sidebar-mark mono" onClick={onReset} aria-label="spoin">
          sp<span className="sidebar-mark-accent">o</span>in
        </button>

        <button
          type="button"
          className="sidebar-refresh"
          onClick={onRefresh}
          aria-label={`Refresh ${VIEW_LABEL[view]}`}
        >
          <span className="sidebar-refresh-icon">
            <RefreshIcon />
          </span>
          <span className="sidebar-refresh-label">Refresh</span>
        </button>
      </div>

      <div className="nav-items">
        <button
          type="button"
          className="nav-item"
          aria-current={view === "feed" ? "page" : undefined}
          onClick={() => onNavigate("feed")}
        >
          <span className="nav-item-icon">
            <HomeIcon />
          </span>
          <span className="nav-item-label">Home</span>
        </button>

        <button
          type="button"
          className="nav-item nav-item-mobile-hidden"
          aria-current={view === "notes" ? "page" : undefined}
          onClick={() => onNavigate("notes")}
        >
          <span className="nav-item-icon">
            <NoteIcon />
          </span>
          <span className="nav-item-label">Notes</span>
        </button>

        <button
          type="button"
          className="nav-item nav-item-mobile-hidden"
          aria-current={view === "liked" ? "page" : undefined}
          onClick={() => onNavigate("liked")}
        >
          <span className="nav-item-icon">
            <HeartIcon filled={view === "liked"} />
          </span>
          <span className="nav-item-label">Liked</span>
        </button>

        <button
          type="button"
          className="nav-item nav-item-mobile-hidden"
          aria-current={view === "saved" ? "page" : undefined}
          onClick={() => onNavigate("saved")}
        >
          <span className="nav-item-icon">
            <BookmarkIcon filled={view === "saved"} />
          </span>
          <span className="nav-item-label">Saved</span>
        </button>

        {/* Opens the right rail as a sheet/slide-over (below 1150px only --
            CSS-hidden above that, where the rail is already inline). Not a
            `view` -- doesn't take `aria-current`. */}
        <button
          type="button"
          className="nav-item nav-item-topics-trigger"
          onClick={onOpenRail}
          aria-label="Open topic filters"
        >
          <span className="nav-item-icon">
            <SlidersIcon />
          </span>
          <span className="nav-item-label">Topics</span>
        </button>

        <button
          type="button"
          className="nav-item"
          aria-current={view === "profile" ? "page" : undefined}
          onClick={() => onNavigate("profile")}
        >
          <span className="nav-item-icon">
            <UserIcon filled={view === "profile"} />
          </span>
          <span className="nav-item-label">Profile</span>
        </button>

        <button
          type="button"
          className="nav-item"
          aria-current={view === "settings" ? "page" : undefined}
          onClick={() => onNavigate("settings")}
        >
          <span className="nav-item-icon">
            <GearIcon />
          </span>
          <span className="nav-item-label">Settings</span>
        </button>

        {STUBS.map(({ label, icon: Icon }) => (
          <span key={label} className="nav-item nav-item-stub" aria-disabled="true">
            <span className="nav-item-icon">
              <Icon />
            </span>
            <span className="nav-item-label">{label}</span>
          </span>
        ))}
      </div>

      <div className="nav-item-logout-wrap">
        {user?.is_guest ? (
          <Link href="/claim" className="nav-item nav-item-signup">
            <span className="nav-item-icon">
              <UserIcon />
            </span>
            <span className="nav-item-label">Sign up</span>
          </Link>
        ) : (
          <button type="button" className="nav-item nav-item-logout" onClick={logout}>
            <span className="nav-item-icon">
              <LogoutIcon />
            </span>
            <span className="nav-item-label">Log out</span>
          </button>
        )}
      </div>
    </nav>
  );
}
