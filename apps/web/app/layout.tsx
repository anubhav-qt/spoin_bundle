import type { Metadata, Viewport } from "next";
import Script from "next/script";
import "./globals.css";

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

/**
 * System stacks only — no next/font, nothing to self-host or silently fall
 * back on. Two roles, not one face doing everything (see ADR-0012): a plain
 * sans for content, and monospace reserved for system chrome — topic labels,
 * station headers, status metadata. The split itself carries meaning: mono
 * reads as *the system talking to you*, proportional sans as the content.
 */
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
    <html lang="en">
      {/* suppressHydrationWarning: expected — the inline script below sets
          data-palette on the server-rendered node before React hydrates,
          so client and server markup legitimately differ on this one
          attribute. This is the standard fix for that pattern. */}
      <body suppressHydrationWarning>
        <Script id="apply-palette" strategy="beforeInteractive">
          {APPLY_PALETTE_SCRIPT}
        </Script>
        {children}
      </body>
    </html>
  );
}
