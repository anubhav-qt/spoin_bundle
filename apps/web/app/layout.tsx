import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { Atkinson_Hyperlegible, IBM_Plex_Sans, Inter, Literata, Space_Grotesk } from "next/font/google";
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
 * ADR-0023's five faces, self-hosted via next/font/google (ADR-0037) — no
 * runtime CDN request, and a browser only fetches the @font-face a reader's
 * `data-font` selection actually resolves to (see globals.css), so declaring
 * all five here doesn't mean all five download. Two roles otherwise (see
 * ADR-0012): these variables feed `--font-sans` only. Monospace stays a
 * fixed system stack, locked out of the choice — ADR-0021's ASCII scenes
 * depend on it staying fixed-width.
 */
const literata = Literata({ subsets: ["latin"], variable: "--font-literata", display: "swap" });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const grotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-grotesk", display: "swap" });
const plex = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex",
  display: "swap",
});
const hyperlegible = Atkinson_Hyperlegible({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-hyperlegible",
  display: "swap",
});
const FONT_VARIABLES = `${literata.variable} ${inter.variable} ${grotesk.variable} ${plex.variable} ${hyperlegible.variable}`;

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
