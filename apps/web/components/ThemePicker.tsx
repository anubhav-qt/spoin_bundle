"use client";

/**
 * Five palette swatches (ADR-0012's committed set), switched live and persisted
 * to `localStorage`. The pre-hydration flash is handled separately by the
 * inline script in `app/layout.tsx` — this component's own effect only needs
 * to cover the case where nothing has been picked yet.
 *
 * Each swatch shows the palette's four main tokens as quadrants rather than a
 * single blended gradient — it reads as "here's the palette" instead of "here's
 * a color." The name shows on hover via a pure-CSS tooltip (`data-tooltip` +
 * `::after`), no extra DOM needed.
 */

import { useEffect, useState } from "react";

const STORAGE_KEY = "slocho-palette";
const DEFAULT_PALETTE = "notebook";

const PALETTES = [
  { key: "notebook", name: "Notebook" },
  { key: "copper", name: "Copper Board" },
  // Display names, not the `data-palette`/localStorage keys (ADR-0016 kept
  // the keys "cyanotype"/"phosphor" stable for persistence, but their
  // identities changed entirely, so the name shown on hover is renamed to
  // match what they actually look like now.
  { key: "cyanotype", name: "Skylight" },
  { key: "phosphor", name: "Obsidian" },
  { key: "scope", name: "Oscilloscope" },
] as const;

export function ThemePicker() {
  const [active, setActive] = useState(DEFAULT_PALETTE);

  useEffect(() => {
    setActive(document.body.dataset.palette ?? DEFAULT_PALETTE);
  }, []);

  const choose = (key: string) => {
    document.body.dataset.palette = key;
    localStorage.setItem(STORAGE_KEY, key);
    setActive(key);
  };

  return (
    <div className="theme-picker" role="group" aria-label="Theme">
      {PALETTES.map(({ key, name }) => (
        <button
          key={key}
          type="button"
          className="theme-pill"
          data-active={active === key}
          data-tooltip={name}
          aria-pressed={active === key}
          aria-label={name}
          onClick={() => choose(key)}
        >
          <span className="theme-pill-swatch" data-palette-preview={key}>
            <i />
            <i />
            <i />
            <i />
          </span>
        </button>
      ))}
    </div>
  );
}
