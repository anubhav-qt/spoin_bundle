/**
 * The left rail: wordmark and nav. Only "Home" and "Notes" and "Liked" are
 * real — the rest are stubs (rendered, `aria-disabled`, no click handler)
 * until those surfaces exist. "Explore" moved out in favor of the right
 * rail's topic discovery (ADR-0015, reworked into a modal by ADR-0036),
 * which replaces it with a real (if simple) feature rather than another stub.
 *
 * The wordmark doubles as a dev-only reset easter egg (`onReset`, wired to
 * POST /dev/reset — see api/routers/dev.py). Deliberately not a labeled
 * button anywhere in the three rails, per how it was asked for: standalone,
 * discoverable only by clicking the thing that's always on screen anyway.
 */

import { useAuth } from "./AuthProvider";
import { BookmarkIcon, GearIcon, HeartIcon, HomeIcon, LayersIcon, NoteIcon, UserIcon, LogoutIcon } from "./icons";

const STUBS = [
  { label: "Deep Dive", icon: LayersIcon },
  { label: "Settings", icon: GearIcon },
] as const;

export type ShellView = "feed" | "notes" | "liked" | "saved" | "profile";

interface Props {
  onReset: () => void;
  view: ShellView;
  onNavigate: (view: ShellView) => void;
}

export function Sidebar({ onReset, view, onNavigate }: Props) {
  const { logout } = useAuth();

  return (
    <nav className="rail-left" aria-label="Primary">
      <button type="button" className="sidebar-mark mono" onClick={onReset} aria-label="spoin">
        sp<span className="sidebar-mark-accent">o</span>in
      </button>

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
        className="nav-item"
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
        className="nav-item"
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
        className="nav-item"
        aria-current={view === "saved" ? "page" : undefined}
        onClick={() => onNavigate("saved")}
      >
        <span className="nav-item-icon">
          <BookmarkIcon filled={view === "saved"} />
        </span>
        <span className="nav-item-label">Saved</span>
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

      {STUBS.map(({ label, icon: Icon }) => (
        <span key={label} className="nav-item" aria-disabled="true">
          <span className="nav-item-icon">
            <Icon />
          </span>
          <span className="nav-item-label">{label}</span>
        </span>
      ))}

      <div className="nav-item-logout-wrap">
        <button type="button" className="nav-item nav-item-logout" onClick={logout}>
          <span className="nav-item-icon">
            <LogoutIcon />
          </span>
          <span className="nav-item-label">Log out</span>
        </button>
      </div>
    </nav>
  );
}
