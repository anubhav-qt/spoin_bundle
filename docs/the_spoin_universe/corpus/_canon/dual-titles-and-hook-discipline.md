---
title: Dual Titles, Feed Scroll Dynamics, and Hook Layer Separation
kind: spoin_canon
source: Spoin ADR-0022 and CLAUDE.md
topic_tags:
  - spoin canon
  - dual titles
  - hook layer
  - scroll dynamics
  - writing style
---

## Dual Titles Architecture: Display Title versus Canonical Title

Every card maintains two distinct title fields, established in ADR-0022:

1. **`title` (Display Title):**
   - Rendered on the front of the card in the vertical feed.
   - Purpose: Engages the reader and stops a scrolling feed. It can be witty, evocative, framing-oriented, or playful (e.g. *"The Ghost in the Database"* or *"Why Your Thread Pool is Lying to You"*). A configurable percentage of display titles are playful, while others remain direct.
2. **`canonical_title` (Machine and System Title):**
   - The literal, unembellished, descriptive name of the concept (e.g. *"PostgreSQL MVCC Snapshot Isolation"* or *"Little's Law and Connection Pool Sizing"*).
   - Read by every automated downstream consumer: search indexing, quiz question stems, remediation link lists, curriculum progress trackers, topic coverage maps, and deduplication comparisons.
   - Crucially, the card generator prompt's "already-covered" list consumes **both** titles: `canonical_title` so the model knows the concept is already taught, and `title` so it does not repeat the same joke or metaphor.

A single title field fails because wit in search results looks unindexed, while dry literal titles across a mobile vertical feed feel like reading an index card catalog. Dual titles decouple presentation charm from system indexing.

## Feed Scroll Dynamics and Hook Mechanics

Spoin delivers learning through an endless vertical feed. The reader's default posture is passive scrolling; card engagement requires arresting motion in a fraction of a second.

A successful hook operates across three coordinated surfaces in the collapsed card preview:
- The **`title`** establishes curiosity, framing, or tension.
- The **`summary`** delivers immediate punchiness without throat-clearing, posing a concrete technical puzzle, an unexpected consequence, or a crisp breakdown of a common assumption.
- The **ASCII art** (when present) provides visual humor or a recognizable pop-culture metaphor that anchors the concept.

If the hook relies on generic textbook phrases (e.g. *"In this card, we will explore the importance of caching"*), the user scrolls past. If the hook is provocative but decoupled from the actual technical mechanism, the user feels misled when expanding the card. The hook must be an honest, witty gateway into the technical reality.

## Strict Separation: Silliness in the Hook, Truth in the Body

The central editorial rule governing Spoin card generation is defined in `CLAUDE.md`:

> **Silliness lives in the hook layer — `title`, `summary`, ASCII art. Never in `body`.**

The product's promise is quiz-gated mastery of *true technical things*. Once a user taps to expand a card, the full `body` scrolls into view. That `body` is subject to strict constraints:
- **Zero jokes in the explanation:** A joke or whimsical metaphor in `body` becomes noise when a reader is attempting to understand an intricate causal chain (such as the two-phase commit protocol or TLS 1.3 key derivation).
- **Tested material:** Card `body` text is the exact material quiz questions are derived from and tested against. If a card uses a whimsical analogy to explain an isolation level, the user is forced to answer quiz questions based on the analogy rather than the real-world engineering standard.
- **Quality gate evaluation:** Automated verification passes evaluate `body` as ground truth. Joking or sarcastic prose degrades the quality gate's ability to verify factual correctness against the reference corpus.

A joke in the hook is charm; a joke in the explanation is an engineering defect.
