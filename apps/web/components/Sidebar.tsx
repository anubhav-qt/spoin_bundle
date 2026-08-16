/**
 * The left rail: wordmark and nav. Only "Home" is real — the rest are stubs
 * (rendered, `aria-disabled`, no click handler) until those surfaces exist.
 * "Explore" moved out in favor of the right rail's DiscoverBox (ADR-0015),
 * which replaces it with a real (if simple) feature rather than another stub.
 *
 * The wordmark doubles as a dev-only reset easter egg (`onReset`, wired to
 * POST /dev/reset — see api/routers/dev.py). Deliberately not a labeled
 * button anywhere in the three rails, per how it was asked for: standalone,
 * discoverable only by clicking the thing that's always on screen anyway.
 */

import { BookmarkIcon, GearIcon, HeartIcon, HomeIcon, LayersIcon, NoteIcon, UserIcon } from "./icons";

const STUBS = [
  { label: "Profile", icon: UserIcon },
  { label: "Liked", icon: HeartIcon },
  { label: "Saved", icon: BookmarkIcon },
  { label: "Notes", icon: NoteIcon },
  { label: "Deep Dive", icon: LayersIcon },
  { label: "Settings", icon: GearIcon },
] as const;

interface Props {
  onReset: () => void;
}

export function Sidebar({ onReset }: Props) {
  return (
    <nav className="rail-left" aria-label="Primary">
      <button type="button" className="sidebar-mark mono" onClick={onReset} aria-label="slocho">
        slocho
      </button>

      <a className="nav-item" href="/" aria-current="page">
        <span className="nav-item-icon">
          <HomeIcon />
        </span>
        <span className="nav-item-label">Home</span>
      </a>

      {STUBS.map(({ label, icon: Icon }) => (
        <span key={label} className="nav-item" aria-disabled="true">
          <span className="nav-item-icon">
            <Icon />
          </span>
          <span className="nav-item-label">{label}</span>
        </span>
      ))}
    </nav>
  );
}
