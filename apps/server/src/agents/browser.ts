import type { CardOut } from "@spoin/shared";
import { type Browser as Chromium, chromium } from "playwright-core";
import { log } from "../log.ts";

/*
 * Headless Chromium in the worker (task 0045): `fetch` reads a page whose HTML has no real text
 * once its scripts have run, and designer_toad sees its art on the real card, rendered by the web
 * app at a phone's width, as a reader would. One browser per process, started when first needed.
 */

/** A phone's screen: an iPhone 15's width, at twice its points, enough to judge art by. */
const PHONE = { width: 393, height: 852, scale: 2 };
const PAGE_TIMEOUT_MS = 30_000;

/** A card as the web app's render page takes it: as the feed sends it, with its topic's name. */
export interface RenderedCard {
  card: CardOut;
  topicName: string;
}

export interface Browser {
  /** A page's title and visible text once its scripts have run. */
  pageText(url: string, signal: AbortSignal): Promise<{ title: string; text: string }>;
  /** The card on a phone, as a PNG. */
  renderCard(card: RenderedCard, signal: AbortSignal): Promise<Buffer>;
  /** A page or a picture as a laptop's screen shows it, as a JPEG. */
  screenshot(url: string, signal: AbortSignal): Promise<Buffer>;
}

/** A laptop's screen: wide enough for a page's main picture to show above the fold. */
const SCREEN = { width: 1280, height: 900 };

/** The browser, given where the web app is served; null where there is none, as in tests. */
export function chromiumBrowser(webUrl: string | null): Browser {
  let launched: Promise<Chromium> | null = null;
  const browser = () => {
    if (!launched) {
      // Playwright closes the browser on the stop signal by default, which failed a render the
      // worker's drain would have let finish (the first live run's designer_toad).
      launched = chromium.launch({
        headless: true,
        handleSIGTERM: false,
        handleSIGINT: false,
        handleSIGHUP: false,
      });
      launched.then(
        (started) => {
          started.on("disconnected", () => {
            launched = null;
          });
        },
        () => {
          launched = null;
        },
      );
    }
    return launched;
  };

  return {
    async pageText(url, signal) {
      const context = await (await browser()).newContext();
      const stop = () => void context.close();
      signal.addEventListener("abort", stop, { once: true });
      try {
        const page = await context.newPage();
        await page
          .goto(url, { waitUntil: "networkidle", timeout: PAGE_TIMEOUT_MS })
          .catch((error: unknown) => {
            // A page that never goes quiet has usually drawn its text by the timeout anyway.
            log.warn({ err: error, url }, "the page never went quiet");
          });
        const title = await page.title();
        // Run in the page, where the DOM is; this file's types are Node's.
        const text = await page.evaluate(() => {
          const shown = globalThis as unknown as { document?: { body?: { innerText: string } } };
          return shown.document?.body?.innerText ?? "";
        });
        return { title, text };
      } finally {
        signal.removeEventListener("abort", stop);
        await context.close();
      }
    },

    async renderCard(shown, signal) {
      if (!webUrl) throw new Error("No web app is set up to render cards on (WEB_URL).");
      const context = await (await browser()).newContext({
        viewport: { width: PHONE.width, height: PHONE.height },
        deviceScaleFactor: PHONE.scale,
        isMobile: true,
        hasTouch: true,
      });
      const stop = () => void context.close();
      signal.addEventListener("abort", stop, { once: true });
      try {
        const page = await context.newPage();
        await page.goto(`${webUrl}/render/card`, { waitUntil: "networkidle", timeout: PAGE_TIMEOUT_MS * 4 });
        await page.waitForFunction(() => "spoinRenderCard" in globalThis, undefined, {
          timeout: PAGE_TIMEOUT_MS,
        });
        await page.evaluate((given) => {
          (globalThis as unknown as { spoinRenderCard: (shown: unknown) => void }).spoinRenderCard(given);
        }, shown);
        const rendered = page.locator(`[data-rendered-card="${shown.card.id}"]`);
        await rendered.waitFor({ timeout: PAGE_TIMEOUT_MS });
        // Fonts and the art's layout settle a beat after React commits.
        await page.waitForTimeout(500);
        return await rendered.screenshot({ type: "png" });
      } finally {
        signal.removeEventListener("abort", stop);
        await context.close();
      }
    },

    async screenshot(url, signal) {
      const context = await (await browser()).newContext({ viewport: SCREEN });
      const stop = () => void context.close();
      signal.addEventListener("abort", stop, { once: true });
      try {
        const page = await context.newPage();
        await page.goto(url, { waitUntil: "load", timeout: PAGE_TIMEOUT_MS }).catch((error: unknown) => {
          // A page still loading ads or trackers has usually drawn its pictures by the timeout.
          log.warn({ err: error, url }, "the page never finished loading");
        });
        // Pictures that load late, after the page says it has loaded.
        await page.waitForTimeout(1500);
        return await page.screenshot({ type: "jpeg", quality: 70 });
      } finally {
        signal.removeEventListener("abort", stop);
        await context.close();
      }
    },
  };
}
