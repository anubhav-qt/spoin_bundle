/**
 * Thin stroked line icons, matched to the reference's weight: 1.5px strokes on a
 * 24 viewBox, rounded caps and joins, no fills.
 *
 * Inline rather than from a package. They need to inherit `currentColor` and
 * the card's stroke width, and an icon dependency would ship a few hundred
 * glyphs to render these.
 */

type IconProps = { className?: string };

export function LevelIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 19V11" />
      <path d="M10 19V6" />
      <path d="M16 19v-9" />
      <path d="M22 19V4" />
    </svg>
  );
}

export function SubtopicIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 5h16" />
      <path d="M4 12h10" />
      <path d="M4 19h7" />
    </svg>
  );
}

export function ClockIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

export function DeckIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="7" y="3.5" width="13" height="13" rx="2.5" />
      <path d="M16.5 20.5H6a2.5 2.5 0 0 1-2.5-2.5V7.5" />
    </svg>
  );
}

export function RefreshIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 12a8 8 0 0 1 13.66-5.66L20 8.5" />
      <path d="M20 4v4.5h-4.5" />
      <path d="M20 12a8 8 0 0 1-13.66 5.66L4 15.5" />
      <path d="M4 20v-4.5h4.5" />
    </svg>
  );
}

export function HeartIcon({ filled = false }: { filled?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" style={{ fill: filled ? "currentColor" : "none" }}>
      <path d="M12 20s-7.5-4.7-7.5-9.4A4.1 4.1 0 0 1 12 8a4.1 4.1 0 0 1 7.5 2.6C19.5 15.3 12 20 12 20Z" />
    </svg>
  );
}

export function BookmarkIcon({ filled = false }: { filled?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" style={{ fill: filled ? "currentColor" : "none" }}>
      <path d="M6.5 4.5h11v15l-5.5-4-5.5 4v-15Z" />
    </svg>
  );
}

export function NoteIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M16 4.5 19.5 8 9 18.5l-4.5 1 1-4.5L16 4.5Z" />
    </svg>
  );
}

export function SparkIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3.5 13.8 9 19.5 12 13.8 15 12 20.5 10.2 15 4.5 12l5.7-3L12 3.5Z" />
    </svg>
  );
}

export function ShareIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="17.5" cy="6" r="2.5" />
      <circle cx="6.5" cy="12" r="2.5" />
      <circle cx="17.5" cy="18" r="2.5" />
      <path d="M8.8 10.8 15.2 7.3M8.8 13.2l6.4 3.5" />
    </svg>
  );
}

export function CheckIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m5 12.5 4.5 4.5L19 7" />
    </svg>
  );
}

/** The trailing arrow on the solid pill, straight from the reference. */
export function ArrowIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 17 17 7" />
      <path d="M8.5 7H17v8.5" />
    </svg>
  );
}

export function HomeIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 11.5 12 4l8 7.5" />
      <path d="M6 10v9.5h12V10" />
    </svg>
  );
}

/** Revisit — a clock wound backwards. Same 24/1.5 spec as the rest. */
export function HistoryIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 12a9 9 0 1 0 2.64-6.36" />
      <path d="M3 4.5V9h4.5" />
      <path d="M12 8.5V12l2.6 1.8" />
    </svg>
  );
}

/** Opens the mobile "Browse" sheet — filters and settings live behind it. */
export function SlidersIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h8M17 7h3M4 12h3M12 12h8M4 17h11M19 17h1" />
      <circle cx="14.5" cy="7" r="2" />
      <circle cx="9" cy="12" r="2" />
      <circle cx="16.5" cy="17" r="2" />
    </svg>
  );
}

export function CompassIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="m14.5 9.5-2 5-5 2 2-5 5-2Z" />
    </svg>
  );
}

export function UserIcon({ filled = false }: { filled?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" style={{ fill: filled ? "currentColor" : "none" }}>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 20c0-3.5 3-6 7-6s7 2.5 7 6" />
    </svg>
  );
}

export function FocusIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9" />
      <path d="M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9" />
      <path d="M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15" />
      <path d="M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15" />
    </svg>
  );
}

export function LayersIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 13 9 5 9-5" />
    </svg>
  );
}

export function CloseIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

export function CopyIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M15 9V6.5A2.5 2.5 0 0 0 12.5 4H6.5A2.5 2.5 0 0 0 4 6.5v6A2.5 2.5 0 0 0 6.5 15H9" />
    </svg>
  );
}

export function ExpandIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 4.5H4.5V9" />
      <path d="M15 4.5h4.5V9" />
      <path d="M9 19.5H4.5V15" />
      <path d="M15 19.5h4.5V15" />
    </svg>
  );
}

export function LogoutIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M10 4.5H6.5A2.5 2.5 0 0 0 4 7v10a2.5 2.5 0 0 0 2.5 2.5H10" />
      <path d="M15.5 16 20 12l-4.5-4" />
      <path d="M9.5 12H20" />
    </svg>
  );
}

export function GearIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.3M12 18.2v2.3M20.5 12h-2.3M5.8 12H3.5M17.7 6.3l-1.6 1.6M7.9 16.1l-1.6 1.6M17.7 17.7l-1.6-1.6M7.9 7.9 6.3 6.3" />
    </svg>
  );
}

export function LinkIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  );
}

export function PhotoIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3.5" y="4.5" width="17" height="15" rx="3" />
      <circle cx="8.5" cy="9.5" r="1.5" />
      <path d="m20.5 15-5-5L5.5 19" />
    </svg>
  );
}

/* ── Avatar marks ───────────────────────────────────────────────────────────
   A closed set of eight, drawn to the same spec as the icons above (24
   viewBox, 1.5 stroke, rounded caps, no fills) so a chosen avatar sits in the
   same visual family as the rest of the interface.

   These replaced a row of raw Unicode glyphs (◉ ◇ △ ✦ …). A glyph inherits
   whichever face is active — five of them ship (ADR-0023/0037) — so the same
   stored avatar rendered at a different weight, size and baseline per font,
   and two of them fell back to a system face entirely. A path renders
   identically everywhere and picks up `currentColor` like every other icon.

   `avatar_icon` stores the KEY ("orbit"), not the glyph. `AvatarMark` falls
   back to rendering an unrecognized value as text, so accounts that saved a
   glyph before this change keep showing it rather than going blank. */

export const AVATAR_MARK_KEYS = [
  "orbit",
  "prism",
  "lattice",
  "aperture",
  "meridian",
  "cairn",
  "beacon",
  "helix",
] as const;

export type AvatarMarkKey = (typeof AVATAR_MARK_KEYS)[number];

const AVATAR_MARKS: Record<AvatarMarkKey, React.ReactElement> = {
  orbit: (
    <>
      <circle cx="12" cy="12" r="3.5" />
      <ellipse cx="12" cy="12" rx="9" ry="4.5" transform="rotate(-24 12 12)" />
    </>
  ),
  prism: (
    <>
      <path d="M12 3.5 20.5 19H3.5L12 3.5Z" />
      <path d="M12 3.5V19" />
    </>
  ),
  lattice: (
    <>
      <path d="M4 9h16M4 15h16" />
      <path d="M9 4v16M15 4v16" />
    </>
  ),
  aperture: (
    <>
      <path d="M12 3.5 20 8v8l-8 4.5L4 16V8l8-4.5Z" />
      <circle cx="12" cy="12" r="2.5" />
    </>
  ),
  meridian: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 3.5c3 2.4 4.5 5.2 4.5 8.5S15 18.1 12 20.5c-3-2.4-4.5-5.2-4.5-8.5S9 5.9 12 3.5Z" />
    </>
  ),
  cairn: (
    <>
      <path d="M8 19.5h8" />
      <rect x="6.5" y="14" width="11" height="4" rx="1.5" />
      <rect x="8.5" y="9" width="7" height="4" rx="1.5" />
      <circle cx="12" cy="5.5" r="2" />
    </>
  ),
  beacon: (
    <>
      <path d="M12 4v9" />
      <circle cx="12" cy="16.5" r="2.5" />
      <path d="M6.5 6.5 8.5 9M17.5 6.5 15.5 9" />
    </>
  ),
  helix: (
    <>
      <path d="M8 3.5c0 6 8 8.5 8 14.5" />
      <path d="M16 3.5c0 6-8 8.5-8 14.5" />
      <path d="M8.5 8.5h7M8.5 15.5h7" />
    </>
  ),
};

export function isAvatarMarkKey(value: string): value is AvatarMarkKey {
  return (AVATAR_MARK_KEYS as readonly string[]).includes(value);
}

/** Renders a stored `avatar_icon`. Unknown values render as text — see above. */
export function AvatarMark({ mark }: { mark: string }) {
  if (!isAvatarMarkKey(mark)) {
    return <span className="avatar-mark-legacy">{mark}</span>;
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {AVATAR_MARKS[mark]}
    </svg>
  );
}
