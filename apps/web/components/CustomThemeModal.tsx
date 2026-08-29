"use client";

/**
 * Create or edit one saved theme (F4, ADR-0070).
 *
 * The reader picks a name and exactly four colours (background, text, accent,
 * secondary accent); everything else in the palette derives from those via
 * `[data-palette="custom"]`'s `color-mix` rules in `globals.css`. Saving writes
 * through `lib/preferences.ts` (server + cache) and makes the theme active.
 *
 * "Delete this theme" only appears when editing an existing saved theme, not
 * when creating a new one — unchanged from the modal's earlier chrome.
 */

import { useState } from "react";
import { createPortal } from "react-dom";
import type { CustomPalette } from "@/lib/api";
import {
  deleteCustomPalette,
  getState,
  saveCustomPalette,
} from "@/lib/preferences";

const DEFAULT_COLORS = {
  bg: "#12141a",
  fg: "#e8eaf0",
  accent: "#7c9eff",
  accent2: "#ff9d7c",
};

const FIELDS: { key: keyof typeof DEFAULT_COLORS; label: string }[] = [
  { key: "bg", label: "Background" },
  { key: "fg", label: "Text" },
  { key: "accent", label: "Accent" },
  { key: "accent2", label: "Secondary accent" },
];

interface Props {
  /** An existing saved-theme id to edit, or `null` to create a new one. */
  editId: string | null;
  onClose: () => void;
}

export function CustomThemeModal({ editId, onClose }: Props) {
  const existing: CustomPalette | undefined = editId
    ? getState().customPalettes.find((p) => p.id === editId)
    : undefined;

  const [name, setName] = useState(existing?.name ?? "");
  const [colors, setColors] = useState({
    bg: existing?.bg ?? DEFAULT_COLORS.bg,
    fg: existing?.fg ?? DEFAULT_COLORS.fg,
    accent: existing?.accent ?? DEFAULT_COLORS.accent,
    accent2: existing?.accent2 ?? DEFAULT_COLORS.accent2,
  });

  const setField = (key: keyof typeof DEFAULT_COLORS, value: string) =>
    setColors((prev) => ({ ...prev, [key]: value }));

  const trimmed = name.trim();
  const canSave = trimmed.length > 0;

  const save = () => {
    if (!canSave) return;
    saveCustomPalette({ id: editId ?? undefined, name: trimmed, ...colors });
    onClose();
  };

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label={editId ? "Edit theme" : "New theme"}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title">{editId ? "Edit theme" : "New theme"}</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>

        <label className="custom-theme-name">
          <span className="custom-theme-field-label">Name</span>
          <input
            type="text"
            value={name}
            maxLength={40}
            placeholder="Sunset Desk"
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </label>

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

        <button
          type="button"
          className="custom-theme-apply"
          onClick={save}
          disabled={!canSave}
        >
          {editId ? "Save changes" : "Save theme"}
        </button>

        {editId ? (
          <button
            type="button"
            className="custom-theme-delete"
            onClick={() => {
              deleteCustomPalette(editId);
              onClose();
            }}
          >
            Delete this theme
          </button>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
