"use client";

/**
 * ADR-0023's five faces, wired up by ADR-0037. Sits next to ThemePicker,
 * same [data-*] + localStorage mechanism — but unlike ThemePicker's
 * click-and-it's-saved behavior, a selection here previews live without
 * persisting, and the row shows a Keep/Revert confirmation until resolved.
 * Legibility is harder to judge from a small swatch than color is, so this
 * lets a reader try a face against real content before committing.
 */

import { useEffect, useState } from "react";
import { CustomFontModal } from "./CustomFontModal";
import { PickerDropdown } from "./PickerDropdown";

const STORAGE_KEY = "spoin-font";
const DEFAULT_FONT = "literata";
// Not the default (that stays Literata, ADR-0037) — just a marked
// recommendation in the picker. See ADR-0037's "developer's pick" note.
const DEV_CHOICE = "grotesk";

const FONTS = [
  { key: "literata", name: "Literata" },
  { key: "inter", name: "Inter" },
  { key: "grotesk", name: "Space Grotesk" },
  { key: "jetbrains", name: "JetBrains Mono" },
  { key: "hyperlegible", name: "Atkinson Hyperlegible" },
] as const;

export function applyFont(key: string) {
  if (key === DEFAULT_FONT) {
    document.body.removeAttribute("data-font");
  } else {
    document.body.dataset.font = key;
  }
}

export function persistFont(key: string) {
  localStorage.setItem(STORAGE_KEY, key);
}

function persistedFont(): string {
  return localStorage.getItem(STORAGE_KEY) ?? DEFAULT_FONT;
}

const FONT_NAME: Record<string, string> = Object.fromEntries(FONTS.map((f) => [f.key, f.name]));

interface Props {
  /** "row" (default): the always-open `Aa` swatch row (right-rail sheet /
   *  mobile Browse). "dropdown": the same row inside a labelled
   *  `PickerDropdown` for the desktop rail's four-up utility row. */
  variant?: "row" | "dropdown";
}

export function FontPicker({ variant = "row" }: Props) {
  const [active, setActive] = useState(DEFAULT_FONT);
  // The persisted value being previewed away from — null while there is no
  // pending preview (the row shows no Keep/Revert). Set the moment a
  // different face is clicked, cleared on Keep or Revert.
  const [pendingFrom, setPendingFrom] = useState<string | null>(null);
  const [customOpen, setCustomOpen] = useState(false);

  useEffect(() => {
    setActive(document.body.dataset.font ?? DEFAULT_FONT);
  }, []);

  const preview = (key: string) => {
    const saved = persistedFont();
    applyFont(key);
    setActive(key);
    // Selecting the already-persisted face is not a preview — nothing to
    // confirm or revert.
    setPendingFrom(key === saved ? null : saved);
  };

  const keep = () => {
    localStorage.setItem(STORAGE_KEY, active);
    setPendingFrom(null);
  };

  const revert = () => {
    if (pendingFrom === null) return;
    applyFont(pendingFrom);
    setActive(pendingFrom);
    setPendingFrom(null);
  };

  const isPreset = FONTS.some((f) => f.key === active);

  const body = (
    <div className="font-picker">
      <div className="font-picker-row" role="group" aria-label="Font">
        {FONTS.map(({ key, name }) => (
          <button
            key={key}
            type="button"
            className="font-pill"
            data-active={active === key}
            data-devchoice={key === DEV_CHOICE || undefined}
            data-tooltip={key === DEV_CHOICE ? `${name} · developer's pick` : name}
            aria-pressed={active === key}
            aria-label={key === DEV_CHOICE ? `${name} (developer's pick)` : name}
            style={{ fontFamily: `var(--font-${key})` }}
            onClick={() => preview(key)}
          >
            Aa
          </button>
        ))}
        <button
          type="button"
          className="font-pill font-pill-custom"
          data-active={!isPreset}
          data-tooltip="Custom font"
          aria-pressed={!isPreset}
          aria-label="Custom font"
          onClick={() => setCustomOpen(true)}
        >
          +
        </button>
      </div>

      {pendingFrom !== null ? (
        <div className="font-picker-confirm">
          <span className="mono">Keep this font?</span>
          <button type="button" className="font-picker-keep" onClick={keep}>
            Keep
          </button>
          <button type="button" className="font-picker-revert" onClick={revert}>
            Revert
          </button>
        </div>
      ) : null}

      {customOpen ? (
        <CustomFontModal
          active={active}
          onSelect={(key) => {
            setActive(key);
            setPendingFrom(null);
          }}
          onClose={() => setCustomOpen(false)}
        />
      ) : null}
    </div>
  );

  if (variant === "dropdown") {
    return (
      <PickerDropdown label="Font" value={FONT_NAME[active] ?? "Custom"} align="right">
        {body}
      </PickerDropdown>
    );
  }

  return body;
}
