"use client";

/**
 * The user's personal shelf of liked knowledge cards — a config over the
 * shared `CollectionView` (ADR-0046, task 0034). Distinctive pieces: the
 * `liked_at` sort key is applied server-side, and removing a card unlikes it
 * with a 5-second undo that re-likes and re-inserts the captured row.
 *
 * Performance contract (same as the feed): retrieval + presentation only.
 */

import { api, type LikedCard, type Topic } from "@/lib/api";
import { engagement } from "@/lib/engagement";
import { likedStore } from "@/lib/engagementState";
import { CollectionView, type CollectionConfig } from "./CollectionView";
import { HeartIcon } from "./icons";

const config: CollectionConfig<LikedCard> = {
  scope: "liked",
  eyebrow: "LIKED",
  title: "Things worth remembering.",
  searchPlaceholder: "Search liked cards…",
  searchAriaLabel: "Search liked cards",
  countNoun: ["LIKED CARD", "LIKED CARDS"],
  errorHead: "COULDN’T LOAD YOUR SHELF",
  emptyGlyph: "♡",
  emptyHead: "NOTHING LIKED YET",
  emptyBody: (
    <>
      When something makes you stop scrolling
      <br />
      and think <em>&ldquo;I want to remember this&rdquo;</em>,
      <br />
      it&apos;ll live here.
    </>
  ),
  footerIcon: <HeartIcon filled />,
  footerVerb: "liked",
  itemNoun: ["card", "cards"],
  filteredEmptyNoun: "liked cards",

  fetch: (topicId, sort) => api.likedCards(topicId, sort),
  card: (row) => row.card,
  topicName: (row) => row.topic_name,

  cardProps: (_row, { removeWithUndo }) => ({
    initialLiked: true,
    onUnliked: (cardId) =>
      removeWithUndo(cardId, {
        label: "Removed from Liked",
        // Write through so a Card mounted elsewhere for this same card_id
        // (the feed) also flips back to liked — see lib/engagementState.ts.
        // The re-like is a fresh `card_like` row server-side (created_at
        // resets), the delete-now-undo-by-redo tradeoff (lib/undo.ts).
        redo: () => {
          likedStore.set(cardId, true);
          engagement.record(cardId, "like");
        },
      }),
  }),
};

interface Props {
  active?: boolean;
  topics: Topic[];
  onNavigateHome: () => void;
}

export function LikedView({ topics, onNavigateHome, active = true }: Props) {
  return (
    <CollectionView
      config={config}
      topics={topics}
      onNavigateHome={onNavigateHome}
      active={active}
    />
  );
}
