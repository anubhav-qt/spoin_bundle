/**
 * The app's single loading indicator: the "spoin" wordmark with each glyph
 * lifting on a staggered baseline wave, the "o" carrying the accent hue.
 *
 * Pure CSS animation, no JS timers — it paints correctly the moment the
 * pre-hydration palette script has run, and it costs nothing to mount. This
 * replaces every ad-hoc CSS spinner in the app (F12; concepts in
 * docs/design/mockups/loader-concepts/, "Wave" chosen).
 *
 *  - `page`   — full-viewport blocking state (the AuthProvider gate a
 *               deep link hits before auth resolves).
 *  - `inline` — sits inside a button or a line of text. Every glyph takes
 *               `currentColor` so it stays legible on a filled button;
 *               `caption` adds a short visible label beside it (modals).
 *
 * `prefers-reduced-motion` (and Settings' opt-in `data-reduced-motion`)
 * freeze the wave flat rather than blanking it — see globals.css.
 */
import type { CSSProperties } from "react";

const GLYPHS = ["s", "p", "o", "i", "n"] as const;

export function SpoinWave({
  variant = "inline",
  label = "Loading",
  caption,
}: {
  variant?: "page" | "inline";
  /** Accessible name announced to assistive tech. */
  label?: string;
  /** Optional short visible text beside the wave (inline variant only). */
  caption?: string;
}) {
  const wave = (
    <span className="spoin-wave" data-variant={variant} role="status" aria-label={caption ?? label}>
      <span className="spoin-wave-glyphs" aria-hidden="true">
        {GLYPHS.map((g, i) => (
          <span key={g} style={{ "--i": i } as CSSProperties}>
            {g}
          </span>
        ))}
      </span>
      {caption && variant === "inline" ? <span className="spoin-wave-cap">{caption}</span> : null}
    </span>
  );

  return variant === "page" ? <div className="page-loader">{wave}</div> : wave;
}
