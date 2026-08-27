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
import { CustomThemeModal } from "./CustomThemeModal";
import { PickerDropdown } from "./PickerDropdown";

const STORAGE_KEY = "spoin-palette";
// Developer-taste default (ADR-0012's note): the app boots Obsidian, not
// Notebook. `app/layout.tsx`'s pre-hydration script writes this same value
// when nothing is stored, so `document.body.dataset.palette` is always set by
// the time this component's effect runs.
const DEFAULT_PALETTE = "phosphor";

const PALETTES = [
  { key: "notebook", name: "Notebook" },
  // ADR-0038: replaces Copper Board with the colors CustomThemeModal already
  // shipped as its own defaults, committed as a real preset.
  { key: "twilight", name: "Twilight" },
  // Display names, not the `data-palette`/localStorage keys (ADR-0016 kept
  // the keys "cyanotype"/"phosphor" stable for persistence, but their
  // identities changed entirely, so the name shown on hover is renamed to
  // match what they actually look like now.
  { key: "cyanotype", name: "Skylight" },
  { key: "phosphor", name: "Obsidian" },
  { key: "scope", name: "Oscilloscope" },
] as const;

//: A custom palette's 4 colors live as inline styles on <body> (see
//: CustomThemeModal) -- inline style beats any attribute-selector rule, so
//: switching to a PRESET must clear them or the preset would silently stay
//: tinted by whatever custom colors were set last.
const CUSTOM_PROPERTIES = ["--bg", "--fg", "--accent", "--accent-2"];

interface Props {
  /** "pills" (default): the compact swatch row (right-rail sheet / mobile
   *  Browse). "dropdown": the same row inside a labelled `PickerDropdown`, for
   *  the desktop rail's four-up utility row. "previews": the large onboarding
   *  layout with a live miniature card per palette (task 0002 — "not just
   *  color swatches"). Same component, same persistence, per that task's "do
   *  not build two different pickers" requirement. */
  variant?: "pills" | "dropdown" | "previews";
  /** Called after a palette is applied — onboarding uses this to know it's
   *  safe to advance past the step, without re-deriving it from localStorage. */
  onChoose?: (key: string) => void;
}

const PALETTE_NAME: Record<string, string> = {
  ...Object.fromEntries(PALETTES.map((p) => [p.key, p.name])),
  custom: "Custom",
};

export function ThemePicker({ variant = "pills", onChoose }: Props) {
  const [active, setActive] = useState(DEFAULT_PALETTE);
  const [customOpen, setCustomOpen] = useState(false);

  useEffect(() => {
    setActive(document.body.dataset.palette ?? DEFAULT_PALETTE);
  }, []);

  const choose = (key: string) => {
    for (const prop of CUSTOM_PROPERTIES) document.body.style.removeProperty(prop);
    document.body.dataset.palette = key;
    localStorage.setItem(STORAGE_KEY, key);
    setActive(key);
    onChoose?.(key);
  };

  if (variant === "previews") {
    return (
      <div className="theme-picker theme-picker-previews" role="group" aria-label="Theme">
        {PALETTES.map(({ key, name }) => (
          <button
            key={key}
            type="button"
            className="theme-preview-option"
            data-active={active === key}
            aria-pressed={active === key}
            onClick={() => choose(key)}
          >
            <span className="theme-preview-card" data-palette={key}>
              <span className="theme-preview-card-inner">
                <span className="theme-preview-card-topic">Sample topic</span>
                <span className="theme-preview-card-title">A card looks like this</span>
                <span className="theme-preview-card-summary">
                  Swipe, read, and quiz through cards styled in {name}.
                </span>
              </span>
            </span>
            <span className="theme-preview-name">{name}</span>
          </button>
        ))}
      </div>
    );
  }

  const pills = (
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

      <button
        type="button"
        className="theme-pill theme-pill-custom"
        data-active={active === "custom"}
        data-tooltip="Custom theme"
        aria-pressed={active === "custom"}
        aria-label="Custom theme"
        onClick={() => setCustomOpen(true)}
      >
        <span className="theme-pill-swatch theme-pill-swatch-custom">+</span>
      </button>

      {customOpen ? (
        <CustomThemeModal onApplied={() => setActive("custom")} onClose={() => setCustomOpen(false)} />
      ) : null}
    </div>
  );

  if (variant === "dropdown") {
    return (
      <PickerDropdown label="Theme" value={PALETTE_NAME[active] ?? "Obsidian"}>
        {pills}
      </PickerDropdown>
    );
  }

  return pills;
}
