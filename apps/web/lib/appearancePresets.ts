/**
 * The built-in palette and font lists shown in the appearance pickers (F4/F5).
 *
 * Curated 2026-08-30 for spread, not volume — see
 * `docs/design/mockups/appearance-pickers.html` and
 * `docs/handoff/v1-finish-line-plan.md`. Every palette's tokens live in
 * `app/globals.css` (`[data-palette="<key>"]`); every font key resolves through a
 * `[data-font="<key>"]` rule there too. Keys are the persisted values (ADR-0016
 * kept `cyanotype`/`phosphor`/`scope` stable even though their identities
 * changed) — never rename a key, only its display `name`.
 */

export interface PalettePreset {
  key: string;
  name: string;
  /** The four swatch quadrants: bg, accent, accent-2, and a fourth palette
   *  colour (`--good` or the secondary channel). Rendered inline so the picker
   *  needs no per-palette CSS. */
  swatch: [string, string, string, string];
}

/** The palette shown with a "developer's pick" dot (ADR-0012) — cosmetic, not
 *  the default. */
export const PALETTE_DEV_CHOICE = "phosphor";

/** 11 palettes, ordered light → dark. Notebook is the default (no `[data-palette]`
 *  needed — it is `:root`). */
export const PALETTE_PRESETS: PalettePreset[] = [
  { key: "notebook", name: "Notebook", swatch: ["#edf0ea", "#c1442b", "#a83a24", "#4c7a5a"] },
  { key: "cyanotype", name: "Skylight", swatch: ["#e8f0f7", "#3f7ea3", "#2f6486", "#4a8f76"] },
  { key: "daylight", name: "Daylight", swatch: ["#ffffff", "#0b5cc4", "#084a9e", "#1f7a4d"] },
  { key: "terracotta", name: "Terracotta", swatch: ["#f4ece1", "#a8482c", "#8a5a34", "#5c7a5f"] },
  { key: "meadow", name: "Meadow", swatch: ["#eef2e6", "#2c7038", "#b0592a", "#7a8a4a"] },
  { key: "fog", name: "Fog", swatch: ["#eeeeec", "#4b5a63", "#37444b", "#5a7a6a"] },
  { key: "twilight", name: "Twilight", swatch: ["#12141a", "#7c9eff", "#ff9d7c", "#83d9a3"] },
  { key: "scope", name: "Oscilloscope", swatch: ["#0d1116", "#38c6d9", "#e8a33d", "#38c6d9"] },
  { key: "ember", name: "Ember", swatch: ["#191512", "#e0894a", "#c96f4f", "#9bb08a"] },
  { key: "amethyst", name: "Amethyst", swatch: ["#17141c", "#b492f0", "#f0b28a", "#8ad0b0"] },
  { key: "phosphor", name: "Obsidian", swatch: ["#0b0b0c", "#f4f4f5", "#d4d4d6", "#b8b8ba"] },
];

export interface FontPreset {
  key: string;
  name: string;
  /** CSS `font-family` for the live "Aa" preview. Self-hosted faces
   *  (`next/font/google` in `app/layout.tsx`) use their `--font-*` variable;
   *  the batched-CSS2 faces are referenced by literal family name. */
  family: string;
}

/** The font shown with a "developer's pick" dot (ADR-0037). */
export const FONT_DEV_CHOICE = "grotesk";

/** 20 faces, grouped serif → slab → sans → rounded → display → mono. */
export const FONT_PRESETS: FontPreset[] = [
  { key: "literata", name: "Literata", family: "var(--font-literata)" },
  { key: "sourceserif", name: "Source Serif 4", family: '"Source Serif 4"' },
  { key: "lora", name: "Lora", family: '"Lora"' },
  { key: "garamond", name: "EB Garamond", family: '"EB Garamond"' },
  { key: "newsreader", name: "Newsreader", family: '"Newsreader"' },
  { key: "crimson", name: "Crimson Text", family: '"Crimson Text"' },
  { key: "fraunces", name: "Fraunces", family: "var(--font-fraunces)" },
  { key: "zilla", name: "Zilla Slab", family: "var(--font-zilla)" },
  { key: "bitter", name: "Bitter", family: '"Bitter"' },
  { key: "inter", name: "Inter", family: "var(--font-inter)" },
  { key: "ibmplexsans", name: "IBM Plex Sans", family: '"IBM Plex Sans"' },
  { key: "worksans", name: "Work Sans", family: '"Work Sans"' },
  { key: "dmsans", name: "DM Sans", family: '"DM Sans"' },
  { key: "manrope", name: "Manrope", family: "var(--font-manrope)" },
  { key: "grotesk", name: "Space Grotesk", family: "var(--font-grotesk)" },
  { key: "hyperlegible", name: "Atkinson Hyperlegible", family: "var(--font-hyperlegible)" },
  { key: "nunito", name: "Nunito", family: '"Nunito"' },
  { key: "playfair", name: "Playfair Display", family: '"Playfair Display"' },
  { key: "jetbrains", name: "JetBrains Mono", family: "var(--font-jetbrains)" },
  { key: "ibmplexmono", name: "IBM Plex Mono", family: '"IBM Plex Mono"' },
];

export const PALETTE_NAMES: Record<string, string> = Object.fromEntries(
  PALETTE_PRESETS.map((p) => [p.key, p.name]),
);
export const FONT_NAMES: Record<string, string> = Object.fromEntries(
  FONT_PRESETS.map((f) => [f.key, f.name]),
);
