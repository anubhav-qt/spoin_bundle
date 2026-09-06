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

## 2. Phase 2 — Images: Visual Anchors & Semantic Retrieval Bait

> **Mandatory Reference Contracts:** [`docs/handoff/antigravity-corpus-authoring.md`](antigravity-corpus-authoring.md) § 10, [`docs/adr/0095-open-licensed-image-catalog.md`](../adr/0095-open-licensed-image-catalog.md), and [`docs/handoff/next-image-sourcing.md`](next-image-sourcing.md).  
> **Applicability:** Standing operational procedure for **all current and future agents** sourcing imagery across ANY subject in the Spoin Universe.

---

### 2.1 The Master Universe Subject Distribution Framework

A standard Spoin subject generates **500 to 750 cards** across 8–12 subtopics. Attempting to source hundreds of images creates severe semantic dilution (unrelated cards being assigned loosely matched stock photos), cognitive clutter, and high maintenance overhead. 

All topics across the Spoin Universe strictly follow a **three-tier visual distribution model**:

| Category | Subject Slug | Subject Name | Tier | Target Images | Visual Domain & Allowable Sources |
|---|---|---|---|---|---|
| `astronomy` | `astronomy` | Astronomy | **Tier 1** | **60–80** | NASA, ESA/Hubble, JWST, ESO. Core celestial bodies, deep-sky phenomena, planetary geology, instrumentation (~8–10 per chapter). |
| `science` | `human-biology` | Human Biology | **Tier 1** | **60–80** | NIH/NLM, CDC PHIL, Wellcome Collection, classical histological plates, electron micrographs. Anatomical systems, cellular morphology, physiological mechanisms. |
| `history` | `world-history` | World History | **Tier 1** | **60–80** | Library of Congress, Europeana, Smithsonian Open Access, Met Museum. Primary archaeological artifacts, monumental architecture, contemporaneous maps, epigraphy. |
| `mythology` | `world-mythology` | World Mythology | **Tier 1** | **60–80** | The Met, Rijksmuseum, Getty Open Content, British Library. Classical statuary, temple reliefs, illuminated codices, sacred iconography. |
| `philosophy` | `world-philosophy` | World Philosophy | **Tier 2** | **20–35** | Classical portrait busts, primary manuscript folios (papyrus, parchment), historical academy sites. **Abstract ideas are never given stock photos.** |
| `spirituality` | `bhagavad-gita` | Vedic Philosophy (Gita) | **Tier 2** | **20–35** | Historical Sanskrit manuscripts (Schøyen Collection, National Museum), classical temple reliefs, traditional iconographic representations. |
| `psychology` | `general-psychology` | General Psychology | **Tier 2** | **20–35** | Primary historical apparatus (Wundt tachistoscope, Skinner box), standardized optical illusion plates, classical EEG tracings. **Zero stock photos of glowing brains or stressed actors.** |
| `sports` | `10m-air-pistol` | 10m Air Pistol | **Tier 2** | **20–35** | ISSF Olympic competition photography, match equipment (Steyr LP50, Walther LP500), mechanical front/rear sights, electronic target geometry (SCATT). |
| `computer-science` | `game-development` | Game Development | **Tier 2** | **20–35** | Vintage arcade cabinets, milestone console hardware (Magnavox Odyssey, Atari 2600), PDP-1 Spacewar CRT setups, early dev kits. **Zero copyrighted game screenshots.** |
| `computer-science` | `rust` | Rust | **Tier 3** | **0 (`images: []`)** | **Pure Code & Theory.** Empty manifest mandatory. Compensated by high Mermaid diagram density (`diagram: 2–4`). |
| `computer-science` | `generative-ai` | Generative AI | **Tier 3** | **0 (`images: []`)** | **Pure Code & Theory.** Zero photos. Stock motherboards/glowing nodes strictly banned. Compensated by Mermaid diagrams. |
| `computer-science` | `langchain` | LangChain / LangGraph | **Tier 3** | **0 (`images: []`)** | **Pure Code & Theory.** Zero photos. Compensated by Mermaid diagrams of agent state graphs and runnable pipelines. |
| `computer-science` | `backend-engineering` | Backend Engineering | **Tier 3** | **0 (`images: []`)** | **Pure Code & Theory.** Zero photos. Compensated by Mermaid diagrams of distributed consensus, LSM trees, and protocol handshakes. |
| `computer-science` | `frontend-engineering` | Frontend Engineering | **Tier 3** | **0 (`images: []`)** | **Pure Code & Theory.** Zero photos. Compensated by Mermaid diagrams of DOM trees, event loops, and render pipelines. |
| `computer-science` | `fullstack-engineering`| Fullstack Engineering | **Tier 3** | **0 (`images: []`)** | **Pure Code & Theory.** Zero photos. Compensated by Mermaid diagrams of auth flows, sync pipelines, and caching layers. |
| `computer-science` | `practically-useful-software-engineering` | Systems & Practice | **Tier 3** | **0 (`images: []`)** | **Pure Code & Theory.** Zero photos. Compensated by Mermaid diagrams of CI/CD DAGs, branching trees, and rollback strategies. |

---

### 2.2 How Images Function in Spoin (Runtime Retrieval Mechanics)

Understanding how the Spoin engine handles images dictates how you author manifests (ADR-0095):

1. **The Model Never Sees Images During Card Drafting:**
   - Card generation prompts are never sent image menus or IDs. (Sending 70+ image descriptions would consume 6k+ tokens per generation batch, blowing token budgets and causing model hallucination of fake image IDs).
2. **Server-Side Semantic Embedding Assignment:**
   - After a card draft is created, the backend embeds the card's text using OpenAI embeddings (`text-embedding-3-small`).
   - It performs a vector cosine similarity search against the embedded **`description` fields** of all images in that topic's `images.md`.
   - The highest-scoring unused image above the similarity floor is assigned to `card.visual_id`.
3. **Single-Use Invariant per Topic:**
   - An image is attached to at most **one card per topic**. Once used, it is excluded from subsequent card matching.
4. **Visual Slot Exclusivity:**
   - A card carries either an ASCII gag, a Mermaid diagram, or a photograph. **A card never carries both an ASCII gag and a photograph** (ADR-0095 § 135).
5. **Feed Visual Density:**
   - For Tier 1 subjects (60–80 images across 500–750 cards), roughly **1 out of every 7–8 cards (~13–15% of the feed)** carries an authentic full-bleed photograph.

---

### 2.3 Authoring `description`: Retrieval Bait, NOT a Caption

> ⚠️ **The `description` field in `images.md` is NOT user-facing text.** It is dense semantic retrieval bait for vector search.

#### Why Copying Alt-Text or Archive Captions Fails
Archive captions say what an image is *filed as*, not what is *visible in the frame*. NASA captions frequently describe the mission history rather than the object; Wikipedia captions summarize geopolitical history rather than the artifact. A card about stellar convection will never retrieve an image whose description only recites satellite orbital telemetry.

#### The 4-Part Description Formula
Every image description must be **2 to 4 dense sentences** written strictly from raw visual inspection:
1. **Framing, Scale & Perspective:** Extreme close-up, wide-field mosaic, cross-sectional cutaway, transmission electron micrograph, oblique aerial perspective, or standardized studio plate.
2. **Palette, Lighting & Spectrum:** False-color composite (mapping narrowband sulfur, hydrogen, oxygen to RGB), natural-color optical, darkfield illumination, high-contrast monochrome, or raking archaeological light.
3. **Visible Morphology & Structural Features:** Explicitly name observable structures — filamentary gas knots, impact crater central peaks, striated muscle sarcomeres, Corinthian acanthus leaves, serrated trigger blades, or papyrus fibers.
4. **Conceptual Vocabulary Hook:** Embed the exact physical, anatomical, astronomical, or technical terms that a high-yield Spoin card teaching this concept would use.

**Good vs. Bad Example (Astronomy):**
- ❌ *Bad:* "The Crab Nebula, designated NGC 1952, photographed by Hubble in 2005." *(Matches almost nothing semantically; vague)*
- ✅ *Good:* "High-resolution optical composite of the Crab Nebula supernova remnant (M1), revealing an intricate filamentary web of ionized gas enclosing an ethereal blue synchrotron glow. Filament structures display dense, tangled knots of orange and red hydrogen and sulfur emissions, surrounding a central diffuse cavity sculpted by the high-energy wind of the central pulsating neutron star." *(Matches cards on pulsars, synchrotron radiation, supernova remnants, and filamentary ionization)*

**Good vs. Bad Example (Human Biology):**
- ❌ *Bad:* "Microscopic view of blood cells."
- ✅ *Good:* "Colorized scanning electron micrograph of human whole blood, displaying biconcave disc-shaped red blood cells (erythrocytes) interspersed with globular, spherical white blood cells (leukocytes) covered in microvillar projections. Faint fibrous strands of fibrin meshwork are visible adhering to activated disc-shaped platelets during early hemostatic plug formation." *(Matches cards on hematology, erythrocyte gas exchange, leukocyte immune function, and clotting cascades)*

**Good vs. Bad Example (Tier 2 Artifact - 10m Air Pistol):**
- ❌ *Bad:* "A match air pistol used in Olympic shooting."
- ✅ *Good:* "High-detail profile photograph of a competition 10-metre match air pistol (Walther LP500), mounted with an anatomical carved walnut target grip featuring an adjustable palm shelf. The frame highlights the ventilated silver barrel shroud, carbon-fiber compressed air cylinder, micro-adjustable square-notch rear sight aperture, and mechanical two-stage trigger shoe set in the forward post position." *(Matches cards on grip shelf ergonomics, trigger shoe positioning, sight alignment, and pneumatic balance)*

---

### 2.4 Authorized Sourcing Gateways & Endpoints

Never guess CDN paths or use scraping heuristics. Query official programmatic APIs:

#### 1. NASA Image and Video Library (`images.nasa.gov`)
- **Search Endpoint:**
  `https://images-api.nasa.gov/search?q={query}&media_type=image`
- **Asset Manifest Query:**
  `https://images-api.nasa.gov/asset/{nasa_id}`
- **Asset URL Rule:**
  Inspect the returned JSON array of URLs. **Always pick `~orig.jpg` or `~large.jpg`**. Never synthesize or assume `~medium.jpg` exists.

#### 2. Wikimedia Commons API
- **Direct Query Endpoint:**
  ```
  https://commons.wikimedia.org/w/api.php?action=query&titles=File:{exact_filename}&prop=imageinfo&iiprop=url|extmetadata&format=json
  ```
- **Hashing Rule:** Never attempt to synthesize Wikimedia directory hashes (e.g. `/5/52/`). Always fetch the verified live URL directly from the `url` property of the `imageinfo` response.

#### 3. Museum Open Access & Primary Archives
- **The Metropolitan Museum of Art:** [Met Open Access API](https://metmuseum.github.io/) (`isPublicDomain: true`).
- **Smithsonian Institution:** [Smithsonian Open Access](https://www.si.edu/openaccess) (CC0 metadata and media).
- **Rijksmuseum:** [Rijksmuseum Data Services](https://data.rijksmuseum.nl/) (public domain high-res plates).
- **Wellcome Collection:** [Wellcome Collection API](https://wellcomecollection.org/works) (historical medicine, microscopy, anatomical plates; CC-BY / Public Domain).
- **Library of Congress:** [loc.gov API](https://www.loc.gov/apis/) (unrestricted photographic collections).
- **Europeana / DPLA:** Open-access European and American heritage repositories.

---

### 2.5 The Mandatory Step-by-Step Execution Protocol

When sourcing images for ANY topic, execute this step-by-step cycle methodically in steady batches of **10 to 15 images**:

```
[1. Identify Need from Corpus] 
       ↓
[2. API Query & URL Extraction] 
       ↓
[3. Live HTTP 200 Verification via curl.exe] 
       ↓
[4. Scratch Download to scratch/temp_img.jpg] 
       ↓
[5. Multimodal Vision Inspection via view_file] 
       ↓
[6. Author Dense Description & Attribution] 
       ↓
[7. Immediate Scratch Cleanup (Delete Binary)] 
       ↓
[8. Append to images.md & Validate YAML]
```

#### Step 1: Corpus Needs Identification
Read the topic's corpus chunks (`docs/the_spoin_universe/corpus/...`). Identify core physical structures, morphological milestones, anatomical systems, or primary artifacts that require visual grounding.

#### Step 2: Query Authorized API & Extract URLs
Query NASA, Wikimedia Commons, or museum endpoints to locate verified asset URLs.

#### Step 3: Live HTTP 200 Verification
In PowerShell, run `curl.exe` (not PowerShell's alias `curl`):
```powershell
curl.exe -I -s -L "https://images-assets.nasa.gov/image/PIA17172/PIA17172~orig.jpg"
```
Verify that the server returns `HTTP/2 200` or `HTTP/1.1 200 OK`.

#### Step 4: Temporary Scratch Download
Download the image binary into the local `scratch/` folder:
```powershell
curl.exe -s -L "https://images-assets.nasa.gov/image/PIA17172/PIA17172~orig.jpg" -o "scratch/temp_img.jpg"
```

#### Step 5: Mandatory Vision Inspection via `view_file`
Call the `view_file` tool on `scratch/temp_img.jpg`:
- This feeds the raw pixel data directly into your multimodal vision model.
- **Inspect visual fidelity:** Confirm image is sharp, uncluttered, free of modern watermarks, free of unreadable foreign text, and genuinely portrays the phenomenon.
- If an image turns out to be an illegible contact sheet, blurry plate, or conceptual artwork, **discard it immediately**.

#### Step 6: Author Manifest Entry
Using the 4-part description formula, write the manifest entry. Author strictly from what is observable in the frame.

#### Step 7: Immediate Scratch Cleanup
Delete the temporary scratch file immediately:
```powershell
Remove-Item -Force "scratch/temp_img.jpg"
```
**CRITICAL INVARIANT:** Never commit image binary files (`.jpg`, `.png`, `.webp`) to git. Only commit manifest text (`images.md`).

---

### 2.6 The Closed License Allowlist & Legal Invariants

Because Spoin is a commercial product, license compliance is absolute and non-negotiable:

| License Key | Description | Requirements |
|---|---|---|
| `cc0` | Creative Commons Zero | Public domain dedication. Attribution listed as `Public domain` or institution name. |
| `public-domain` | Unrestricted Public Domain | Expired copyright or US Government work (NASA, USGS, NIH, CDC). |
| `cc-by` | CC Attribution (2.0, 3.0, 4.0) | Strict attribution string required matching author/institution credit. |
| `cc-by-sa` | CC Attribution-ShareAlike | Display attribution string required. |
| `unsplash` | Unsplash License | Commercial use permitted. Unsplash photographer credit required. |
| `pexels` | Pexels License | Commercial use permitted. Photographer credit required. |
| `pixabay` | Pixabay Content License | Commercial use permitted. Contributor credit required. |

#### Strictly Prohibited Licenses
1. **NonCommercial (`-NC`):** **STRICTLY BANNED.** Spoin is commercial. Using NC material creates direct legal liability.
2. **NoDerivatives (`-ND`):** **STRICTLY BANNED.** Cloudinary crops and resizes images dynamically to fit mobile viewports, creating derivative works.

#### Critical YAML Syntax Gotcha: Colons in Attributions
Attributions frequently contain colons (e.g. `X-ray: NASA/CXC; Optical: NASA/STScI`). In YAML, an unquoted colon followed by a space causes PyYAML to parse the line as a dictionary mapping rather than a string scalar, breaking the manifest parser.
- ❌ `attribution: X-ray: NASA/CXC; Optical: NASA/STScI` *(Crashes parser)*
- ✅ `attribution: "X-ray: NASA/CXC; Optical: NASA/STScI"` *(Clean scalar)*

---

### 2.7 Manifest File Schema & Structure (`images.md`)

Manifests reside at `docs/the_spoin_universe/images/<category>/[<sub_category>/]<subject>/images.md`. There is **no prose body** — only front matter:

```yaml
---
kind: image_manifest
category: astronomy
sub_category: physics
subject: astronomy
images:
  - title: Saturn's Rings Backlit by the Sun
    description: >
      Saturn photographed from inside its own shadow by the Cassini spacecraft, the rings
      illuminated from behind so the finest microscopic dust in the outer E and G rings
      glows brightly through forward scattering. The dense main B ring appears as a broad
      black silhouette blocking solar rays, while the tenuous inner C ring reveals subtle
      translucent banding against the dark disc of the planet.
    source_url: "https://photojournal.jpl.nasa.gov/jpeg/PIA17172.jpg"
    source_page: "https://photojournal.jpl.nasa.gov/catalog/PIA17172"
    licence: public-domain
    attribution: "NASA/JPL-Caltech/Space Science Institute"
    topic_tags:
      - saturn
      - planetary rings
      - cassini
      - scattering
---
```

### 2.8 Manifest Validation Command
Every manifest must be validated via Python before concluding Phase 2:
```powershell
python -c "
import yaml, sys
from pathlib import Path
p = Path('docs/the_spoin_universe/images/<topic_path>/images.md')
data = yaml.safe_load(p.read_text(encoding='utf-8').split('---', 2)[1])
imgs = data.get('images', [])
print(f'YAML Valid: {p.name}')
print(f'Total Sourced Images: {len(imgs)}')
allowlist = {'cc0', 'public-domain', 'cc-by', 'cc-by-sa', 'unsplash', 'pexels', 'pixabay'}
for i, img in enumerate(imgs):
    assert img.get('title'), f'Image {i} missing title'
    assert img.get('description') and len(img['description']) > 100, f'Image {i} description too short'
    assert img.get('source_url'), f'Image {i} missing source_url'
    assert img.get('licence') in allowlist, f'Image {i} invalid licence: {img.get(\"licence\")}'
    assert img.get('attribution'), f'Image {i} missing attribution'
print('All image manifest invariants verified clean!')
"
```

---

---

## 3. Phase 3 — Curriculum: Authored Teaching Structure

### 3.1 The Curriculum Contract
The curriculum file is authored data, not generated text (`docs/the_spoin_universe/curricula/<topic>/curriculum.md`):
- **YAML Front Matter Only:** Leading `---`, YAML block, closing `---`. Nothing but whitespace after (no markdown prose body).
- **Subtopic Level:** `title`, `description`, `prerequisites`.
  - **No `sources` field at subtopic level:** `sources` was dropped and replaced by per-tier `grounding` — one field naming corpus material, not two that can drift.
- **Tier-Level `grounding`:** Every tier explicitly declares its corpus scope:
  ```yaml
  grounding:
    - "astronomy/physics/astronomy/stellar-structure-and-stellar-nucleosynthesis.md#The Four Fundamental Equations of Stellar Structure"
    - "astronomy/physics/astronomy/tips-and-tricks.md#Common Misconceptions: Stellar Optics and Apparent Brightness"
  ```
  - **Format:** `"<path relative to corpus/>#<exact ## heading, verbatim>"`.
  - **Quote Every Ref:** Astronomy's and physics headings are full of colons (`:`) — e.g. `#Common Misconceptions: Stellar Optics`. Unquoted, YAML parses the colon as a dictionary mapping and fails validation.
- **Topic Sizing:** Targets **500–750 cards** across all tiers:
  - Typically 8–12 subtopics in an acyclic DAG.
  - Each subtopic targets **~50–60 cards across 3 tiers** (~16–20 cards per tier).
- **Database Band Invariant:**
  - `target_cards` must satisfy `5 <= target_cards <= 25` per tier.
  - `card_types` quotas must sum exactly to `target_cards`.

### 3.2 Grounding is a Scope, Not a Citation
Every card in a tier is written from passages picked per card, by similarity between that card's brief and the sections on its tier's `grounding` list:
1. **Too Narrow is the Real Failure:** Two sections grounding 20 cards forces 20 cards to be written from the same ~3,000 characters, producing near-duplicates that the downstream quality gate rejects.
2. **Rough Band:** **5–10 sections for a 16–20 card tier.** Fewer only if the material is genuinely that concentrated.
3. **Include Legitimate Scope:** Ranking happens within the scope, so include everything that legitimately teaches this tier.
4. **Tiers Should Differ:** If beginner and advanced cite the same sections, the tier split isn't earning anything. Tiers should have differentiated conceptual depths.
5. **Reuse is Expected:** Foundational sections can ground both beginner and advanced (drawing different cards), or cross subtopics.
6. **Fallback Safety Net:** If the declared scope cannot supply good enough passages, retrieval falls back to an open query across the whole corpus. The generator reports scoped vs. fallback counts per tier — persistent fallbacks signal that the declared scope was too narrow.

### 3.3 The Six Card Types, Quota Mix & Visual Load (The Strict 25–30% Prose Ceiling)

**The Golden Rule of the Feed:** **`prose` is strictly capped at 25–30% of target cards — NEVER more than 30% under any circumstance.** The Spoin feed must never devolve into a wall of text.

All topics across the Spoin Universe allocate tier quotas across exactly **six first-class card types**:

| Card Type | Role & Primary Function | Observational Topics (Tier 1 & 2) | Pure Code & Theory (Tier 3) |
|---|---|---|---|
| **`prose`** | Core conceptual prose explanation | **Strictly 25–30% max** (4–6 cards). Hard ceiling to prevent text walls. | **Strictly 25–30% max** (4–6 cards). Kept tight and punchy. |
| **`image`** | Photographic visual anchor from open-licensed catalog with dense retrieval bait | **12–18% of tier (2–3 cards)**. Sums across all tiers to match the exact count of sourced images in `images.md` (e.g. 76 in Astronomy). | **Strictly 0** (Tier 3 manifests are `images: []`). |
| **`code`** | Syntax-highlighted worked code snippet | **Strictly 0** (non-technical topics; enforced downstream). | **20–25% of tier (4–6 cards)**. Core implementation examples. |
| **`diagram`** | Client-rendered Mermaid SVG (ADR-0067) | **10–15% of tier (2–3 cards)**. Reserved strictly for things photos cannot show (HR tracks, fusion cycles, orbits). | **15–20% of tier (2–4 cards)**. Primary visual anchor for architectures, memory layouts, ASTs. |
| **`comparison`** | Myth vs. Fact, A vs. B, or trade-off matrix (ADR-0017) | **25–30% of tier (4–6 cards)**. Sourced heavily from `tips-and-tricks.md` misconceptions and traps. | **10–15% of tier (2–3 cards)**. Structural and architectural trade-offs. |
| **`ascii`** | Curated single-use ASCII art gag scene (ADR-0079) | **20–25% of tier (3–5 cards)**. Curated humor and shareable viral hooks. | **20–25% of tier (4–5 cards)**. Aggressively breaks up code/text blocks. |

#### Detailed Quota Breakdowns:

1. **For Photographic / Observational Topics (Tier 1: Astronomy, Biology, History; Tier 2: Philosophy, Psychology, Sports):**
   - **`image` (12–18% of tier, 2–3 cards per tier):** Primary photographic visual anchor. Each `image` card attaches a verified photo from the open-licensed catalog (`images.md`), using rich multimodal descriptions (composition, color palette, morphology) as semantic retrieval bait. Quotas sum across all tiers to equal the exact number of cataloged images (e.g. 76 in Astronomy).
   - **`prose` (Strictly 25–30% max, 4–6 cards):** High-density conceptual explanation carrying the core idea. Strictly capped at 30% to prevent text walls.
   - **`comparison` (25–30% of tier, 4–6 cards):** High volume of comparative cards, Myth vs. Fact pairs (❌ / ✅), and operational traps grounded in `tips-and-tricks.md`.
   - **`ascii` (20–25% of tier, 3–5 cards):** Curated single-use ASCII art gag scenes that learners screenshot and share.
   - **`diagram` (10–15% of tier, 2–3 cards):** Client-rendered Mermaid SVGs reserved strictly for mechanisms photographs cannot show (evolutionary HR tracks, CNO/p-p fusion cycles, conic sections, cosmic distance ladder rungs).
   - **`code` (Strictly 0):** Enforced downstream for non-technical topics.

2. **For Pure Code & Theory Topics (Tier 3: Rust, Systems, Backend, GenAI):**
   - **`image` (Strictly 0):** Pure code and theory topics feature empty manifests (`images: []`). Stock photos of keyboards, monitors, and glowing brains are strictly banned.
   - **`diagram` (15–20% of tier, 2–4 cards):** Client-rendered Mermaid diagrams replace photographs as the primary visual anchor for memory layouts, borrow graphs, ASTs, state machines, and protocols.
   - **`prose` (Strictly 25–30% max, 4–6 cards):** Kept tight and punchy.
   - **`code` (20–25% of tier, 4–6 cards):** Worked syntax-highlighted code examples.
   - **`ascii` (20–25% of tier, 4–5 cards):** Aggressively breaks up code/text blocks.
   - **`comparison` (10–15% of tier, 2–3 cards):** Trade-off matrices.

### 3.4 Deep Integration of `tips-and-tricks.md`
`tips-and-tricks.md` is prime pedagogical material — particularly sections titled `Common Misconceptions: …`, observational traps, and practitioner rules of thumb.
- Ground celestial mechanics, optics, stellar evolution, relativity, and cosmology tiers directly in their corresponding misconception chunks.
- These sections supply high-density grounding for `comparison` (Myth vs. Fact) and `prose` cards.

### 3.5 Prerequisites DAG Design
- Prerequisites must reference exact `title` strings of other subtopics in the same file.
- The prerequisite graph must be strictly acyclic.
- Provide multiple root entry points (`prerequisites: []`) so learners can explore tracks concurrently.

### 3.6 Curriculum Validation Command
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
