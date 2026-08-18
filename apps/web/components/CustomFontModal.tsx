"use client";

/**
 * The expanded font list (ADR-0037's five presets don't have room for every
 * bundled face) — reuses the same `.modal-overlay`/`.modal-panel` chrome as
 * `TopicDiscoveryModal`/theme picker's `CustomThemeModal`, per how it was
 * asked for: theme and font pickers should share one popup design.
 *
 * Unlike the preset row's hover-preview + Keep/Revert dance, a pick here
 * applies and persists immediately — the modal itself is already the
 * deliberate "I'm choosing a font" action, so there's nothing left to confirm.
 */

import { createPortal } from "react-dom";
import { applyFont, persistFont } from "./FontPicker";

interface Props {
  active: string;
  onSelect: (key: string) => void;
  onClose: () => void;
}

// ADR-0038: expanded from 5 to 51 faces. The first 5 are self-hosted via
// next/font/google (layout.tsx); the other 46 load from one batched Google
// Fonts stylesheet request -- see the comment on EXTRA_GOOGLE_FONTS_HREF in
// layout.tsx for why those two groups use different mechanisms.
const EXTRA_FONTS = [
  { key: "fraunces", name: "Fraunces", hint: "Warm, expressive serif" },
  { key: "manrope", name: "Manrope", hint: "Clean, modern sans" },
  { key: "zilla", name: "Zilla Slab", hint: "Sturdy slab serif" },
  { key: "courier", name: "Courier Prime", hint: "Typewriter monospace" },
  { key: "comfortaa", name: "Comfortaa", hint: "Rounded, friendly" },

  // -- serif --
  { key: "merriweather", name: "Merriweather", hint: "Classic literary serif" },
  { key: "playfair", name: "Playfair Display", hint: "High-contrast display serif" },
  { key: "lora", name: "Lora", hint: "Balanced, calligraphic serif" },
  { key: "crimson", name: "Crimson Text", hint: "Book-style old-style serif" },
  { key: "garamond", name: "EB Garamond", hint: "Renaissance-era serif" },
  { key: "bitter", name: "Bitter", hint: "Slab serif built for screens" },
  { key: "ptserif", name: "PT Serif", hint: "Transitional text serif" },
  { key: "sourceserif", name: "Source Serif", hint: "Adobe's text serif" },
  { key: "baskerville", name: "Libre Baskerville", hint: "Web-optimized Baskerville" },
  { key: "cormorant", name: "Cormorant", hint: "Elegant display serif" },
  { key: "spectral", name: "Spectral", hint: "Screen-first text serif" },
  { key: "notoserif", name: "Noto Serif", hint: "Wide-coverage serif" },
  { key: "vollkorn", name: "Vollkorn", hint: "German book serif" },
  { key: "domine", name: "Domine", hint: "Sturdy, confident text serif" },
  { key: "alegreya", name: "Alegreya", hint: "Literature-inspired serif" },

  // -- sans --
  { key: "roboto", name: "Roboto", hint: "Google's default sans" },
  { key: "opensans", name: "Open Sans", hint: "Humanist workhorse sans" },
  { key: "lato", name: "Lato", hint: "Warm, semi-rounded sans" },
  { key: "montserrat", name: "Montserrat", hint: "Geometric urban sans" },
  { key: "poppins", name: "Poppins", hint: "Geometric rounded sans" },
  { key: "nunito", name: "Nunito", hint: "Rounded, friendly sans" },
  { key: "worksans", name: "Work Sans", hint: "Optimized for on-screen text" },
  { key: "rubik", name: "Rubik", hint: "Slightly rounded grotesque" },
  { key: "karla", name: "Karla", hint: "Grotesque with quirky details" },
  { key: "mulish", name: "Mulish", hint: "Minimalist, low-contrast sans" },
  { key: "dmsans", name: "DM Sans", hint: "Low-contrast geometric sans" },
  { key: "sora", name: "Sora", hint: "Modern, technical sans" },
  { key: "outfit", name: "Outfit", hint: "Clean geometric sans" },
  { key: "plusjakarta", name: "Plus Jakarta Sans", hint: "Rounded geometric sans" },
  { key: "publicsans", name: "Public Sans", hint: "US government's open sans" },
  { key: "barlow", name: "Barlow", hint: "Slightly condensed grotesque" },
  { key: "urbanist", name: "Urbanist", hint: "Low-contrast geometric sans" },
  { key: "figtree", name: "Figtree", hint: "Friendly rounded sans" },
  { key: "ibmplexsans", name: "IBM Plex Sans", hint: "Corporate neutral sans" },
  { key: "raleway", name: "Raleway", hint: "Elegant thin-weight sans" },

  // -- slab / display serif --
  { key: "robotoslab", name: "Roboto Slab", hint: "Roboto's slab-serif sibling" },
  { key: "arvo", name: "Arvo", hint: "Geometric slab serif" },
  { key: "bevan", name: "Bevan", hint: "Bold display slab" },

  // -- monospace --
  { key: "firacode", name: "Fira Code", hint: "Coding font with ligatures" },
  { key: "sourcecodepro", name: "Source Code Pro", hint: "Adobe's monospace" },
  { key: "ibmplexmono", name: "IBM Plex Mono", hint: "Corporate monospace" },
  { key: "spacemono", name: "Space Mono", hint: "Quirky fixed-width face" },
  { key: "robotomono", name: "Roboto Mono", hint: "Roboto's monospace sibling" },
  { key: "inconsolata", name: "Inconsolata", hint: "Humanist monospace" },

  // -- display / handwriting --
  { key: "caveat", name: "Caveat", hint: "Casual handwriting" },
  { key: "bebasneue", name: "Bebas Neue", hint: "Tall condensed display" },
] as const;

export function CustomFontModal({ active, onSelect, onClose }: Props) {
  const choose = (key: string) => {
    applyFont(key);
    persistFont(key);
    onSelect(key);
  };

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Custom font"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title">More fonts</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="custom-font-list">
          {EXTRA_FONTS.map(({ key, name, hint }) => (
            <button
              key={key}
              type="button"
              className="custom-font-row"
              data-active={active === key}
              onClick={() => choose(key)}
              style={{ fontFamily: `var(--font-${key})` }}
            >
              <span className="custom-font-row-sample">Aa</span>
              <span className="custom-font-row-text">
                <span className="custom-font-row-name">{name}</span>
                <span className="custom-font-row-hint mono">{hint}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
