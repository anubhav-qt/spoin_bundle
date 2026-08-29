/**
 * Appearance-preference store (ADR-0070).
 *
 * The palette, the user's saved themes and the font choice live on the server
 * now (`user_preference` / `user_font`, `/profile/me/preferences`). This module
 * is the client's single source of truth for them at runtime:
 *
 *   - `localStorage` is a PRE-PAINT CACHE, not the source of truth. The inline
 *     script in `app/layout.tsx` paints from it before React mounts; this
 *     module then reconciles against the server value once auth resolves
 *     (`reconcile`), and rewrites the cache to match.
 *   - Every mutation applies live, updates the cache in the same tick, and
 *     pushes to the server optimistically (a failed PUT leaves the local
 *     choice in place — a reload still shows it from the cache).
 *   - Imported fonts: the bytes are not in `localStorage`. Each is registered
 *     as an `@font-face` whose `src` is an authenticated object URL, so an
 *     imported font can briefly FOUT on a cold load where a built-in cannot.
 *
 * Components subscribe with `subscribe`; `ThemePicker` / `FontPicker` render
 * from `getState()`.
 */

import { api, type CustomPalette, type ImportedFont, type Preferences } from "./api";

// -- storage keys -------------------------------------------------------------
const K_PALETTE = "spoin-palette";
const K_CUSTOM_PALETTES = "spoin-custom-palettes";
const K_LEGACY_CUSTOM = "spoin-custom-colors"; // pre-ADR-0070 single custom slot
const K_FONT = "spoin-font";
const K_IMPORTED_FONTS = "spoin-imported-fonts"; // metadata only ({id,name,format})

export const DEFAULT_PALETTE = "notebook";
export const DEFAULT_FONT = "literata";

const CUSTOM_PROPS = ["--bg", "--fg", "--accent", "--accent-2"] as const;

export interface PrefState {
  palette: string;
  customPalettes: CustomPalette[];
  font: string;
  importedFonts: ImportedFont[];
}

let state: PrefState = {
  palette: DEFAULT_PALETTE,
  customPalettes: [],
  font: DEFAULT_FONT,
  importedFonts: [],
};

const listeners = new Set<() => void>();
let hydrated = false;

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** The current state. Side-effect-free so it is safe as a
 *  `useSyncExternalStore` snapshot — hydration runs from `PreferencesSync`'s
 *  mount effect and `reconcile`, never during render. */
export function getState(): PrefState {
  return state;
}

function notify() {
  for (const fn of listeners) fn();
}

// -- applying to the DOM ----------------------------------------------------

function applyPalette(key: string, customs: CustomPalette[]) {
  if (typeof document === "undefined") return;
  const body = document.body;
  for (const prop of CUSTOM_PROPS) body.style.removeProperty(prop);

  if (key.startsWith("custom:")) {
    const pal = customs.find((p) => p.id === key.slice("custom:".length));
    body.dataset.palette = "custom";
    if (pal) {
      body.style.setProperty("--bg", pal.bg);
      body.style.setProperty("--fg", pal.fg);
      body.style.setProperty("--accent", pal.accent);
      body.style.setProperty("--accent-2", pal.accent2);
    }
  } else {
    body.dataset.palette = key;
  }
}

function applyFont(key: string) {
  if (typeof document === "undefined") return;
  if (key === DEFAULT_FONT) document.body.removeAttribute("data-font");
  else document.body.dataset.font = key;
}

// -- imported-font @font-face registration --------------------------------
//
// One managed <style> element holds an @font-face plus a
// `[data-font="import:<id>"]` rule per imported font. The @font-face `src`
// points at an object URL from an authenticated fetch (the endpoint is behind
// a Bearer token; a bare url() would 401 — same problem avatars have).

const FACE_STYLE_ID = "spoin-imported-font-faces";
const registeredFonts = new Map<string, string>(); // id -> object URL

function faceStyleEl(): HTMLStyleElement | null {
  if (typeof document === "undefined") return null;
  let el = document.getElementById(FACE_STYLE_ID) as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement("style");
    el.id = FACE_STYLE_ID;
    document.head.appendChild(el);
  }
  return el;
}

function rebuildFaceStyle() {
  const el = faceStyleEl();
  if (!el) return;
  const rules: string[] = [];
  for (const [id, url] of registeredFonts) {
    const family = `spoin-font-${id}`;
    rules.push(
      `@font-face{font-family:"${family}";src:url("${url}");font-display:swap}`,
      `[data-font="import:${id}"]{--font-sans:"${family}",ui-sans-serif,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}`,
    );
  }
  el.textContent = rules.join("\n");
}

async function ensureFontFace(id: string) {
  if (registeredFonts.has(id)) return;
  try {
    const url = await api.fontObjectUrl(id);
    registeredFonts.set(id, url);
    rebuildFaceStyle();
    // If this font is the active one, re-apply so the now-present rule wins.
    if (state.font === `import:${id}`) applyFont(state.font);
  } catch {
    // Font bytes unreachable (offline, deleted server-side). The rule is
    // absent, so `--font-sans` stays on the fallback stack — no crash.
  }
}

function unregisterFontFace(id: string) {
  const url = registeredFonts.get(id);
  if (url) {
    URL.revokeObjectURL(url);
    registeredFonts.delete(id);
    rebuildFaceStyle();
  }
}

// -- cache (localStorage) ------------------------------------------------

function readJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeCache() {
  try {
    localStorage.setItem(K_PALETTE, state.palette);
    localStorage.setItem(K_CUSTOM_PALETTES, JSON.stringify(state.customPalettes));
    localStorage.setItem(K_FONT, state.font);
    localStorage.setItem(
      K_IMPORTED_FONTS,
      JSON.stringify(
        state.importedFonts.map((f) => ({ id: f.id, name: f.name, format: f.format })),
      ),
    );
  } catch {
    // Private mode / quota — the app still works, it just flashes the default
    // on the next cold load. Not worth failing a theme change over.
  }
}

/** Read the cache into state and apply it. Idempotent; safe to call on every
 *  `getState`. Also performs the one-time migration of the pre-ADR-0070 single
 *  `custom` slot into a named entry in the list. */
export function hydrateFromCache() {
  if (typeof window === "undefined") return;
  hydrated = true;

  let palette = localStorage.getItem(K_PALETTE) ?? DEFAULT_PALETTE;
  let customPalettes = readJSON<CustomPalette[]>(K_CUSTOM_PALETTES, []);
  const font = localStorage.getItem(K_FONT) ?? DEFAULT_FONT;
  const importedMeta = readJSON<Array<{ id: string; name: string; format: string }>>(
    K_IMPORTED_FONTS,
    [],
  );

  // Legacy: `palette === "custom"` + a `spoin-custom-colors` object. Fold it
  // into the list as "My theme" and repoint `palette` at it.
  if (palette === "custom") {
    const legacy = readJSON<
      { bg: string; fg: string; accent: string; accent2: string } | null
    >(K_LEGACY_CUSTOM, null);
    if (legacy && !customPalettes.length) {
      const id = cryptoRandomId();
      customPalettes = [{ id, name: "My theme", ...legacy }];
      palette = `custom:${id}`;
    } else if (customPalettes.length) {
      palette = `custom:${customPalettes[0].id}`;
    }
  }

  state = {
    palette,
    customPalettes,
    font,
    importedFonts: importedMeta.map((m) => ({ ...m, byte_size: 0 })),
  };

  applyPalette(state.palette, state.customPalettes);
  applyFont(state.font);
  for (const f of state.importedFonts) void ensureFontFace(f.id);
  writeCache();
  notify();
}

// -- server sync ------------------------------------------------------------

let pushTimer: ReturnType<typeof setTimeout> | null = null;

function pushToServer() {
  if (pushTimer) clearTimeout(pushTimer);
  pushTimer = setTimeout(() => {
    pushTimer = null;
    void api
      .updatePreferences({
        palette: state.palette,
        custom_palettes: state.customPalettes,
        font: state.font,
      })
      .catch(() => {
        // Optimistic: the local choice and its cache already stand. A guest
        // with no token, an offline blip, a transient 5xx — none of them
        // should revert a setting the user just made. It reconciles on the
        // next `/auth/me`.
      });
  }, 400);
}

/** Server is the source of truth. Called once auth resolves (the `/auth/me`
 *  payload carries `preferences`). Applies the server value if it differs from
 *  what the inline script painted, registers any imported fonts, and rewrites
 *  the cache. */
export function reconcile(server: Preferences) {
  if (!hydrated) hydrateFromCache();

  const prevIds = new Set(state.importedFonts.map((f) => f.id));
  state = {
    palette: server.palette,
    customPalettes: server.custom_palettes,
    font: server.font,
    importedFonts: server.imported_fonts,
  };

  for (const f of server.imported_fonts) void ensureFontFace(f.id);
  for (const id of prevIds) {
    if (!server.imported_fonts.some((f) => f.id === id)) unregisterFontFace(id);
  }

  applyPalette(state.palette, state.customPalettes);
  applyFont(state.font);
  writeCache();
  notify();
}

// -- mutations ------------------------------------------------------------

export function selectPalette(key: string) {
  state = { ...state, palette: key };
  applyPalette(key, state.customPalettes);
  writeCache();
  notify();
  pushToServer();
}

export function selectFont(key: string) {
  state = { ...state, font: key };
  applyFont(key);
  writeCache();
  notify();
  pushToServer();
}

/** Add a new saved theme (no `id`) or update an existing one (`id` present),
 *  and make it active. */
export function saveCustomPalette(input: Omit<CustomPalette, "id"> & { id?: string }) {
  const id = input.id ?? cryptoRandomId();
  const entry: CustomPalette = { ...input, id };
  const existing = state.customPalettes.some((p) => p.id === id);
  const customPalettes = existing
    ? state.customPalettes.map((p) => (p.id === id ? entry : p))
    : [...state.customPalettes, entry];

  state = { ...state, customPalettes, palette: `custom:${id}` };
  applyPalette(state.palette, customPalettes);
  writeCache();
  notify();
  pushToServer();
  return id;
}

export function deleteCustomPalette(id: string) {
  const customPalettes = state.customPalettes.filter((p) => p.id !== id);
  const palette = state.palette === `custom:${id}` ? DEFAULT_PALETTE : state.palette;
  state = { ...state, customPalettes, palette };
  applyPalette(palette, customPalettes);
  writeCache();
  notify();
  pushToServer();
}

/** Upload a font, register it, and (by default) make it active. */
export async function importFont(file: File, name: string, activate = true) {
  const meta = await api.uploadFont(file, name.trim());
  await ensureFontFace(meta.id);
  state = { ...state, importedFonts: [...state.importedFonts, meta] };
  if (activate) state = { ...state, font: `import:${meta.id}` };
  applyFont(state.font);
  writeCache();
  notify();
  // The font row already exists server-side; this just points `font` at it.
  if (activate) pushToServer();
  return meta;
}

export async function deleteImportedFont(id: string) {
  await api.deleteFont(id);
  unregisterFontFace(id);
  const importedFonts = state.importedFonts.filter((f) => f.id !== id);
  const font = state.font === `import:${id}` ? DEFAULT_FONT : state.font;
  state = { ...state, importedFonts, font };
  applyFont(font);
  writeCache();
  notify();
  if (state.font === DEFAULT_FONT) pushToServer();
}

// -- helpers ------------------------------------------------------------

function cryptoRandomId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `id-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
  }
}

/** The resolved four colours for a `custom:<id>` palette, or null. Used by the
 *  swatch preview and the edit modal's initial values. */
export function customPaletteColors(key: string): CustomPalette | null {
  if (!key.startsWith("custom:")) return null;
  return state.customPalettes.find((p) => p.id === key.slice("custom:".length)) ?? null;
}
