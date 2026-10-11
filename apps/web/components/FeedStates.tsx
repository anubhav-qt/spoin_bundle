"use client";

/**
 * End-of-feed and degraded states.
 *
 * ADR-0006 is explicit that these are **a real design surface, not error
 * states**: "Short pages on a swipe feed read as 'I reached the end'." Cards are
 * written once, a whole topic before its first card goes live (ADR-0106), so no
 * copy may promise more cards, and there is never an indefinite spinner.
 */

export function DegradedNotice() {
  return (
    <div className="notice" data-tone="degraded">
      <p className="notice-kicker">Short page</p>
      <p className="notice-title">Fewer cards than usual</p>
      <p className="notice-body">
        We keep the mix of difficulty levels honest rather than padding the page with
        whatever happens to be available.
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
        Rather than stopping, these are coming round again in a different order. Every
        topic is written in full before it goes live, so nothing new is on the way: take
        the quiz to move on, or pick up another topic.
      </p>
    </div>
  );
}

/** The feed's topics have no cards at all: each is still being written. */
export function EndOfFeed() {
  return (
    <div className="notice">
      <p className="notice-kicker">Still being written</p>
      <p className="notice-title">Your topics have no cards yet</p>
      <p className="notice-body">
        A new topic is written in full before its first card appears, which can take a
        while. Nothing is loading in the background; come back later, or follow a topic
        that&rsquo;s ready.
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
        Pick a topic to start a feed.
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
