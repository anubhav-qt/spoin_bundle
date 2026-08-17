# Task 0004: A single view of all your notes

- **Owner:** unassigned
- **Timebox:** ~1 day, once note-taking itself exists (see below -- this may be two tasks)
- **Depends on:** nothing structurally, but is blocked in practice by the gap described
  here.
- **Background reading:** [ADR-0015](../adr/0015-topic-progress-and-discovery.md)'s
  engagement-stats section; `apps/api/src/spoin/domain/models/engagement.py`'s
  `CardNote` model.

## The problem

The Note button on a card (`Card.tsx`) fires a bare `EngagementEvent` of kind `note` --
that's it. `CardNote` (`user_id`, `card_id`, `body: Text`, per-user and private) is
modeled in the schema but **has zero writers anywhere in the codebase**. No UI captures
note text, no endpoint saves it. The count shown in the new topic-stats modal
(`GET /topics/{id}/stats`'s `notes` field) is real -- it's counting `note` events -- but
there is no note *content* behind that count anywhere to show.

The ask: "I'd want all my saved notes shown later in one place." That view can't exist
until note-taking actually stores something.

## What to build

Two pieces, probably worth splitting:

1. **Note-taking itself.** The Note button needs to open some kind of text input (inline,
   a small popover, whatever fits the card's interaction model) and persist it via a new
   endpoint that writes to `CardNote` -- upsert semantics, since a user should be able to
   edit a note they already wrote on a card, not just append.
2. **The "all my notes" view.** Once (1) exists: a new route/surface listing every
   `CardNote` a user has written, presumably with enough card context (title, topic) to be
   useful without opening each card individually. Where this lives in the nav (a page? a
   panel off the "Notes" stub already added to the left sidebar?) is an open design
   question, not decided here.

## Deliverables

- A note-taking endpoint + UI.
- The "all my notes" view.
- If the two land separately, this doc should be split rather than left half-checked-off.
