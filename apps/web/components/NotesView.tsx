"use client";

/**
 * "All my notes" (docs/tasks/0004-notes-in-one-place.md, part 2) — every
 * `CardNote` this user has written, rendered as full `Card`s with the note
 * editor open. A config over the shared `CollectionView` (ADR-0046, task
 * 0034).
 *
 * Unlike Liked / Revisit, Notes fetches once (`GET /notes`, no params) and
 * filters + sorts client-side — its "recent"/"oldest" sort is by
 * `note.updated_at`, and search also matches the note body. Clearing a note
 * to empty deletes it, with a 5-second undo that re-`PUT`s the exact text.
 *
 * Seen-state is presentation-only here — this view isn't on the feed's
 * progression path.
 */

import { api, type NoteWithCard, type Topic } from "@/lib/api";
import { invalidate } from "@/lib/refresh";
import { CollectionView, type CollectionConfig, type CollectionSortKey } from "./CollectionView";
import { NoteIcon } from "./icons";

const DIFFICULTY_RANK: Record<string, number> = {
  beginner: 1,
  intermediate: 2,
  advanced: 3,
};

function sortNotes(a: NoteWithCard, b: NoteWithCard, key: CollectionSortKey): number {
  switch (key) {
    case "recent":
      return new Date(b.note.updated_at).getTime() - new Date(a.note.updated_at).getTime();
    case "oldest":
      return new Date(a.note.updated_at).getTime() - new Date(b.note.updated_at).getTime();
    case "topic":
      return a.topic_name.localeCompare(b.topic_name);
    case "difficulty":
      return (DIFFICULTY_RANK[a.card.difficulty] ?? 0) - (DIFFICULTY_RANK[b.card.difficulty] ?? 0);
    default:
      return 0;
  }
}

const config: CollectionConfig<NoteWithCard> = {
  scope: "notes",
  eyebrow: "NOTES",
  title: "Private. Only you can see these.",
  searchPlaceholder: "Search notes…",
  searchAriaLabel: "Search notes",
  countNoun: ["NOTE", "NOTES"],
  errorHead: "COULDN’T LOAD YOUR NOTES",
  emptyGlyph: "✎",
  emptyHead: "NO NOTES YET",
  emptyBody: (
    <>
      Tap the note icon on any card
      <br />
      to jot down your thoughts.
      <br />
      They&apos;ll live here.
    </>
  ),
  footerIcon: <NoteIcon />,
  footerVerb: "written",
  itemNoun: ["note", "notes"],
  filteredEmptyNoun: "notes",

  fetch: () => api.listNotes(),
  card: (row) => row.card,
  topicName: (row) => row.topic_name,

  clientFilterSort: true,
  searchExtra: (row, q) => row.note.body.toLowerCase().includes(q),
  sortRow: sortNotes,

  cardProps: (_row, { removeWithUndo, updateRow }) => ({
    initialNoteOpen: true,
    onNoteChange: (cardId, body) => {
      if (body === null) {
        // Cleared to empty — Card has already issued the DELETE. Drop the row
        // and offer an undo that re-`PUT`s the captured text.
        removeWithUndo(cardId, {
          label: "Note deleted",
          redo: async (removed) => {
            await api.saveNote(removed.card.id, removed.note.body);
            invalidate("notes");
          },
        });
      } else {
        updateRow(cardId, (r) => ({
          ...r,
          note: { ...r.note, body, updated_at: new Date().toISOString() },
        }));
      }
    },
  }),
};

interface Props {
  topics?: Topic[];
  onNavigateHome?: () => void;
  active?: boolean;
}

export function NotesView({ topics = [], onNavigateHome, active = true }: Props) {
  return (
    <CollectionView
      config={config}
      topics={topics}
      onNavigateHome={onNavigateHome}
      active={active}
    />
  );
}
