# TODO: Spoin Card Generator Prompt Updates & Art Library Refinements

> **Status**: In Progress — Active refinement of curated ASCII reference library and few-shot examples.  
> **Target Files**: [`apps/api/src/spoin/generation/prompts/cards.py`](file:///e:/spoin_bundle/apps/api/src/spoin/generation/prompts/cards.py) and [`apps/api/src/spoin/generation/langchain_impl.py`](file:///e:/spoin_bundle/apps/api/src/spoin/generation/langchain_impl.py).

---

## 🎯 Semantic Understanding of User Refinement Rules

### 1. 🌟 Promote Fancy, Screenshot-Worthy & Trendy GenZ Content
- **Curated Pop Culture**: Actively leverage expressive characters (Homer, Bart, Yoda, Snoopy, Garfield, Pikachu, Mermaids, Dragons, South Park, Superman, Dalek) from the curated DB rather than generic 1-liners.
- **Two-Pass Scanning Pipeline**:
  1. **Pass 1 (Pre-Scan Library)**: Generator scans the full curated DB *before* reading the granular subtopic title to absorb available creative visual assets.
  2. **Pass 2 (Contextual Match & Adapt)**: Generator matches the topic concepts to the most screenshot-worthy, funny, and educational artwork, tailoring it to the specific concept.

---

### 2. 🚫 STRICTLY PROHIBITED: Text-Only Flowcharts & Box Diagrams
- **Mermaid Agent Scope**: All node-link flowcharts, sequence diagrams, and rectangular text-only box lists are strictly prohibited in ASCII art cards (they are handled exclusively by the Mermaid maker agent).
- **Physical & Pictorial Requirement**: ASCII art cards **must feature genuine pictorial drawings** (physical objects, hardware terminals, calculators, ships, hourglasses, tools, celestial bodies, animals, character figures, 3D packages, etc.), annotated with concise educational text.

---

### 3. 🛠️ Specific Card Fixes & Quality Audits
- **Example 27 (Yoda / Math)**: Fix broken whitespace/ear alignment on Yoda ASCII art.
- **Example 13 (AI Scope)**: Pinky and the Brain permanently removed from reference library as irrelevant. Replaced with authentic AI/Robot/Terminal asset.
- **Example 22 (Gym / Fitness)**: Replace ambiguous boxing gloves with an intuitive strength curve / mechanical torque / cable pulley / free weights illustration.
- **Example 15 (FastAPI Gag)**: Provide clear, relatable alternatives for the synchronous `time.sleep` event loop freeze.
- **Example 5 (Raylib Engine Gag)**: Provide game dev / arcade / controller alternatives for the 2D camera world vs screen space offset.
- **Example 1 (10m Air Pistol Gag)**: Provide dedicated Olympic target marksman / laser focus alternatives rather than Homer Simpson.
- **Ambiguous Postures**: Explicitly disambiguate postures (e.g. always label `(9'-')9` with `*BOXER STANCE*`).

---

### 4. 🗂️ Curated Subcategory Reviews
- **Mermaids**: 22 cards presented for user keep/delete curation.
- **Graduation Caps**: 12 cards presented for user keep/delete curation.
- **Dilbert Characters**: 4 cards presented for user keep/delete curation.
