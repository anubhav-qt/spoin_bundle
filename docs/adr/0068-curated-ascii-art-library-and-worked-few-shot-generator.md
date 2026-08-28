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
