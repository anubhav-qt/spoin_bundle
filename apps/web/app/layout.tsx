import type { Metadata, Viewport } from "next";
import Script from "next/script";
import {
  Atkinson_Hyperlegible,
  Comfortaa,
  Courier_Prime,
  Fraunces,
  Inter,
  JetBrains_Mono,
  Literata,
  Manrope,
  Space_Grotesk,
  Zilla_Slab,
} from "next/font/google";
import "./globals.css";
import "katex/dist/katex.min.css";
import { AuthProvider } from "@/components/AuthProvider";
import { GenerationTrackerProvider } from "@/components/GenerationTrackerProvider";

/**
 * Applies the persisted palette before first paint. Without this, the page
 * would flash the default `notebook` palette and then jump to whatever the
 * user picked last (ADR-0013 / docs/tasks/0002) once React hydrates and
 * ThemePicker's own effect runs. `beforeInteractive` is Next's supported way
 * to run a script this early — a hand-written `<head>` isn't, under the app
 * router's metadata API.
 */
const APPLY_PALETTE_SCRIPT = `
(function () {
  try {
    var palette = localStorage.getItem("spoin-palette");
    if (palette) document.body.setAttribute("data-palette", palette);
    if (palette === "custom") {
      var colors = JSON.parse(localStorage.getItem("spoin-custom-colors") || "null");
      if (colors) {
        document.body.style.setProperty("--bg", colors.bg);
        document.body.style.setProperty("--fg", colors.fg);
        document.body.style.setProperty("--accent", colors.accent);
        document.body.style.setProperty("--accent-2", colors.accent2);
      }
    }
  } catch (e) {}
})();
`;

/** Same shape as APPLY_PALETTE_SCRIPT, for the font choice (ADR-0023, wired
 *  up by ADR-0037). */
const APPLY_FONT_SCRIPT = `
(function () {
  try {
    var font = localStorage.getItem("spoin-font");
    if (font) document.body.setAttribute("data-font", font);
  } catch (e) {}
})();
`;

/** Same shape again, for Settings' reduced-motion switch.
 *
 *  Only ever sets the attribute, never clears it: `prefers-reduced-motion` is
 *  still honoured on its own in globals.css, so this is a way to opt IN on a
 *  device whose OS setting says otherwise — not a way to opt out of the OS
 *  setting. Pre-hydration for the same reason as the two above: an animation
 *  that plays for one frame before React clears it is exactly the thing
 *  someone turning this on is trying to avoid. */
const APPLY_MOTION_SCRIPT = `
(function () {
  try {
    if (localStorage.getItem("spoin-reduced-motion") === "1") {
      document.body.setAttribute("data-reduced-motion", "1");
    }
  } catch (e) {}
})();
`;

/**
 * The five PRESET faces, self-hosted via next/font/google (ADR-0037) — no
 * runtime CDN request, and a browser only fetches the @font-face a reader's
 * `data-font` selection actually resolves to (see globals.css), so declaring
 * every face here doesn't mean every face downloads. Two roles otherwise (see
 * ADR-0012): these variables feed `--font-sans` only. Monospace stays a
 * fixed system stack, locked out of the choice — ADR-0021's ASCII scenes
 * depend on it staying fixed-width. (`jetbrains` below is a --font-sans
 * option that happens to be a monospace TYPEFACE, not a change to that
 * separate --font-mono variable — the two are unrelated.)
 *
 * IBM Plex Sans was dropped from the preset five: visually it read as a
 * near-duplicate of Inter at a glance, which was the actual "these all look
 * the same" complaint — swapped for JetBrains Mono, a genuinely different
 * texture (a "terminal" reading face fits this app's technical content).
 * The five extra faces below (Fraunces/Manrope/Zilla Slab/Courier
 * Prime/Comfortaa) back the custom font picker's expanded list, not the
 * five-pill row.
 */
const literata = Literata({ subsets: ["latin"], variable: "--font-literata", display: "swap" });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const grotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-grotesk", display: "swap" });
const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-jetbrains",
  display: "swap",
});
const hyperlegible = Atkinson_Hyperlegible({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-hyperlegible",
  display: "swap",
});

// -- extra faces, custom font picker only ------------------------------
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-fraunces", display: "swap" });
const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope", display: "swap" });
const zillaSlab = Zilla_Slab({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-zilla",
  display: "swap",
});
const courierPrime = Courier_Prime({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-courier",
  display: "swap",
});
const comfortaa = Comfortaa({ subsets: ["latin"], variable: "--font-comfortaa", display: "swap" });

/**
 * The 46 extra faces behind CustomFontModal's "More fonts" list (ADR-0038:
 * over 50 faces total, counting the 5 presets + 5 original extras above).
 * Loaded as one Google Fonts CSS2 stylesheet request rather than 46
 * next/font/google imports -- next/font validates the requested `weight`
 * array against each family's actually-published static cuts at build time
 * and hard-fails the whole app if one is wrong; the CSS2 API is tolerant of
 * a requested weight a family doesn't ship (it just omits it), which is the
 * right trade for a long, rarely-audited list like this one. Referenced by
 * literal family name in each `[data-font="…"]` rule in globals.css, not by
 * a `--font-*` custom property -- there's no local @font-face to point at.
 */
const EXTRA_GOOGLE_FONTS_HREF =
  "https://fonts.googleapis.com/css2?" +
  [
    "family=Merriweather:wght@400;700",
    "family=Playfair+Display:wght@400;700",
    "family=Lora:wght@400;700",
    "family=Crimson+Text:wght@400;700",
    "family=EB+Garamond:wght@400;700",
    "family=Bitter:wght@400;700",
    "family=PT+Serif:wght@400;700",
    "family=Source+Serif+4:wght@400;700",
    "family=Libre+Baskerville:wght@400;700",
    "family=Cormorant:wght@400;700",
    "family=Spectral:wght@400;700",
    "family=Noto+Serif:wght@400;700",
    "family=Vollkorn:wght@400;700",
    "family=Domine:wght@400;700",
    "family=Alegreya:wght@400;700",
    "family=Roboto:wght@400;700",
    "family=Open+Sans:wght@400;700",
    "family=Lato:wght@400;700",
    "family=Montserrat:wght@400;700",
    "family=Poppins:wght@400;700",
    "family=Nunito:wght@400;700",
    "family=Work+Sans:wght@400;700",
    "family=Rubik:wght@400;700",
    "family=Karla:wght@400;700",
    "family=Mulish:wght@400;700",
    "family=DM+Sans:wght@400;700",
    "family=Sora:wght@400;700",
    "family=Outfit:wght@400;700",
    "family=Plus+Jakarta+Sans:wght@400;700",
    "family=Public+Sans:wght@400;700",
    "family=Barlow:wght@400;700",
    "family=Urbanist:wght@400;700",
    "family=Figtree:wght@400;700",
    "family=IBM+Plex+Sans:wght@400;700",
    "family=Raleway:wght@400;700",
    "family=Roboto+Slab:wght@400;700",
    "family=Arvo:wght@400;700",
    "family=Bevan:wght@400",
    "family=Fira+Code:wght@400;700",
    "family=Source+Code+Pro:wght@400;700",
    "family=IBM+Plex+Mono:wght@400;700",
    "family=Space+Mono:wght@400;700",
    "family=Roboto+Mono:wght@400;700",
    "family=Inconsolata:wght@400;700",
    "family=Caveat:wght@400;700",
    "family=Bebas+Neue:wght@400",
  ].join("&") +
  "&display=swap";

const FONT_VARIABLES = [
  literata,
  inter,
  grotesk,
  jetbrains,
  hyperlegible,
  fraunces,
  manrope,
  zillaSlab,
  courierPrime,
  comfortaa,
]
  .map((f) => f.variable)
  .join(" ");

export const metadata: Metadata = {
  title: "Spoin",
  description: "A swipeable feed of AI-generated knowledge flash cards.",
};

export const viewport: Viewport = {
  // Matches the Notebook palette's paper color (see ADR-0012) — the shipped
  // default until the palette picker (docs/tasks/0002) exists.
  themeColor: "#EDF0EA",
  // Lets the fixed mobile topbar/bottom-nav (ADR-0063) paint into the
  // notch/home-indicator safe areas instead of leaving a themeColor-only
  // strip there; `env(safe-area-inset-*)` in globals.css's ≤680px block is
  // what actually keeps content clear of them.
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={FONT_VARIABLES}>
      {/* suppressHydrationWarning: expected — the inline scripts below set
          data-palette/data-font on the server-rendered node before React
          hydrates, so client and server markup legitimately differ on those
          two attributes. This is the standard fix for that pattern. */}
      <body suppressHydrationWarning>
        {/* The 46-face "more fonts" catalog (CustomFontModal) -- one batched
            stylesheet request rather than 46 individual next/font/google
            imports. The 10 faces above stay self-hosted per-family (the fast
            path: 5 presets + the 5 original extras); this covers only the
            expanded list a reader opts into from the "More fonts" modal.
            Next hoists <link> tags into <head> on every page regardless of
            whether that modal is ever opened, so this does cost one request
            up front -- accepted as the simplest correct thing given how
            rarely this list changes; revisit with a dynamically-injected
            <link> on modal-open only if that request becomes a real
            first-paint cost. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href={EXTRA_GOOGLE_FONTS_HREF} />
        <Script id="apply-palette" strategy="beforeInteractive">
          {APPLY_PALETTE_SCRIPT}
        </Script>
        <Script id="apply-motion" strategy="beforeInteractive">
          {APPLY_MOTION_SCRIPT}
        </Script>
        <Script id="apply-font" strategy="beforeInteractive">
          {APPLY_FONT_SCRIPT}
        </Script>
        <AuthProvider>
          <GenerationTrackerProvider>{children}</GenerationTrackerProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
