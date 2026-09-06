# ADR-0102: Image Card Assignment, Visual Kind Schema, and the Planner Ceiling Loop Guard

- **Status:** Accepted
- **Date:** 2026-09-06
- **Deciders:** project owner, implementing session
- **Continues:** [ADR-0095](0095-open-licensed-image-catalog.md) (open-licensed image catalog)
- **Amends:** [ADR-0059](0059-card-planning-pass-and-prompt-versioning.md) (card type quotas), [ADR-0066](0066-redraw-over-budget-ascii-art.md) (regeneration loops)

## Context

Astronomy is the first authored curriculum in Spoin: 10 subtopics, 30 subtopic-tiers, 568 cards, of which 76 are planned as `image` cards. ADR-0095 delivered Phase 1 of the image catalog with exactly 76 open-licensed, human-verified images for Astronomy in `the_spoin_universe`.

However, the product lacked an image assignment path. Specifically:
1. **Predicate collision:** `_card_matches_type` in `pipeline/state.py` evaluated `IMAGE` and `PROSE` with identical predicates (`return not tags and draft.visual_id is None`). As a result, 155 prose cards filled the 76-card image quota unguided.
2. **Missing visual kind:** `Card.visual_id` stored ASCII scene labels as arbitrary strings. Storing an image asset's UUID in `visual_id` would force renderers to inspect string formats (e.g. UUID regex) to deduce whether a card needs ASCII art or an image tag.
3. **Loop guard risk:** If a card planned as `image` fails assignment (e.g. catalog exhausted or below similarity floor), rejecting it triggers regeneration. If the planner continues to demand image cards when none are available, the generation pipeline enters an unbounded regeneration loop (ADR-0066).

## Decisions

### 1. `VisualKind` and `card.visual_kind` Schema

We introduce `VisualKind(StrEnum)` with values `ascii` and `image` in `spoin.domain.enums`.
A corresponding `visual_kind` column and database constraint are added to `Card`:

```python
CheckConstraint(
    "(visual_id IS NULL) = (visual_kind IS NULL)",
    name="visual_kind_accompanies_visual_id",
)
```

**Why it is not inferred:** An image `visual_id` is a UUID while an ASCII scene ID is not. While technically recoverable via string inspection, doing so would make frontend and client rendering depend on implicit format conventions. Storing `visual_kind` explicitly maintains clean domain boundaries.

Existing cards with non-null `visual_id` are backfilled to `ascii` before applying the constraint.

### 2. Server-Side Post-Drafting Assignment (`spoin.generation.images`)

Image cards are drafted **without telling the LLM that images exist** (ADR-0095). The generator writes a conceptually grounded card draft, and assignment runs server-side immediately after drafting and before persistence.

- **Query:** `f"{draft.canonical_title}. {draft.summary} {draft.body}"` embedded with `aembed_query` and matched against image descriptions via cosine distance.
- **Exclusions:** `exclude_image_ids` queries `spoin_db_2` for all active and draft cards in the topic whose `visual_id` is a UUID. Newly assigned images within the batch are added to `exclude_image_ids` to prevent intra-batch collisions without locks.
- **Visual slots:** On assignment, `visual_id` is set to the image UUID, `visual_kind` is set to `VisualKind.IMAGE`, and `visual_slots` is populated with `{"title", "attribution", "display_url", "source_page", "licence"}`. The renderer never needs to query `the_spoin_universe` directly.
- **Fault tolerance:** `assign_images` never raises. Unreachable corpus database or SQL errors report `unavailable` and leave drafts unassigned.

### 3. Planner Ceiling Loop Guard

*The planner is trusted for taste, not constraints* (CLAUDE.md).

Before planning cards for a subtopic-tier, `nodes.py` queries `the_spoin_universe` for the actual count of unassigned catalog images matching the topic's categories (`count_available_images`).

`tier_quotas["image"]` is capped at `min(requested_quota, available)`. Any shortfall is immediately shifted to `prose`:

```python
available = await count_available_images(universe_session_scope, categories=categories, exclude_image_ids=used)
requested = tier_quotas.get("image", 0)
capped = min(requested, available)
if capped < requested:
    tier_quotas["image"] = capped
    tier_quotas["prose"] = tier_quotas.get("prose", 0) + (requested - capped)
```

This guarantees `sum(tier_quotas.values()) == target_cards` while ensuring the planner never briefs more image cards than the catalog can fulfill.

### 4. Tightening `_card_matches_type`

Only after the planner ceiling and assignment path are in place is `_card_matches_type` updated:

```python
if card_type == CardType.ASCII.value:
    return draft.visual_kind is VisualKind.ASCII
if card_type == CardType.IMAGE.value:
    return not tags and draft.visual_kind is VisualKind.IMAGE
if card_type == CardType.PROSE.value:
    return not tags and draft.visual_id is None
```

- `ASCII` now requires `draft.visual_kind is VisualKind.ASCII`, preventing image cards from filling ASCII quotas.
- `IMAGE` requires `draft.visual_kind is VisualKind.IMAGE`, ensuring only assigned images satisfy the quota.
- `PROSE` excludes both ASCII and IMAGE cards.

### 5. Similarity Floor Calibration

`image_similarity_floor: float = 0.0` is added to `Settings`. Run 1 runs with floor 0.0, recording all cosine similarity scores in `ImageAssignmentReport.scores` so an empirical threshold can be set from observed data rather than guesswork.

## Consequences

- Astronomy can now draft and assign its 76 verified open-licensed images without prose cards masquerading as image cards.
- Topics with zero images in the catalog gracefully cap image quota at 0, shifting all cards to prose without failing or looping.
- Renderers have explicit `visual_kind` and self-contained `visual_slots` containing title, attribution, and license without cross-database lookups.
