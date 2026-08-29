"use client";

/**
 * The font picker (F5, ADR-0023 / 0037 / 0070 / 0071).
 *
 * Twenty built-in faces plus any the reader has imported, all persisted
 * SERVER-SIDE (`lib/preferences.ts` → `/profile/me/preferences` + `/fonts`);
 * `localStorage` is only the pre-paint cache. Selecting a face applies it live
 * and saves immediately — no Keep/Revert (ADR-0071: it now matches
 * `ThemePicker`).
 *
 * Same 38px swatch-grid + fixed-height-scroll as `ThemePicker`, in a 5-row
 * window. "Upload a font" is its own row above the grid so it stays reachable
 * however far the (potentially long) list is scrolled; picking a file expands
 * an inline "name it" row — never a second popup.
 */

import { useRef, useState, useSyncExternalStore } from "react";
import { FONT_DEV_CHOICE, FONT_NAMES, FONT_PRESETS } from "@/lib/appearancePresets";
import {
  deleteImportedFont,
  getState,
  importFont,
  selectFont,
  subscribe,
} from "@/lib/preferences";
import { PickerDropdown } from "./PickerDropdown";

interface Props {
  /** "row" (default): the always-open grid. "dropdown": the same grid inside a
   *  labelled `PickerDropdown` for the desktop rail's utility row. */
  variant?: "row" | "dropdown";
}

const ACCEPT = ".woff2,.ttf,.otf,font/woff2,font/ttf,font/otf";

function stripExt(filename: string): string {
  return filename.replace(/\.(woff2|ttf|otf)$/i, "");
}

export function FontPicker({ variant = "row" }: Props) {
  const prefs = useSyncExternalStore(subscribe, getState, getState);
  const fileInput = useRef<HTMLInputElement>(null);

  const [pending, setPending] = useState<{ file: File; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onFile = (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setPending({ file, name: stripExt(file.name) });
  };

  const saveImport = async () => {
    if (!pending || !pending.name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await importFont(pending.file, pending.name);
      setPending(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not import that font.");
    } finally {
      setBusy(false);
    }
  };

  const importedActive = prefs.font.startsWith("import:");

  const body = (
    <div className="appearance-menu">
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          onFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      <div className="appearance-add-row">
        <button
          type="button"
          className="appearance-add-trigger"
          onClick={() => fileInput.current?.click()}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3v11" />
            <path d="M8 7l4-4 4 4" />
            <path d="M4.5 15v3.5A2.5 2.5 0 0 0 7 21h10a2.5 2.5 0 0 0 2.5-2.5V15" />
          </svg>
          Upload a font
        </button>

        {pending ? (
          <div className="font-import-row">
            <span className="font-import-file mono" title={pending.file.name}>
              {pending.file.name}
            </span>
            <input
              type="text"
              className="font-import-name"
              value={pending.name}
              maxLength={80}
              placeholder="Name this font"
              autoFocus
              onChange={(e) => setPending((p) => (p ? { ...p, name: e.target.value } : p))}
              onKeyDown={(e) => {
                if (e.key === "Enter") void saveImport();
                if (e.key === "Escape") setPending(null);
              }}
            />
            <button
              type="button"
              className="font-import-save"
              onClick={() => void saveImport()}
              disabled={busy || !pending.name.trim()}
            >
              {busy ? "…" : "Save"}
            </button>
          </div>
        ) : null}
        {error ? <p className="font-import-error mono">{error}</p> : null}
      </div>

      <div
        className={
          variant === "dropdown" ? "appearance-scroll appearance-scroll-5" : "appearance-open"
        }
      >
        <div className="font-picker-row" role="group" aria-label="Font">
          {FONT_PRESETS.map(({ key, name, family }) => (
            <button
              key={key}
              type="button"
              className="font-pill"
              data-active={prefs.font === key}
              data-devchoice={key === FONT_DEV_CHOICE || undefined}
              data-tooltip={key === FONT_DEV_CHOICE ? `${name} · developer's pick` : name}
              aria-pressed={prefs.font === key}
              aria-label={key === FONT_DEV_CHOICE ? `${name} (developer's pick)` : name}
              style={{ fontFamily: family }}
              onClick={() => selectFont(key)}
            >
              Aa
            </button>
          ))}

          {prefs.importedFonts.map((f) => {
            const key = `import:${f.id}`;
            return (
              <button
                key={f.id}
                type="button"
                className="font-pill font-pill-saved"
                data-active={prefs.font === key}
                data-tooltip={f.name}
                aria-pressed={prefs.font === key}
                aria-label={f.name}
                style={{ fontFamily: `"spoin-font-${f.id}", var(--font-sans)` }}
                onClick={() => selectFont(key)}
              >
                Aa
                <span
                  className="pill-action pill-action-delete"
                  role="button"
                  tabIndex={-1}
                  aria-label={`Remove ${f.name}`}
                  title="Remove this font"
                  onClick={(e) => {
                    e.stopPropagation();
                    void deleteImportedFont(f.id);
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
      </div>
    </div>
  );

  if (variant === "dropdown") {
    const label = importedActive
      ? prefs.importedFonts.find((f) => `import:${f.id}` === prefs.font)?.name ?? "Imported"
      : FONT_NAMES[prefs.font] ?? "Literata";
    return (
      <PickerDropdown label="Font" value={label} align="right">
        {body}
      </PickerDropdown>
    );
  }

  return body;
}
