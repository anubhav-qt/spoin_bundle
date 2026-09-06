# Reinforcement Learning & Operational Playbook: Topic Authoring

> **Who this is for:** Antigravity agents in current and future sessions authoring, expanding, or curating topics in `the_spoin_universe`.  
> **Origin:** Distilled directly from the production execution of the **Astronomy** survey expansion (2026-09-06), spanning all three required phases: **Knowledge**, **Images**, and **Curriculum**.  
> **Companion Contracts:** [`antigravity-corpus-authoring.md`](antigravity-corpus-authoring.md), [`antigravity-curriculum-authoring.md`](antigravity-curriculum-authoring.md), [`next-image-sourcing.md`](next-image-sourcing.md), and [`procedure.md`](../the_spoin_universe/procedure.md).

---

## 0. The Golden Rule of Execution

> **NEVER EVER DO WHAT IS NOT TOLD. ZERO SHORTCUTS. ASK AND PROPOSE BEFORE WRITING.**

- **No Automated Bypasses:** Do not write helper scripts that scrape metadata, hallucinate captions, or bypass manual review.
- **Genuine Vision Inspection:** Every single image described in an `images.md` manifest must be downloaded locally to scratch and visually inspected using `view_file` with multimodal vision.
- **Live HTTP 200 Checks:** Every single URL committed must return a live `HTTP 200 OK` under real browser headers. Never guess or synthesize Wikimedia MD5 hash paths (`/5/52/`).
- **Phase Ordering is Absolute:**
  ```
  PHASE 1: KNOWLEDGE   (docs/the_spoin_universe/corpus/…)     -> Chunks for Frog
  PHASE 2: IMAGES      (docs/the_spoin_universe/images/…)     -> Verified visual anchors
  PHASE 3: CURRICULUM  (docs/the_spoin_universe/curricula/…)  -> Authored teaching structure
  ```
  **Never start Phase 2 until Phase 1 is validated. Never start Phase 3 until Phase 1 and 2 are delivered and accepted by the owner.**
- **Propose Before Authoring:** In Phase 3, present a single argued curriculum structure to the project owner for feedback and approval before writing any files.

---

## 1. Phase 1 — Knowledge: Corpus Authoring for Frog

### 1.1 The Frog Chunking Contract
Frog's ingest pipeline (`apps/frog/src/frog/ingest/contract.py`) enforces hard structural rules:
1. **One `##` Heading = One Chunk:** Sections are bounded strictly by level-2 headings (`##`). Nothing auto-splits an oversized section downstream.
2. **Hard Ceiling: $\le 2,200$ Characters (~512 Tokens):**
   - Any section exceeding 2,200 characters fails ingestion with a fatal contract violation (`SectionTooLong`).
   - Aim for **1,000–2,000 characters** (corpus median is ~1,550).
   - If a section exceeds 2,200 characters, it is almost always **two ideas wearing one heading**. Split it into two distinct `##` headings.
3. **Zero Preamble Prose:**
   - Files must open with YAML frontmatter (`---` ... `---`) immediately followed by the first `##` heading.
   - Any prose before the first `##` heading becomes an orphaned, headless preamble that fails the contract (`DocumentHasPreamble`).
4. **Self-Contained Chunks (The Prompt Isolation Rule):**
   - A chunk is retrieved and dropped into a generation prompt alongside 5 random chunks from other topics.
   - **Never use relative references:** Avoid *"as mentioned above"*, *"in the next chapter"*, *"see earlier"*, or *"as we saw"*.
   - Define all technical terms, physical variables, and notation in-situ within each section.
5. **Mandatory `tips-and-tricks.md`:**
   - Every subject (survey or topic) must include a dedicated `tips-and-tricks.md` capturing hard-learned operational traps, measurement traps, observational pitfalls, atmospheric biases, and practitioner field rules.

### 1.2 Validation Command
Run the Python contract check across the target topic files:
```powershell
python -c "
import sys; from pathlib import Path; sys.path.insert(0, 'apps/frog/src')
from frog.ingest.contract import parse_document
p = Path('docs/the_spoin_universe/corpus/<topic_path>')
for f in sorted(p.glob('*.md')):
    doc, errs = parse_document(str(f), f.read_bytes())
    print(f'{f.name}: {len(doc.sections)} sections, max={max(len(s.text) for s in doc.sections)}, errs={len(errs.problems)}')
"
```
Ensure **zero problems** across all files.

---

## 2. Phase 2 — Images: Visual Anchors & Retrieval Bait

### 2.1 The Three-Tier Distribution Model
A complete Spoin topic targets **500–750 cards**. Sourcing hundreds of photographic images creates cognitive clutter and semantic dilution. Follow the universe tier distribution:

1. **Tier 1: Visually Rich & Observational (60–80 images):**
   - *Subjects:* Astronomy, Human Biology, World History, World Mythology, Natural Sciences.
   - Sized at ~8–10 images per chapter across 7–9 chapters (~1 visual anchor per 7–8 cards / 10–15% visual density).
   - Sourced methodically in batches of 12–15 with 100% `view_file` multimodal vision inspection.
2. **Tier 2: Cultural, Historic & Artifact-Grounded (20–35 images):**
   - *Subjects:* World Philosophy, Vedic Philosophy, General Psychology, 10m Air Pistol, Game Development.
   - Strictly authentic primary physical artifacts (ancient manuscripts, historical instruments, competition gear). No stock filler.
3. **Tier 3: Pure Code, Architecture & Theory (0 images — `images: []`):**
   - *Subjects:* Rust, Generative AI, LangChain, Backend, Frontend, Systems Engineering.
   - Must have an empty manifest (`images: []`). Compensated by high Mermaid diagram density.

### 2.2 Sourcing Invariants & Workflow
For every single image entry:
1. **Official API Query:**
   - NASA: Query `https://images-api.nasa.gov/asset/{nasa_id}` to find live `~large.jpg` or `~orig.jpg` endpoints.
   - Wikimedia Commons: Query `https://commons.wikimedia.org/w/api.php?action=query&titles=File:{filename}&prop=imageinfo&iiprop=url|extmetadata&format=json` to fetch verified CDN URLs.
2. **Live HTTP 200 Verification:**
   - In PowerShell, run `curl.exe -I -s -L "{url}"` (do not use PowerShell's alias `curl` which maps to `Invoke-WebRequest`). Verify `HTTP/2 200` or `HTTP/1.1 200 OK`.
3. **Temporary Scratch Download:**
   - Download the image to `scratch/temp_img.jpg`.
4. **Mandatory Vision Inspection via `view_file`:**
   - Open `scratch/temp_img.jpg` with `view_file` to feed raw pixels directly into your multimodal vision.
   - Author a rich 2–4 sentence description based **strictly on what is visible in the frame** (composition, palette, morphology, framing, perspective).
   - **Never copy archive captions, metadata, or alt text.** The description serves as dense semantic retrieval bait for cards.
5. **Immediate Scratch Cleanup:**
   - Delete `scratch/temp_img.jpg` immediately (`Remove-Item -Force "scratch/temp_img.jpg"`). Never commit binary image files to git.
6. **Closed License Allowlist:**
   - Only: `cc0`, `public-domain`, `cc-by`, `cc-by-sa`, `unsplash`, `pexels`, `pixabay`. (No NC, no ND).
7. **YAML Syntax Gotcha (Colons in Attributions):**
   - Any attribution containing internal colons (e.g., `attribution: X-ray: NASA/CXC...`) will crash PyYAML with a scanner error unless enclosed in double quotes:
     `attribution: "X-ray: NASA/CXC; Optical: NASA/STScI"`

### 2.3 Manifest Validation Command
```powershell
python -c "
import yaml; from pathlib import Path
p = Path('docs/the_spoin_universe/images/<topic_path>/images.md')
text = p.read_text(encoding='utf-8')
meta = yaml.safe_load(text.split('---', 2)[1])
imgs = meta.get('images', [])
print(f'YAML Valid! Count: {len(imgs)}')
"
```

---

## 3. Phase 3 — Curriculum: Authored Teaching Structure

### 3.1 The Curriculum Contract
The curriculum file is authored data, not generated text (`docs/the_spoin_universe/curricula/<topic>/curriculum.md`):
- **YAML Front Matter Only:** Leading `---`, YAML block, closing `---`. Nothing but whitespace after (no markdown prose body).
- **Topic Sizing:** Targets **500–750 cards** across all tiers:
  - Typically 8–12 subtopics.
  - Each subtopic targets **~50–60 cards across 3 tiers** (~16–20 cards per tier).
- **Database Band Invariant:**
  - `target_cards` must satisfy `5 <= target_cards <= 25` per tier.
  - `card_types` quotas must sum exactly to `target_cards`.

### 3.2 The 5 Card-Type Vocabularies
Only these 5 types exist:
- `prose`: Core technical explanation carrying the concept.
- `code`: Worked code example. **Strictly 0 for non-technical topics** (enforced outside the prompt).
- `diagram`: Client-rendered Mermaid diagrams (` ```mermaid `).
- `comparison`: Myth vs. Fact, A vs. B, or comparative trade-off tables.
- `ascii`: Single-use scenes from the curated ASCII library.

### 3.3 The Visual Balance Principle in Quotas
- **When Sourcing Tier 1 (Photographic subjects like Astronomy):**
  - Our 60–80 photographs are the **primary visual anchor** of the feed, attached dynamically server-side via embedding retrieval (~1 photo per 7–8 cards).
  - Do not bloat `diagram` quotas. Keep **`diagram: 1`** per tier, reserved exclusively for things photos cannot communicate (flowcharts, nuclear cycles, evolutionary tracks).
  - Use **`prose: 14–16`**, **`comparison: 2–3`**, **`diagram: 1`**, **`ascii: 1`**.
- **When Sourcing Tier 3 (Pure Code & Theory like Rust):**
  - Because photos are zero (`images: []`), **compensate heavily with `diagram: 2–4`** so the feed receives structured Mermaid SVGs instead of a wall of dry text.

### 3.4 Prerequisites DAG Design
- Prerequisites must reference exact `title` strings of other subtopics in the same file.
- The prerequisite graph must be strictly acyclic.
- **Conceptual Philosophy:** Treat the DAG as a broad gating map for tier quizzes and discovery, not an overly restrictive single-track railroad. Provide multiple independent entry points (roots with `prerequisites: []`) to enable multi-track learner exploration.

### 3.5 Curriculum Validation Command
```powershell
$env:PYTHONPATH="apps/frog/src"
python -c "
from pathlib import Path
from frog.curriculum.runner import validate_curricula
p, f = validate_curricula(Path('docs/the_spoin_universe/curricula'), Path('docs/the_spoin_universe/corpus'))
print(f'Passed: {len(p)}, Failed: {len(f)}')
for x in p:
    total = sum(t.target_cards for s in x.subtopics for t in s.tiers)
    print(f'  {x.topic}: {len(x.subtopics)} subtopics, {total} cards')
for err in f:
    print(f'FAIL: {err.source_path}: {err.problems}')
"
```

---

## 4. Environment & Tooling Gotchas on Windows / PowerShell

1. **`curl` vs `curl.exe`:**
   - In PowerShell, typing `curl` invokes the alias for `Invoke-WebRequest`.
   - Always run **`curl.exe`** when executing command-line web requests, inspecting HTTP headers, or downloading temporary assets.
2. **Python Import Resolution:**
   - To run pytest or scripts importing `frog`, always prepend the environment path:
     `$env:PYTHONPATH="apps/frog/src"; python -m pytest apps/frog/tests`
3. **Archiving Invariant:**
   - Non-active topics are archived via `git mv` into `docs/the_spoin_universe/_archive/`.
   - **Never delete files.** Everything must remain versioned and restorable.
   - Keep `docs/the_spoin_universe/corpus/_canon/` in active corpus, as generation prompt code hard-codes its path.
4. **Clean Workspace Rule:**
   - Scratch scripts or temporary files belong in `scratch/`.
   - Before finishing any session, verify `scratch/` contains zero binary blobs (`.jpg`, `.png`).
