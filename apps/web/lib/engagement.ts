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

const FLUSH_INTERVAL_MS = 5000;

/** Sent immediately rather than buffered — progression depends on them. */
const URGENT: ReadonlySet<EngagementKind> = new Set([
  "expand",
  "explicit_complete",
  "dwell_complete",
]);

class EngagementBuffer {
  private queue: EngagementEvent[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;

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
      id: crypto.randomUUID(),
      card_id: cardId,
      kind,
      ...(dwellMs === undefined ? {} : { dwell_ms: dwellMs }),
      client_occurred_at: new Date().toISOString(),
    });

    if (URGENT.has(kind)) void this.flush();
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
