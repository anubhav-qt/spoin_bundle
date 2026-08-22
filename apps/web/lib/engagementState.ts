"use client";

/**
 * Cross-instance liked/bookmarked state, keyed by card id.
 *
 * The same card can be mounted as more than one `Card` component at once --
 * Feed, Liked, Saved, Notes and the Share page all stay mounted
 * simultaneously (AppShell's `hidden`-not-unmounted views; the Feed can even
 * render the *same* card_id twice under recycling, ADR-0050). `liked`/
 * `bookmarked` used to live purely in each instance's own `useState`, seeded
 * once from `initialLiked`/`initialBookmarked` and never touched again --
 * unliking a card from LikedView had no way to reach the *other* `Card`
 * instance rendering the same card_id in the Feed, so a card liked in the
 * Feed and then unliked from Liked kept showing as liked on scrolling back.
 * Stale local state, not a server disagreement.
 *
 * This is a plain in-memory cache, not the source of truth (the server is,
 * per ADR-0011) -- it exists purely so every mounted `Card` instance for the
 * same card agrees with every other one within a session. Cleared on reload
 * like everything else client-side; nothing here needs to survive that.
 */

type Listener = (value: boolean) => void;

function createStore() {
  const values = new Map<string, boolean>();
  const listeners = new Map<string, Set<Listener>>();

  return {
    get(cardId: string): boolean | undefined {
      return values.get(cardId);
    },

    /** Writes through and notifies every OTHER currently-mounted `Card` for
     *  this card id. The instance making the change already has this value
     *  in its own state -- callers still update their own `useState`
     *  directly rather than relying on their own subscription to round-trip
     *  the value back to themselves. */
    set(cardId: string, value: boolean): void {
      values.set(cardId, value);
      for (const fn of listeners.get(cardId) ?? []) fn(value);
    },

    subscribe(cardId: string, fn: Listener): () => void {
      let set = listeners.get(cardId);
      if (!set) {
        set = new Set();
        listeners.set(cardId, set);
      }
      set.add(fn);
      return () => {
        set.delete(fn);
        if (set.size === 0) listeners.delete(cardId);
      };
    },
  };
}

export const likedStore = createStore();
export const bookmarkedStore = createStore();
