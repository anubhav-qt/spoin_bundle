"use client";

/**
 * "All my notes" (docs/tasks/0004-notes-in-one-place.md, part 2) — every
 * `CardNote` this user has written, newest edit first, rendered as full
 * `Card`s with the note editor expanded by default so it reads as a study
 * view rather than a bare list of card titles.
 *
 * Seen-state here is presentation-only: this view isn't part of the feed's
 * progression path, so "Got it" toggles just flip the icon locally rather
 * than round-tripping through engagement/progress like the feed does.
 */

import { useCallback, useEffect, useState } from "react";
import { api, type NoteWithCard } from "@/lib/api";
import { useRefreshEffect } from "@/lib/refresh";
import { Card } from "./Card";

export function NotesView() {
  const [notes, setNotes] = useState<NoteWithCard[] | null>(null);
  const [seenIds, setSeenIds] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    setNotes(null);
    api
      .listNotes()
      .then(setNotes)
      .catch(() => setNotes([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Manual refresh, or an invalidation from elsewhere (a note saved/deleted
  // from a card in the feed, say) — re-fetches without needing a remount.
  useRefreshEffect("notes", load);

  const onNoteChange = (cardId: string, body: string | null) => {
    if (body !== null) return;
    // A note cleared to empty deletes it — drop the row rather than leaving
    // a card with no note content sitting in a "notes" view.
    setNotes((current) => current?.filter((row) => row.card.id !== cardId) ?? current);
  };

  return (
    <div className="notes-view">
      <div className="notes-view-header">
        <h1 className="notes-view-title">Your notes</h1>
        <p className="notes-view-subtitle">Private. Only you can see these.</p>
      </div>

      {notes === null ? <p className="notes-view-empty">Loading…</p> : null}

      {notes !== null && notes.length === 0 ? (
        <p className="notes-view-empty">
          No notes yet — tap the note icon on any card to jot one down.
        </p>
      ) : null}

      <div className="notes-view-list">
        {notes?.map((row) => (
          <Card
            key={row.card.id}
            card={row.card}
            topicName={row.topic_name}
            accentHue={undefined}
            seen={seenIds.has(row.card.id)}
            onSeen={(cardId) => setSeenIds((current) => new Set(current).add(cardId))}
            onUnseen={(cardId) =>
              setSeenIds((current) => {
                const next = new Set(current);
                next.delete(cardId);
                return next;
              })
            }
            isHero={false}
            initialNoteOpen
            onNoteChange={onNoteChange}
          />
        ))}
      </div>
    </div>
  );
}
