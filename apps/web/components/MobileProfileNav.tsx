"use client";

/**
 * ≤680px only: Notes, Liked, Saved, and log out/sign up -- everything
 * `Sidebar` still owns but the mobile pill nav has no room for (see
 * ADR-0061). Rendered inside `ProfileView`, near the top, so "Profile" is
 * genuinely the phone's hub for the whole left rail, not just the profile
 * page itself.
 *
 * Reuses `Sidebar`'s own `.nav-item` markup/classes -- same buttons, same
 * icons, just a different parent and CSS-hidden above 680px instead of
 * being pinned to the mobile nav pill.
 */

import Link from "next/link";
import { useAuth } from "./AuthProvider";
import { BookmarkIcon, HeartIcon, LogoutIcon, NoteIcon, UserIcon } from "./icons";
import type { ShellView } from "./Sidebar";

interface Props {
  onNavigate: (view: ShellView) => void;
}

export function MobileProfileNav({ onNavigate }: Props) {
  const { user, logout } = useAuth();

  return (
    <nav className="mobile-profile-nav" aria-label="More">
      <button type="button" className="nav-item" onClick={() => onNavigate("notes")}>
        <span className="nav-item-icon">
          <NoteIcon />
        </span>
        <span className="nav-item-label">Notes</span>
      </button>

      <button type="button" className="nav-item" onClick={() => onNavigate("liked")}>
        <span className="nav-item-icon">
          <HeartIcon />
        </span>
        <span className="nav-item-label">Liked</span>
      </button>

      <button type="button" className="nav-item" onClick={() => onNavigate("saved")}>
        <span className="nav-item-icon">
          <BookmarkIcon />
        </span>
        <span className="nav-item-label">Saved</span>
      </button>

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
    </nav>
  );
}
