"use client";

/**
 * The bottom tab bar for narrow viewports (<=900px), where the left rail
 * (`Sidebar`) is hidden. Five destinations, Home centred. "Revisit" routes to
 * the Saved view for now — a distinct spaced-repetition surface is a separate
 * task (docs/tasks). Settings isn't a tab; it's reached from the Browse sheet.
 *
 * Fixed to the bottom edge (see `.mobile-nav` in globals.css), so it sits on
 * top of the window-level feed scroll the same way the real OS chrome will in
 * the eventual native app.
 */

import { HeartIcon, HistoryIcon, HomeIcon, NoteIcon, UserIcon } from "./icons";
import type { ShellView } from "./Sidebar";

interface Tab {
  key: string;
  label: string;
  view: ShellView;
  icon: React.ReactNode;
}

interface Props {
  view: ShellView;
  onNavigate: (view: ShellView) => void;
}

export function MobileNav({ view, onNavigate }: Props) {
  const tabs: Tab[] = [
    { key: "liked", label: "Liked", view: "liked", icon: <HeartIcon filled={view === "liked"} /> },
    { key: "revisit", label: "Revisit", view: "saved", icon: <HistoryIcon /> },
    { key: "feed", label: "Home", view: "feed", icon: <HomeIcon /> },
    { key: "notes", label: "Notes", view: "notes", icon: <NoteIcon /> },
    { key: "profile", label: "Profile", view: "profile", icon: <UserIcon filled={view === "profile"} /> },
  ];

  return (
    <nav className="mobile-nav" aria-label="Primary">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          className="mobile-nav-item"
          aria-current={view === tab.view ? "page" : undefined}
          onClick={() => onNavigate(tab.view)}
        >
          <span className="mobile-nav-icon">{tab.icon}</span>
          <span className="mobile-nav-label">{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}
