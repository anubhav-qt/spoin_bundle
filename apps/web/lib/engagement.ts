/**
 * Client-side event buffering (ADR-0011).
 *
 * One HTTP request per scroll tick would melt a free-tier API, so events are
 * buffered and flushed on a timer, on card change, and on page hide.
 *
 * Two rules encoded here:
 *
 * - **`expand` is sent promptly, not buffered.** A dropped impression is
 *   acceptable; a dropped expansion stalls the user's progression.
 * - **Dwell only accumulates while the page is visible.** A tab left open
 *   overnight is not a nine-hour engagement. The server also caps and discards
 *   implausible values, but sending them in the first place is wasteful.
 */

import { api, type EngagementEvent, type EngagementKind } from "./api";
import { invalidate } from "./refresh";

const FLUSH_INTERVAL_MS = 5000;

/** `crypto.randomUUID` only exists in a secure context (HTTPS or localhost) --
 *  on a phone hitting the dev server over plain HTTP by LAN IP it's simply
 *  undefined, which crashed every event record() call before this fell back
 *  to `crypto.getRandomValues` (present in any context) or, failing that, a
 *  `Math.random`-based id. Good enough for an idempotency key that only needs
 *  to be unique per client, not cryptographically strong. */
function generateEventId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

/** Sent immediately rather than buffered — progression depends on them. */
const URGENT: ReadonlySet<EngagementKind> = new Set([
  "expand",
  "explicit_complete",
  "dwell_complete",
  "like",
  "unlike",
  "bookmark",
  "unbookmark",
]);

class EngagementBuffer {
  private queue: EngagementEvent[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  // The most recent urgent flush's promise (ADR-0038) -- lets a caller that
  // just recorded a seen-triggering event (dwell_complete/explicit_complete)
  // wait for that write to actually land server-side before reading back a
  // derived aggregate like topic coverage, without weakening ADR-0011's
  // "don't read your own writes" rule for anything ranking/serving-critical.
  // `flush()` drains `this.queue` synchronously before its first `await`, so
  // by the time `record()` returns, this already points at the in-flight
  // request for the event just pushed.
  private flushing: Promise<void> = Promise.resolve();

  start(): void {
    if (this.timer !== null) return;

    this.timer = setInterval(() => void this.flush(), FLUSH_INTERVAL_MS);
    document.addEventListener("visibilitychange", this.onVisibilityChange);
  }

  stop(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    document.removeEventListener("visibilitychange", this.onVisibilityChange);
    void this.flush();
  }

  record(cardId: string, kind: EngagementKind, dwellMs?: number): void {
    this.queue.push({
      id: generateEventId(),
      card_id: cardId,
      kind,
      ...(dwellMs === undefined ? {} : { dwell_ms: dwellMs }),
      client_occurred_at: new Date().toISOString(),
    });

    if (URGENT.has(kind)) this.flushing = this.flush();

    // Stales the collection view a like/bookmark just changed the membership
    // of, so it re-fetches next time it's looked at instead of showing a
    // list that's quietly out of date with what the feed just did.
    if (kind === "like" || kind === "unlike") invalidate("liked");
    if (kind === "bookmark" || kind === "unbookmark") invalidate("saved");
  }

  /** Resolves once the most recent urgent flush (if any) has settled. */
  whenIdle(): Promise<void> {
    return this.flushing;
  }

  async flush(): Promise<void> {
    if (this.queue.length === 0) return;

    const batch = this.queue;
    this.queue = [];

    try {
      await api.sendEvents(batch);
    } catch {
      // Put them back and let the next tick retry. Every event carries a stable
      // client id, so a retry that partially succeeded earlier deduplicates
      // server-side rather than double-counting.
      this.queue = [...batch, ...this.queue];
    }
  }

  private onVisibilityChange = (): void => {
    if (document.visibilityState === "hidden") void this.flush();
  };
}

export const engagement = new EngagementBuffer();

/**
 * Accumulates dwell time, pausing whenever the page is hidden.
 */
export class DwellTimer {
  private accumulated = 0;
  private startedAt: number | null = null;

  start(): void {
    if (this.startedAt === null) this.startedAt = performance.now();
  }

  pause(): void {
    if (this.startedAt === null) return;
    this.accumulated += performance.now() - this.startedAt;
    this.startedAt = null;
  }

  get elapsedMs(): number {
    const running = this.startedAt === null ? 0 : performance.now() - this.startedAt;
    return Math.round(this.accumulated + running);
  }

  reset(): void {
    this.accumulated = 0;
    this.startedAt = null;
  }
}
