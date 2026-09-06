# Antigravity Global Rules & Operating Principles

This file defines the mandatory operational constraints and execution contracts for Antigravity across the repository.

---

## 1. Absolute Rule: Never Ever Do What Is Not Told (No Shortcuts, No Bypassing)

- **Strict Adherence to Instructions:** Never take unapproved shortcuts, guess, fabricate, or substitute programmatic heuristics for explicit procedural requirements.
- **No Unapproved Helper Scripts or Synthesis:** If a task requires visual inspection, individual verification, or manual editorial review, you are strictly forbidden from writing bulk scripts that scrape metadata, hallucinate data, or fake the required process.
- **Zero Hallucinated or Guessed Data:** Every URL, filename, path, citation, or metric committed to the repository must be verified in real time (e.g., live HTTP 200 checks for URLs, filesystem checks for files). Never guess URLs or CDN paths.
- **Fail Loudly & Ask Rather Than Shortcut:** If a requested scale (e.g., hundreds of items) is time-intensive to do genuinely under the rules, state the exact workload, do it genuinely batch-by-batch, and never pretend to have followed a rule when a script bypassed it.

---

## 2. Image Manifest Sourcing Invariants (ADR-0095 & § 10)

1. **Mandatory Vision Inspection via `view_file`:**
   - Every single image described in an `images.md` manifest must be downloaded locally to scratch and visually inspected using `view_file` with multimodal vision.
   - Descriptions must be authored **strictly from what is visible in the frame** (composition, palette, morphology, framing, details) to serve as dense semantic retrieval bait.
   - **Never copy archive captions, metadata, or alt text.**
   - Remove temporary scratch images after inspection; never commit image binary blobs to git.

2. **100% Verified Live Links:**
   - Every `source_url` and `source_page` must return `HTTP 200 OK` under real browser headers.
   - For NASA assets, query `https://images-api.nasa.gov/asset/{nasa_id}` to retrieve existing `~orig.jpg` or `~large.jpg` endpoints (never assume `~medium.jpg` exists).
   - For Wikimedia Commons assets, query `commons.wikimedia.org/w/api.php?action=query` to obtain the verified filename and CDN URL (never synthesize hash directories like `/5/52/`).

3. **Schema & License Invariants:**
   - Manifests must follow § 10 of `docs/handoff/antigravity-corpus-authoring.md`.
   - Licenses must come strictly from the closed allowlist: `cc0`, `public-domain`, `cc-by`, `cc-by-sa`, `unsplash`, `pexels`, `pixabay`.
   - Empty manifests (`images: []`) are mandatory for non-visual subjects (pure code/theory).

---

## 3. Generalized Visual Distribution & Mermaid Diagram Compensation Principle

### Three-Tier Image Distribution Framework
A typical Spoin subject generates **500 to 750 cards**. Sourcing hundreds of photographic images per subject creates diminishing pedagogical returns, cognitive clutter, and high semantic dilution (unrelated cards being assigned loosely-matched images). All subjects across the universe follow a generalized three-tier distribution:

1. **Tier 1: Visually Rich & Observational (60–80 images):**
   - *Subjects:* Astronomy, Human Biology, World History, World Mythology, Natural Sciences.
   - *Architecture:* Sized at ~8–10 images per chapter across 7–9 chapters, providing ~1 visual anchor for every 7–9 cards (~10–15% visual density).
   - Every core morphological structure, celestial phenomenon, historical era, or mythological pantheon must have at least one verified visual anchor.
   - Sourced methodically in steady batches of 12–15 images with 100% `view_file` multimodal vision inspection.

2. **Tier 2: Cultural, Historic & Artifact-Grounded (20–35 images):**
   - *Subjects:* World Philosophy, Vedic Philosophy (Bhagavad Gita), General Psychology, 10m Air Pistol, Game Development.
   - *Architecture:* Sourced strictly around authentic primary physical artifacts (ancient manuscripts, historical laboratory instruments, competition equipment, early computing hardware). Abstract ideas are never paired with synthetic stock imagery.

3. **Tier 3: Pure Code, Architecture & Theory (0 images — `images: []`):**
   - *Subjects:* Rust, Generative AI, LangChain, Backend Engineering, Frontend Engineering, Fullstack Engineering, Systems Engineering.
   - *Architecture:* Manifests must be strictly empty (`images: []`). Stock photographs of laptops, glowing motherboards, or screens illustrate nothing and degrade feed credibility.

### Mandatory Mermaid Diagram Compensation for Pure Code / Theory
For all **Tier 3 (pure code & theory)** subjects, corpus authors and card generators **MUST compensate for zero photographic images by authoring a substantially higher density of client-rendered Mermaid diagrams (` ```mermaid `)**:
- Abstract mechanisms—including memory layouts, pointer graphs, borrow-checker lifespans, AST transformations, network protocol flows, state machines, and concurrency pipelines—must be visually grounded in structured Mermaid blocks within the prose chunks.
- When generating cards or writing corpus chunks for code/theory, diagrams take the place of photos as the primary visual learning mechanism.

---

## 4. Operational Playbook & Reinforcement Learning

For all future topic authoring runs across all three required phases:
1. **Knowledge (Corpus chunks for Frog):** Strictly $\le 2200$ chars, one `##` heading = one chunk, zero preamble, self-contained terminology, mandatory `tips-and-tricks.md`.
2. **Images (Visual anchors):** 100% multimodal `view_file` visual inspection, live HTTP 200 checks, closed allowlist licenses, zero binary commits.
3. **Curriculum (Authored teaching structure):** 10–12 subtopics in an acyclic DAG, 500–750 total cards ($5 \le \text{target\_cards} \le 25$), non-technical `code: 0`.

Read and strictly adhere to the operational playbook:
[`docs/handoff/reinforcement-learning-topic-authoring.md`](docs/handoff/reinforcement-learning-topic-authoring.md).


