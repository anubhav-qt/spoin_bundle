"use client";

/**
 * The user picks exactly 4 colors (background, text, accent, secondary
 * accent) -- everything else in a palette derives from those via
 * `[data-palette="custom"]`'s `color-mix` rules in globals.css, the same
 * technique `--topic-accent` already uses. Reuses the same
 * `.modal-overlay`/`.modal-panel` chrome as the font picker's
 * `CustomFontModal` and `TopicDiscoveryModal`, per how it was asked for.
 */

import { useState } from "react";
import { createPortal } from "react-dom";

export const CUSTOM_COLORS_KEY = "spoin-custom-colors";
const PALETTE_STORAGE_KEY = "spoin-palette";

export interface CustomColors {
  bg: string;
  fg: string;
  accent: string;
  accent2: string;
}

const DEFAULT_CUSTOM_COLORS: CustomColors = {
  bg: "#12141a",
  fg: "#e8eaf0",
  accent: "#7c9eff",
  accent2: "#ff9d7c",
};

export function readCustomColors(): CustomColors {
  try {
    const raw = localStorage.getItem(CUSTOM_COLORS_KEY);
    if (!raw) return DEFAULT_CUSTOM_COLORS;
    return { ...DEFAULT_CUSTOM_COLORS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_CUSTOM_COLORS;
  }
}

export function applyCustomColors(colors: CustomColors) {
  document.body.style.setProperty("--bg", colors.bg);
  document.body.style.setProperty("--fg", colors.fg);
  document.body.style.setProperty("--accent", colors.accent);
  document.body.style.setProperty("--accent-2", colors.accent2);
}

const FIELDS: { key: keyof CustomColors; label: string }[] = [
  { key: "bg", label: "Background" },
  { key: "fg", label: "Text" },
  { key: "accent", label: "Accent" },
  { key: "accent2", label: "Secondary accent" },
];

interface Props {
  onApplied: () => void;
  onClose: () => void;
}

export function CustomThemeModal({ onApplied, onClose }: Props) {
  const [colors, setColors] = useState<CustomColors>(() => readCustomColors());

  const setField = (key: keyof CustomColors, value: string) => {
    setColors((prev) => ({ ...prev, [key]: value }));
  };

  const apply = () => {
    document.body.dataset.palette = "custom";
    applyCustomColors(colors);
    localStorage.setItem(PALETTE_STORAGE_KEY, "custom");
    localStorage.setItem(CUSTOM_COLORS_KEY, JSON.stringify(colors));
    onApplied();
    onClose();
  };

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Custom theme"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title">Custom theme</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="custom-theme-fields">
          {FIELDS.map(({ key, label }) => (
            <label key={key} className="custom-theme-field">
              <span className="custom-theme-field-label">{label}</span>
              <span className="custom-theme-field-input">
                <input
                  type="color"
                  value={colors[key]}
                  onChange={(e) => setField(key, e.target.value)}
                  aria-label={label}
                />
                <span className="mono custom-theme-field-hex">{colors[key]}</span>
              </span>
            </label>
          ))}
        </div>

        <button type="button" className="custom-theme-apply" onClick={apply}>
          Apply
        </button>
      </div>
    </div>,
    document.body,
  );
}
