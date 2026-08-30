"use client";

/**
 * "Revisit" — the user's shelf of saved (bookmarked) cards. A config over the
 * shared `CollectionView` (ADR-0046, task 0034).
 *
 * F6 / ADR-0072 dropped Revisit's bespoke 2-column tile grid + card overlay:
 * there was no product reason for it to look different from Liked / Notes. It
 * is now the same vertical reading list, and this file is now the same shape
 * as `LikedView`. The wire format is untouched — `saved` view key,
 * `card_bookmark` table, `api.saved*` all unchanged; the rename was copy only.
 *
 * Performance contract (same as the feed): retrieval + presentation only
 * (`GET /cards/saved`).
 */

import { api, type SavedCard, type Topic } from "@/lib/api";
import { engagement } from "@/lib/engagement";
import { bookmarkedStore } from "@/lib/engagementState";
import { CollectionView, type CollectionConfig } from "./CollectionView";
import { BookmarkIcon } from "./icons";

const config: CollectionConfig<SavedCard> = {
  scope: "saved",
  eyebrow: "REVISIT",
  title: "Keep it here. Come back later.",
  searchPlaceholder: "Search saved cards…",
  searchAriaLabel: "Search saved cards",
  countNoun: ["SAVED CARD", "SAVED CARDS"],
  errorHead: "COULDN’T LOAD YOUR SHELF",
  emptyGlyph: "\u{1F516}",
  emptyHead: "NOTHING SAVED YET",
  emptyBody: (
    <>
      Save a card when you want to come back to it.
      <br />
      It&apos;ll live here.
    </>
  ),
  footerIcon: <BookmarkIcon filled />,
  footerVerb: "saved",
  itemNoun: ["card", "cards"],
  filteredEmptyNoun: "saved cards",

  fetch: (topicId, sort) => api.savedCards(topicId, sort),
  card: (row) => row.card,
  topicName: (row) => row.topic_name,

  cardProps: (_row, { removeWithUndo }) => ({
    initialBookmarked: true,
    onUnbookmarked: (cardId) =>
      removeWithUndo(cardId, {
        label: "Removed from Revisit",
        // Write through so a Card mounted elsewhere for this card_id (the
        // feed) also flips back to bookmarked — see lib/engagementState.ts.
        // Fresh `card_bookmark` row server-side (created_at resets).
        redo: () => {
          bookmarkedStore.set(cardId, true);
          engagement.record(cardId, "bookmark");
        },
      }),
  }),
};

interface Props {
  active?: boolean;
  topics: Topic[];
  onNavigateHome: () => void;
}

export function SavedView({ topics, onNavigateHome, active = true }: Props) {
  return (
    <CollectionView
      config={config}
      topics={topics}
      onNavigateHome={onNavigateHome}
      active={active}
    />
  );
}
