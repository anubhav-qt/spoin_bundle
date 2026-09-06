# Antigravity Global Directives & Operating Constraints

## 1. Absolute Directive: NEVER EVER DO WHAT IS NOT TOLD

This is a permanent, non-negotiable instruction for Antigravity across all tasks in this repository:

1. **Strict Instruction Adherence:**
   - Follow every instruction to the letter.
   - Never take unapproved shortcuts, guess, synthesize, or substitute programmatic heuristics for explicit procedural requirements.
   - If the user or instructions state that images must be visually inspected using multimodal vision, **every single image must be downloaded and inspected via `view_file`**.
   - **Never write or use helper functions/scripts to generate, synthesize, scrape, or summarize descriptions** from metadata, captions, alt-text, or catalogues.

2. **No Hallucinations or Guessed Data:**
   - Every URL must be verified with a live `HTTP 200 OK` check before inclusion. Never synthesize Wikimedia MD5 hash paths (e.g., `/5/52/`) or assume asset sizes (e.g., `~medium.jpg`).
   - Every file path, citation, and attribution must be grounded in reality.

3. **Honesty & Transparency Over Shortcuts:**
   - If a task involves high volume and requires genuine vision inspection or manual verification, execute it methodically one-by-one or in steady batches.
   - Never generate bulk synthetic content and pretend it was visually inspected or manually reviewed.
   - When in doubt, ask or proceed genuinely. Never bypass user requirements.

---

## 2. Image Catalog Contract (§ 10 & ADR-0095)

For all image manifests under `docs/the_spoin_universe/images/`:
- **Process for every single image entry:**
  1. Identify image need from corpus chunks.
  2. Query official API (NASA images-api or Wikimedia action=query) for verified asset URL.
  3. Verify `HTTP 200 OK`.
  4. Download image temporarily to `scratch/`.
  5. Open and inspect the image using `view_file` to feed raw pixels directly into vision.
  6. Author a rich 2–4 sentence description based strictly on what is visually observable in the frame (composition, color palette, morphology, framing, perspective) to serve as semantic retrieval bait.
  7. Record the manifest entry in `images.md`.
  8. Delete the temporary scratch image.
- **Licenses:** Strictly from approved allowlist: `cc0`, `public-domain`, `cc-by`, `cc-by-sa`, `unsplash`, `pexels`, `pixabay`.
- **Binaries:** Manifest entries only. Never commit image binary files to git.

---

## 3. Generalized Visual Distribution & Mermaid Diagram Compensation

### Sizing Invariants (500–750 Cards per Subject)
All subjects across the Spoin universe follow an agreed three-tier visual distribution model:
1. **Tier 1: Visually Rich & Observational (60–80 images):**
   - *Subjects:* Astronomy, Human Biology, World History, World Mythology, Natural Sciences.
   - *Coverage:* ~8–10 images per chapter across 7–9 chapters (~1 visual anchor per 7–9 cards / 10–15% visual density).
   - Guarantees every primary astronomical body, biological/anatomical system, historical era, or mythological figure has at least one verified image.
   - Sourced in batches of 12–15 images with mandatory multimodal `view_file` visual inspection.

2. **Tier 2: Cultural, Historic & Artifact-Grounded (20–35 images):**
   - *Subjects:* World Philosophy, Vedic Philosophy (Gita), General Psychology, 10m Air Pistol, Game Development.
   - Grounded strictly in authentic primary artifacts: ancient manuscripts, historical laboratory instruments, competition equipment, early computing hardware. Never padded with generic stock imagery.

3. **Tier 3: Pure Code, Architecture & Theory (0 images — `images: []`):**
   - *Subjects:* Rust, Generative AI, LangChain, Backend Engineering, Frontend Engineering, Fullstack Engineering, Systems Engineering.
   - Empty manifests (`images: []`) are mandatory. Stock photos of keyboards, monitors, or abstract glowing lines are strictly banned.

### Mandatory Mermaid Diagram Density for Tier 3
Because pure code and theory subjects have zero photographic images, **they MUST compensate with a substantially higher density of Mermaid diagrams (` ```mermaid `)**:
- Abstract mechanisms (memory layouts, pointer graphs, borrow-checker lifespans, AST transformations, network protocol flows, state machines, and concurrency pipelines) must be visually explained using structured Mermaid flowcharts, sequence diagrams, and state diagrams directly within the corpus chunks.
- When generating cards or writing corpus chunks for code/theory, diagrams take the place of photos as the primary visual learning mechanism.

---

## 4. Operational Playbook & Reinforcement Learning

For all future topic authoring runs across all three required phases:
1. **Knowledge (Corpus chunks for Frog):** Strictly $\le 2200$ chars, one `##` heading = one chunk, zero preamble, self-contained terminology, mandatory `tips-and-tricks.md`.
2. **Images (Visual anchors):** 100% multimodal `view_file` visual inspection, live HTTP 200 checks, closed allowlist licenses, zero binary commits.
3. **Curriculum (Authored teaching structure):** 10–12 subtopics in an acyclic DAG, 500–750 total cards ($5 \le \text{target\_cards} \le 25$), non-technical `code: 0`.

Read and strictly adhere to the operational playbook:
[`docs/handoff/reinforcement-learning-topic-authoring.md`](docs/handoff/reinforcement-learning-topic-authoring.md).


