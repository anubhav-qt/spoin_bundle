"use client";

/**
 * The palette picker (F4, ADR-0012 + ADR-0070).
 *
 * Eleven built-in palettes plus any number of the reader's own saved themes,
 * all persisted SERVER-SIDE now (`lib/preferences.ts` → `/profile/me/preferences`);
 * `localStorage` is only the pre-paint cache. Selecting a swatch applies it live
 * and writes through — "click and it's saved", same as always.
 *
 * The dropdown is a fixed 3-row window: the presets fill it, saved themes beyond
 * that scroll rather than growing it. "Create your own theme" sits in its own
 * row above the grid (mirroring FontPicker's "Upload a font") so it stays
 * reachable however far the list is scrolled.
 */

import { useState, useSyncExternalStore } from "react";
import {
  PALETTE_DEV_CHOICE,
  PALETTE_NAMES,
  PALETTE_PRESETS,
} from "@/lib/appearancePresets";
import {
  deleteCustomPalette,
  getState,
  selectPalette,
  subscribe,
} from "@/lib/preferences";
import { CustomThemeModal } from "./CustomThemeModal";
import { PickerDropdown } from "./PickerDropdown";

interface Props {
  /** "pills" (default): the compact swatch grid. "dropdown": the same grid
   *  inside a labelled `PickerDropdown` for the desktop rail's utility row.
   *  "previews": the large onboarding layout with a live miniature card per
   *  palette (task 0002 — "not just color swatches"). */
  variant?: "pills" | "dropdown" | "previews";
  /** Called after a palette is applied — onboarding advances on it. */
  onChoose?: (key: string) => void;
}

function usePrefs() {
  return useSyncExternalStore(subscribe, getState, getState);
}

function swatchQuadrants(colors: [string, string, string, string]) {
  return colors.map((c, i) => <i key={i} style={{ background: c }} />);
}

export function ThemePicker({ variant = "pills", onChoose }: Props) {
  const prefs = usePrefs();
  const [editing, setEditing] = useState<string | null>(null); // palette id, or "new"

  const choose = (key: string) => {
    selectPalette(key);
    onChoose?.(key);
  };

  if (variant === "previews") {
    return (
      <div className="theme-picker theme-picker-previews" role="group" aria-label="Theme">
        {PALETTE_PRESETS.map(({ key, name }) => (
          <button
            key={key}
            type="button"
            className="theme-preview-option"
            data-active={prefs.palette === key}
            aria-pressed={prefs.palette === key}
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

  const grid = (
    <div className="theme-picker" role="group" aria-label="Theme">
      {PALETTE_PRESETS.map(({ key, name, swatch }) => (
        <button
          key={key}
          type="button"
          className="theme-pill"
          data-active={prefs.palette === key}
          data-devchoice={key === PALETTE_DEV_CHOICE || undefined}
          data-tooltip={key === PALETTE_DEV_CHOICE ? `${name} · developer's pick` : name}
          aria-pressed={prefs.palette === key}
          aria-label={key === PALETTE_DEV_CHOICE ? `${name} (developer's pick)` : name}
          onClick={() => choose(key)}
        >
          <span className="theme-pill-swatch">{swatchQuadrants(swatch)}</span>
        </button>
      ))}

      {prefs.customPalettes.map((pal) => {
        const key = `custom:${pal.id}`;
        return (
          <button
            key={pal.id}
            type="button"
            className="theme-pill theme-pill-saved"
            data-active={prefs.palette === key}
            data-tooltip={pal.name}
            aria-pressed={prefs.palette === key}
            aria-label={pal.name}
            onClick={() => choose(key)}
          >
            <span className="theme-pill-swatch">
              {swatchQuadrants([pal.bg, pal.accent, pal.accent2, pal.fg])}
            </span>
            <span
              className="pill-action pill-action-edit"
              role="button"
              tabIndex={-1}
              aria-label={`Edit ${pal.name}`}
              title="Rename or edit colours"
              onClick={(e) => {
                e.stopPropagation();
                setEditing(pal.id);
              }}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M14.5 5.5l4 4" />
                <path d="M4 20l1-4.5L15.5 5 19 8.5 8.5 19 4 20Z" />
              </svg>
            </span>
            <span
              className="pill-action pill-action-delete"
              role="button"
              tabIndex={-1}
              aria-label={`Delete ${pal.name}`}
              title="Delete this theme"
              onClick={(e) => {
                e.stopPropagation();
                setEditing(null);
                deleteCustomPalette(pal.id);
              }}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </span>
          </button>
        );
      })}
    </div>
  );

  const body = (
    <div className="appearance-menu">
      <div className="appearance-add-row">
        <button
          type="button"
          className="appearance-add-trigger"
          onClick={() => setEditing("new")}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="13.5" cy="6.5" r="2.5" />
            <circle cx="17.5" cy="12" r="2.5" />
            <circle cx="8.5" cy="7.5" r="2.5" />
            <circle cx="6.5" cy="12.5" r="2.5" />
            <path d="M12 22c-5 0-9-4-9-9a9 9 0 1 1 9 9c-1.1 0-1.8-.9-1.8-2 0-1 .8-1.8 1.8-1.8h1.2a2.8 2.8 0 0 0 2.8-2.8" />
          </svg>
          Create your own theme
        </button>
      </div>
      <div
        className={
          variant === "dropdown" ? "appearance-scroll appearance-scroll-3" : "appearance-open"
        }
      >
        {grid}
      </div>

      {editing !== null ? (
        <CustomThemeModal
          editId={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </div>
  );

  if (variant === "dropdown") {
    const label = prefs.palette.startsWith("custom:")
      ? prefs.customPalettes.find((p) => `custom:${p.id}` === prefs.palette)?.name ?? "Custom"
      : PALETTE_NAMES[prefs.palette] ?? "Notebook";
    return (
      <PickerDropdown label="Theme" value={label}>
        {body}
      </PickerDropdown>
    );
  }

  return body;
}
