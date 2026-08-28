# ADR-0068: Curated ASCII Art Reference Library and Worked Few-Shot Generator Standards

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Anubhav
- **Amends:** [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md) (the free-form ASCII generation), [ADR-0067](0067-mermaid-diagrams-and-form-free-ascii.md) (diagram & ASCII scene scope)
- **Related:** [ADR-0021](0021-ascii-scene-library.md), [ADR-0059](0059-card-planning-pass-and-prompt-versioning.md), [docs/tasks/0026](../tasks/0026-few-shot-examples-from-manual-review.md)

## Context

Following [ADR-0067](0067-mermaid-diagrams-and-form-free-ascii.md), diagram generation moved exclusively to client-side rendered Mermaid blocks, while ASCII art cards remained dedicated to visual illustrative scenes. However, three operational challenges emerged during feed content review:

1. **Hallucinated or Sideways ASCII Art**: Models prompted for free-form ASCII art without reference anchors frequently produced low-fidelity, unaligned drawings, or sideways text emoticons requiring head rotation to decipher.
2. **Text-Only Box Diagrams Masquerading as Art**: Generator models occasionally produced rectangular text boxes and pseudo-flowcharts inside ASCII slots, duplicating the responsibility of the dedicated Mermaid agent.
3. **Ambiguous Emotes and Irrelevant Pop-Culture Characters**: Generic ASCII emotes lacked clear posture labeling (e.g. boxer stances mistranslated as confusion), and obsolete characters failed to engage the GenZ reader demographic.

## Decision

**1. Curated Reference Art Library as the Visual Source of Truth.**
We establish an authoritative, human-curated ASCII art reference library partitioned into:
- `apps/helpers/use_for_gags.txt` (888 curated gag/pop-culture reference cards).
- `apps/helpers/use_for_informative_visualization.txt` (1,599 curated educational/scientific reference cards).
- Every card is cataloged with a unique 16-character hex hash, descriptive title, artist attribution, categorized metadata, and exact rendering.
- All cards strictly satisfy the invariant: **monospace width $\le 40$ columns** across all lines.

**2. Strict Prohibition on Text-Only Flowcharts in ASCII Cards.**
ASCII cards must strictly contain pictorial artworks (physical objects, characters, hardware, tools, icons, astronomical bodies, animal figures). Node-link diagrams, sequence graphs, and rectangular flowchart boxes are strictly prohibited in ASCII art and handled solely by the Mermaid agent.

**3. Two-Pass Scanning Pipeline for Generator Prompts.**
Generator models scan the curated reference library in two passes:
- **Pass 1 (Pre-Scan)**: Scan available creative visual assets before inspecting subtopic titles.
- **Pass 2 (Contextual Match & Adapt)**: Match concepts to screenshot-worthy, funny, or educational artworks, enriching them with witty contextual dialogues and posture labels (e.g., `*BOXER STANCE*`).

**4. 42 Worked Few-Shot Examples Across All 21 Active DB Topics.**
`apps/helpers/ascii_art_library/examples.txt` and `apps/helpers/examples.txt` provide 42 fully worked few-shot examples (1 Gag + 1 Informative per topic across all 21 active database topics), establishing consistent prompt baselines for hook sharpness, structural markdown bodies, and $\le 40$-column ASCII art with dialogue annotations.

**5. Systematic Curated Purge of Weak Assets.**
- Obsolete, unreadable, or ambiguous characters (e.g., Dilbert, Pinky & the Brain, garbled Yoda fragments) are permanently removed from the library.
- Refined subcategories (e.g. Mermaids reduced to top 2 high-fidelity compositions, graduation caps consolidated to graduate portrait, Popeye and Garfield curated to clear expressive poses).

## Consequences

- **High-Fidelity Generation Quality**: LLM generators ground ASCII visual planning in proven, beautiful compositions rather than unconstrained pixel hallucinations.
- **Zero Monospace Overflow**: 100% of curated reference cards and worked examples conform to $\le 40$ monospace characters, preventing horizontal scroll on mobile devices.
- **Clear Architectural Separation**: Mermaid handles abstract flowcharts and architecture graphs; ASCII art handles character gags, physical objects, and memorable visual metaphors.
- **Durable Catalog**: The curated catalog is maintained in `apps/helpers/` with automated verification scripts (`generate_db_topic_examples.py`, `curate_spoin_art.py`).

## Alternatives Considered

- **Pure Generator Free-Form Generation Without Catalog**: Rejected because LLMs lack spatial coordinate awareness, leading to malformed drawings and line overflows.
- **Static Inflexible Asset Insertion**: Rejected because cards require dynamic dialogue bubbles, labels, and contextual adaptation to the specific learning topic.

## Revisit When

- Model visual-spatial reasoning reaches a level where unconstrained zero-shot ASCII synthesis achieves $100\%$ structural fidelity and zero column overflow without reference anchors.

## Implementation note (Task 0029, added after this ADR was accepted)

§3's "two-pass scanning" is realized as **retrieval, not literal scanning** — pasting
either curated file's full contents into a prompt (888 / 1,599 entries) does not fit
any prompt budget. `spoin.content.ascii_library` embeds every entry's TITLE once per
process (local, never-quota'd — the same `get_embedder()` every other similarity
feature in the codebase uses) and, for each `ascii`-typed planned card, embeds that
card's own `asset_direction` and returns the top-10 nearest titles by cosine
similarity. Those ten — title and art both — are shown in that card's own brief in
`generate_cards`'s user prompt, alongside an instruction to adapt one if it fits or
draw original art if none does (never a forced pick, per CLAUDE.md's "trusted for
taste, never for constraints" — the same posture ADR-0067 already took). The two
curated files are duplicated into `apps/api/src/spoin/content/ascii_library_data/` as
the deployed copy, since `apps/api/Dockerfile` never `COPY`s the sibling
`apps/helpers/` tooling directory into the image; that copy needs a manual re-sync
after any edit to the `apps/helpers/` originals (see
[Task 0030](../tasks/0030-manual-review-curated-ascii-library.md)).

**Conflict with §2 resolved (2026-08-28):** §2 above states ASCII cards
"must strictly contain pictorial artworks" and that non-pictorial forms are
"strictly prohibited." Per project owner decision, §2 strictly pictorial
requirement is authoritative for the curated reference library and visual
generations. All curated assets in `apps/helpers/` and runtime reference data
must be pictorial visual artworks. Non-pictorial entries (e.g. text-only
checklists, pure typography) are excluded.


The "22 Mermaids / 12 graduation caps / 4 Dilbert" keep/delete review and the
per-example fixes named in `apps/helpers/TODO_GENERATOR_PROMPTS.md` are curation work
on the library's content, tracked as [Task 0030](../tasks/0030-manual-review-curated-ascii-library.md)
rather than closed by this note.
