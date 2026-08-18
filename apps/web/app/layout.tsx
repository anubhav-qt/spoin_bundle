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
import { AuthProvider } from "@/components/AuthProvider";

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
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={FONT_VARIABLES}>
      {/* suppressHydrationWarning: expected — the inline scripts below set
          data-palette/data-font on the server-rendered node before React
          hydrates, so client and server markup legitimately differ on those
          two attributes. This is the standard fix for that pattern. */}
      <body suppressHydrationWarning>
        <Script id="apply-palette" strategy="beforeInteractive">
          {APPLY_PALETTE_SCRIPT}
        </Script>
        <Script id="apply-font" strategy="beforeInteractive">
          {APPLY_FONT_SCRIPT}
        </Script>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
