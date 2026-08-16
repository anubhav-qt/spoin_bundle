/**
 * The left rail: wordmark and nav. Only "Home" is real — the rest are stubs
 * (rendered, `aria-disabled`, no click handler) until those surfaces exist.
 * "Explore" moved out in favor of the right rail's DiscoverBox (ADR-0015),
 * which replaces it with a real (if simple) feature rather than another stub.
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

export function Sidebar() {
  return (
    <nav className="rail-left" aria-label="Primary">
      <div className="sidebar-mark mono">slocho</div>

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
