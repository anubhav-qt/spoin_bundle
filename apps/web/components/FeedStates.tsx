"use client";

/**
 * End-of-feed and degraded states.
 *
 * ADR-0006 is explicit that these are **a real design surface, not error
 * states**: "Short pages on a swipe feed read as 'I reached the end'." And on
 * free tier a fill can take hours rather than seconds — the cron runs every ~15
 * minutes and the daily quota may already be spent — so the copy must never
 * imply imminent arrival, and there is never an indefinite spinner.
 */

export function DegradedNotice() {
  return (
    <div className="notice" data-tone="degraded">
      <p className="notice-kicker">Short page</p>
      <p className="notice-title">Fewer cards than usual</p>
      <p className="notice-body">
        We keep the mix of difficulty levels honest rather than padding the page with
        whatever happens to be available. More cards are being written for this level.
      </p>
    </div>
  );
}

export function RecyclingNotice() {
  return (
    <div className="notice">
      <p className="notice-kicker">Second pass</p>
      <p className="notice-title">You&rsquo;ve seen everything at this level</p>
      <p className="notice-body">
        Rather than stopping, these are coming round again in a different order. Nothing
        new is being hidden from you &mdash; more cards are still being written, and they
        will appear here as they land.
      </p>
    </div>
  );
}

export function EndOfFeed() {
  return (
    <div className="notice">
      <p className="notice-kicker">Caught up</p>
      <p className="notice-title">That&rsquo;s everything for now</p>
      <p className="notice-body">
        New cards are generated in batches, so this can take a few hours rather than a few
        seconds. Nothing is loading in the background — come back later.
      </p>
    </div>
  );
}

export function EmptyFeed() {
  return (
    <div className="notice">
      <p className="notice-kicker">Nothing here yet</p>
      <p className="notice-title">No topics subscribed</p>
      <p className="notice-body">
        Pick a topic to start a feed. If you are running this locally, the seed job creates a
        demo account with two topics already subscribed.
      </p>
    </div>
  );
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="notice">
      <p className="notice-kicker">Could not load</p>
      <p className="notice-title">The feed didn&rsquo;t come back</p>
      <p className="notice-body">{message}</p>
      <button className="got-it" onClick={onRetry} type="button" style={{ marginTop: 18 }}>
        Try again
      </button>
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="skeleton" aria-hidden="true">
      <div className="skeleton-line" style={{ width: "28%", height: 22 }} />
      <div className="skeleton-line" style={{ width: "82%", height: 20, marginTop: 18 }} />
      <div className="skeleton-line" style={{ width: "55%", height: 20 }} />
      <div className="skeleton-line" style={{ width: "94%", marginTop: 16 }} />
      <div className="skeleton-line" style={{ width: "70%" }} />
    </div>
  );
}
