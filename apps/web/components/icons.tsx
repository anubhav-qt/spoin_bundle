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

export function CompassIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="m14.5 9.5-2 5-5 2 2-5 5-2Z" />
    </svg>
  );
}

export function UserIcon(_: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
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
