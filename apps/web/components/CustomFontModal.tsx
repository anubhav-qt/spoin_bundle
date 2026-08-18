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

const EXTRA_FONTS = [
  { key: "fraunces", name: "Fraunces", hint: "Warm, expressive serif" },
  { key: "manrope", name: "Manrope", hint: "Clean, modern sans" },
  { key: "zilla", name: "Zilla Slab", hint: "Sturdy slab serif" },
  { key: "courier", name: "Courier Prime", hint: "Typewriter monospace" },
  { key: "comfortaa", name: "Comfortaa", hint: "Rounded, friendly" },
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
