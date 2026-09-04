---
title: Card Anatomy, Schema Fields, and System Invariants
kind: spoin_canon
source: Spoin docs/architecture/content-model.md
topic_tags:
  - spoin canon
  - card anatomy
  - content model
  - schema invariants
---

## The Card as the Atomic Learning Unit

In Spoin, learning content is delivered through discrete, vertically swipeable cards. A card is an atomic, self-contained explanation of a single technical concept, designed to be read in a few seconds. Cards are generated once by the background pipeline and shared across all users globally; there is no runtime per-user generation, and the feed serving path never executes LLM inference.

A card is defined by the following core schema attributes:
- `id`: UUID primary key.
- `family_id`: UUID grouping all version revisions of the same conceptual card.
- `version`: Monotonically increasing integer tracking card iterations.
- `status`: Lifecycle state (`draft`, `active`, `rejected`, `superseded`).
- `topic_id`: Foreign key to the canonical topic.
- `subtopic_id`: Foreign key to the curriculum slot.
- `difficulty`: Categorical tier (`beginner`, `intermediate`, `advanced`).
- `title`: Display title shown on the card face in the feed; playful some of the time.
- `canonical_title`: Literal, descriptive title read by machine systems, search, and quizzes.
- `summary`: A standalone, purpose-written hook preview for the collapsed card state.
- `body`: Full Markdown text that scrolls inside the expanded card view.
- `archetype`: Locally derived tags classifying structural shapes present in `body`.
- `is_hero`: Boolean designating the single foundational visual anchor card per subtopic tier.
- `visual_id`: Identifier for an attached ASCII art gag scene.
- `visual_slots`: JSON payload holding scene parameters (`{"art": ..., "alt": ...}`).
- `content_embedding`: 384-dimensional dense vector for semantic deduplication.

## Field Provenance and Generation Boundaries

Every card field has a strict, non-negotiable origin boundary:

| Field | Source of Truth | Origin Rule |
|---|---|---|
| `title`, `canonical_title`, `summary`, `body` | **Generator Model** | Emitted as structured outputs during card drafting. |
| `visual_id`, `visual_slots` | **Generator Model** | Drawn by generator prompts, verified by deterministic server checks. |
| `difficulty` | **System Verified** | Requested during drafting, independently re-rated by the quality gate. |
| `archetype` | **Derived Locally** | Computed deterministically by inspecting `body` Markdown; never self-reported. |
| `is_hero` | **Pipeline Assigned** | Set by a dedicated generation call; never an optional LLM self-report. |
| `content_embedding` | **Derived Locally** | Generated from `body` text post-generation via local embedder. |
| `status`, `version`, `family_id` | **Database System** | Managed exclusively by database transactions; never set by models. |

The pipeline enforces a fundamental rule: **The generator is trusted for taste, never for constraints.** Anything that must be strictly true—column budgets, character limits, structural tagging, difficulty ratings—is enforced or verified deterministically by server-side code outside the model.

## Summary as a Standalone Hook

In the feed interface, a collapsed card displays `title` and `summary`. When tapped, the card expands to reveal the full `body`.

`summary` is an independently written hook designed to stop a scrolling user, not an automated truncation or extraction of the first lines of `body`. The opening lines of a thorough explanation often contain contextual framing or throat-clearing, whereas the hook that captures user attention in a scrolling feed requires punchy, immediate relevance. Truncating `body` also introduces awkward mid-sentence breaks. Truncation with CSS `line-clamp` serves purely as an emergency rendering fallback if `summary` is absent.

## Difficulty as an Objective Card Property

Difficulty (`beginner`, `intermediate`, `advanced`) is an intrinsic property of the **card**, not of the user and not of the user-card pairing. A card explaining the conceptual role of a database index is beginner material; a card analyzing B-tree page split concurrency protocols is advanced material, regardless of who reads it.

Because language models exhibit optimism bias and inconsistency when self-reporting difficulty, the quality gate ignores the generator model's self-assessed difficulty and independently re-evaluates the card's difficulty tier using a separate classifier pass before persisting to the database. In the feed, personalization is achieved by serving a probability distribution of card difficulties matched to the user's earned tier (e.g. an intermediate user receives 70% intermediate, 20% beginner reinforcement, and 10% advanced stretch cards).
