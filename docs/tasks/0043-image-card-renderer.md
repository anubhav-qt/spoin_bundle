# Task 0043: Card Image Renderer for UI & Web Client

> **Status: Ready to build** (2026-09-06) — Depends on Task 0040 (Phases 1–4, backend assignment & loop guards landed and verified).
> Follow-up to [ADR-0095](../adr/0095-open-licensed-image-catalog.md) and [ADR-0102](../adr/0102-image-card-assignment-and-planner-ceiling.md).

## Problem

The generation pipeline now assigns catalog images to `image` card drafts and persists `visual_id`, `visual_kind = "image"`, and `visual_slots` containing:
- `title`
- `attribution`
- `display_url`
- `source_page`
- `licence`

Currently, `apps/web/components/Card.tsx` only renders ASCII art blocks (`visual_slots?.art` / `visual_id`). It has no renderer for photograph cards.

## Requirements

1. **Wire Contract:**
   - Expose `visual_kind: VisualKind | None = None` on `CardOut`, `LikedCardOut`, and `SavedCardOut` in `apps/api/src/spoin/api/schemas.py`.
   - Update `Card` interface in `apps/web/lib/api.ts` with `visual_kind: "ascii" | "image" | null`.

2. **UI Card Component (`apps/web/components/Card.tsx`):**
   - Render a dedicated image display when `card.visual_kind === "image"` and `card.visual_slots` is present.
   - Display the image via `display_url` (with fallback handling if image fails to load).
   - Display mandatory attribution and license badge:
     - Attribution text
     - License tag (e.g. `CC BY-SA 4.0`, `Public Domain`)
     - Clickable link to `source_page` opening in a new tab with `rel="noopener noreferrer"`.
   - Card width responsive layout:
     - Constrain image aspect ratio and width to card bounds.
     - Clean typography matching Spoin theme palette and font settings.
   - Handle collapsed and expanded card states.

3. **No Business Logic in Frontend:**
   - `apps/web` renders what the API sends. It does not look up images from `the_spoin_universe` directly.
   - Survives dangling or missing `visual_id` gracefully.

4. **Visual Review in Live Feed:**
   - Audit real image cards in the browser against Astronomy cards.
   - Measure empirical assignment relevance.
