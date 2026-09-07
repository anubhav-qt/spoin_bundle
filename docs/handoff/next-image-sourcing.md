# Handoff: sourcing the image catalog for every existing subject

> Written 2026-09-05. Owner-directed: fill images for all subjects already in the corpus,
> and make the same pass standing procedure for every new one.
>
> **The contract is § 10 of
> [`antigravity-corpus-authoring.md`](antigravity-corpus-authoring.md)** — this document
> does not restate it. What is here is the run: who does what, which subjects, and the
> prompt to hand over.
>
> **Amended 2026-09-07.** The backfill described below — "fill images for all subjects
> already in the corpus" — was a one-off catch-up and is not the standing procedure any
> more. For any topic from here on, images are sourced **after** its curriculum exists and
> **against the `image_needs` that curriculum declares**
> ([ADR-0105](../adr/0105-the-photograph-is-chosen-before-the-card.md), and the sequence in
> [`antigravity-curriculum-authoring.md`](antigravity-curriculum-authoring.md)). The
> per-subject target counts in the table below are therefore a ceiling to plan capacity
> against, never a quota to fill: source what the curriculum asked for, and say plainly
> when a subject cannot supply it.

## What this is

[ADR-0095](../adr/0095-open-licensed-image-catalog.md) adds photographs as a third visual
kind beside ASCII gags and mermaid. [Task 0040](../tasks/0040-open-licensed-image-catalog.md)
is the five-phase build. **This is Phase 1 and only Phase 1**: the manifest contract, and
the sourcing run that fills it.

Nothing downstream exists yet — there is no `image` table, no Cloudinary account, no
`visual_kind` column, no assignment, no renderer. That is deliberate and it is the right
order: ADR-0095 requires the contract to be written *before* images are sourced, because
retrofitting a manifest format after hundreds of entries exist is the expensive mistake
Phase 2 of the corpus avoided.

So the manifests will sit in the repository, valid and unused, until task 0040 Phase 2
ingests them. That is fine. Sourcing is the long-pole human work; the code behind it is a
week that can start any time.

## Ownership

| Track | Owner |
|---|---|
| Sourcing, licence verification, writing the manifests | **Antigravity, supervised by the project owner** |
| The contract, ingestion, Cloudinary, assignment, planner, schema, renderer | implementing session |

Same split as the corpus itself, for the same reason: the judgment about whether a picture
illustrates an idea is research work, not engineering work.

## The subjects

All 16 leaf subjects currently in `docs/the_spoin_universe/corpus/`. The `category` /
`sub_category` / `subject` columns are the front-matter values, not just the path.

| # | category | sub_category | subject | Tier & Target | Visual Scope & Compensation Invariants |
|---|---|---|---|---|---|
| 1 | astronomy | physics | astronomy | **Tier 1: 60–80** | NASA, ESA/Hubble, JWST. Core celestial bodies, deep-sky phenomena, instrumentation (~8–10/chapter). |
| 2 | science | biology | human-biology | **Tier 1: 60–80** | NIH/NLM, Wellcome, CDC PHIL. Primary anatomical systems, micrographs, classical histological plates. |
| 3 | history | — | world-history | **Tier 1: 60–80** | Library of Congress, Europeana, museum open access. Primary artifacts, monumental architecture, historical maps. |
| 4 | mythology | — | world-mythology | **Tier 1: 60–80** | The Met, Rijksmuseum, Getty Open Content, British Library. Classical statuary, temple reliefs, illuminated codices. |
| 5 | philosophy | — | world-philosophy | **Tier 2: 20–35** | Classical busts, primary manuscript folios, academy locations. Abstract dialectics remain unphotographed. |
| 6 | spirituality | vedic-philosophy | bhagavad-gita | **Tier 2: 20–35** | Historical Sanskrit manuscripts (Schøyen, National Museum), classical temple reliefs, traditional iconography. |
| 7 | psychology | — | general-psychology | **Tier 2: 20–35** | Historical apparatus (Wundt lab, Skinner box), standardized illusion plates, neurological imaging. |
| 8 | sports | precision-sport | 10m-air-pistol | **Tier 2: 20–35** | ISSF Olympic competition, match air pistols (Steyr, Walther), mechanical sights, target geometry, stance/grip. |
| 9 | computer-science | game-development | game-development | **Tier 2: 20–35** | Vintage arcade cabinets, milestone console hardware (Odyssey, 2600), PDP-1 Spacewar, dev kits. Zero copyrighted screenshots. |
| 10 | computer-science | programming-languages | rust | **Tier 3: 0 (`images: []`)** | **Pure Code/Theory.** Zero photos. Compensated by dense Mermaid diagrams (lifetimes, borrow graphs, memory layouts). |
| 11 | computer-science | ai-engineering | generative-ai | **Tier 3: 0 (`images: []`)** | **Pure Code/Theory.** Zero photos. Compensated by dense Mermaid diagrams (transformer attention blocks, diffusion latents). |
| 12 | computer-science | ai-engineering | langchain | **Tier 3: 0 (`images: []`)** | **Pure Code/Theory.** Zero photos. Compensated by dense Mermaid diagrams (LCEL runnables, agent tool-calling loops). |
| 13 | computer-science | software-engineering | backend-engineering | **Tier 3: 0 (`images: []`)** | **Pure Code/Theory.** Zero photos. Compensated by dense Mermaid diagrams (distributed consensus, LSM compactions, TCP handshakes). |
| 14 | computer-science | software-engineering | frontend-engineering | **Tier 3: 0 (`images: []`)** | **Pure Code/Theory.** Zero photos. Compensated by dense Mermaid diagrams (DOM render trees, event loops, reactivity graphs). |
| 15 | computer-science | software-engineering | fullstack-engineering | **Tier 3: 0 (`images: []`)** | **Pure Code/Theory.** Zero photos. Compensated by dense Mermaid diagrams (auth flows, client-server sync, API gateways). |
| 16 | computer-science | software-engineering | practically-useful-software-engineering | **Tier 3: 0 (`images: []`)** | **Pure Code/Theory.** Zero photos. Compensated by dense Mermaid diagrams (CI/CD pipelines, git tree branching, rollback strategies). |

**The Tier 3 rows (`images: []`) are intentional and mandatory.** A photograph of a keyboard or stock server illustrates nothing a diagram would not do infinitely better. Recording `images: []` honestly is doing the job right. In exchange, Tier 3 topics require a significantly higher density of Mermaid diagrams within their corpus chunks.

---

## The prompt

Hand this over as written, with the contract attached.

---

You are sourcing the open-licensed image catalog for `the_spoin_universe`, the
source-of-truth corpus behind Spoin. You have already authored the prose corpus for these
subjects; this is the same research, kept rather than discarded.

**Read § 10 "Images: the `images/` manifest" of `docs/handoff/antigravity-corpus-authoring.md`
before sourcing anything.** It is the contract, it is binding, and everything below assumes
you have read it.

**Your deliverable** is one `images.md` manifest per subject, at
`docs/the_spoin_universe/images/<category>/<sub_category>/<subject>/images.md`, mirroring
the corpus tree exactly (omit the `<sub_category>` level for subjects that have none).
Manifest entries only — never image files.

**Work through all 16 subjects** listed in `docs/handoff/next-image-sourcing.md`.

For each subject:

1. **Re-read the subject's corpus documents first.** The images you want are the ones that
   illustrate ideas the corpus actually teaches. A beautiful photograph of something no card
   will ever be written about is wasted work.

2. **Source only from the allowlisted licences:** `cc0`, `public-domain`, `cc-by`,
   `cc-by-sa`, `unsplash`, `pexels`, `pixabay`. Nothing else, ever.
   - **NonCommercial (NC) is excluded** — Spoin is a commercial product.
   - **NoDerivatives (ND) is excluded** — images are served through Cloudinary
     transformations, which produces a derivative work. This one is not a policy choice and
     cannot be waived.
   - If a licence is ambiguous, stated only in site boilerplate, or you cannot verify it on
     the image's own page: **leave the image out and list it in your report.** An image we
     cannot defend in a takedown is worse than no image.
   - **NOAA is public domain unless the caption contains the word "copyright"** — some do.
     Check per image.
   - **Schmidt Ocean Institute is excluded** despite excellent deep-sea imagery: it
     prohibits commercial use.

3. **Start from the gateways, then the specialist archives:** Openverse API (filter
   `license=by,cc0` with commercial-use and modify/adapt enabled — the best programmatic
   entry point), Wikimedia Commons; then NASA / ESA / JWST / USGS / NOAA / NIH / Wellcome /
   BHL for science, and Smithsonian / the Met / Rijksmuseum / Getty Open Content (the
   museum, not Getty Images) / Library of Congress / Europeana / NYPL for art, history and
   mythology. Unsplash, Pexels and Pixabay cover contemporary and everyday subjects that
   museums cannot.

4. **Look at every image with your vision capability before you describe it. This is
   strict.** Load the image and describe what is actually in the frame. Do **not** write
   a description from the caption, the filename, the alt text, the archive's catalogue
   entry, or the search query that surfaced it — those tell you what the image is *filed
   as*, not what it shows, and they are wrong often enough to matter. If you cannot load
   and view an image, leave it out and list it in your report; a guessed description is
   undetectable at review and produces precisely the failure this contract exists to
   prevent. Looking is also how you catch the image that is correctly licensed and
   genuinely on-topic but unusable: watermarked, illegible at card width, or a diagram
   where you expected a photograph.

5. **Write each `description` as the text a card will be matched against, not as a
   caption.** This is the single highest-leverage field in the delivery and the only signal
   retrieval has. Two to four sentences naming what is visible, what is happening, and the
   vocabulary a card about it would use. If your description would be equally true of a
   different photograph of the same subject, it is too vague — rewrite it.

   Good: *"Saturn photographed from inside its own shadow by Cassini, the rings lit from
   behind so the finest dust in the E and G rings glows while the dense B ring reads as a
   dark band."*
   Bad: *"A photo of Saturn."*

6. **`source_url` must point at the image file itself**, not the page it appears on.
   `source_page` is the page, and it is required regardless — it is what a human checks the
   licence against later.

7. **`attribution` is the exact string that will be printed on the card**, and it is
   required even for CC0 and public-domain images, where it is `public domain`. CC BY and
   CC BY-SA make this a legal obligation, not a courtesy.

8. **Follow the Three-Tier Distribution Model:**
   A typical Spoin subject generates **500 to 750 cards**. Sourcing hundreds of images per subject creates cognitive clutter, slows feed rendering, and causes semantic dilution (unrelated cards being assigned loosely-matched images). All subjects follow the generalized three tiers:
   - **Tier 1 (Visually Rich - 60–80 images):** Astronomy, Human Biology, World History, World Mythology. Provides ~1 visual anchor per 7–9 cards (~8–10 per chapter across 7–9 chapters, ~10–15% visual coverage). Source methodically in steady batches of 12–15 images with genuine `view_file` visual inspection.
   - **Tier 2 (Cultural / Artifact - 20–35 images):** World Philosophy, Vedic Philosophy (Gita), General Psychology, 10m Air Pistol, Game Development. Authentic primary physical artifacts only (manuscripts, instruments, equipment). Never pad with generic stock photos.
   - **Tier 3 (Pure Code & Theory - 0 images — `images: []`):** Rust, Generative AI, LangChain, Backend, Frontend, Fullstack, Systems Engineering. Report `images: []` honestly.

9. **Mandatory Mermaid Diagram Compensation for Tier 3:**
   For all pure code and theoretical subjects, zero photographic images are allowed (`images: []`). **In exchange, corpus authors and card generators MUST provide a significantly higher density of client-rendered Mermaid diagrams (` ```mermaid `)** within the corpus chunks.
   - Flowcharts, sequence diagrams, state machines, and data structure layouts (e.g. memory stack/heap, pointer graphs, borrow-checker lifespans, AST transformations, network protocols) must be visually explained using structured Mermaid blocks.
   - Never use ASCII art for technical flowcharts. Technical diagrams are exclusively Mermaid.

10. **Do not resize, crop, edit, or re-host anything.** You commit metadata. The ingester fetches and uploads.

11. **Execute in steady batches:** If expanding a Tier 1 subject toward its target of 60–80 images, execute in batches of 12–15 images. For every single image: verify `HTTP 200 OK` on both `source_url` and `source_page`, download temporarily to `scratch/`, inspect raw pixels with `view_file`, author a 2–4 sentence dense description strictly from visible features, record the manifest entry, and delete the scratch file. Never write bulk scripts to scrape metadata or synthesize descriptions.

**Close the run with a written report:** which subjects you filled and how many entries
each got; every subject you are reporting as having no sourceable imagery (`images: []`), with the reason;
every image you rejected on licence grounds and why; **every image you could not load and
view, which is therefore excluded**; and anything in the contract that
turned out to be wrong or unworkable — say it in the same run rather than working around it
silently.

---

## When this is done

Phase 1 closes. The next thing that has to exist is task 0040 Phase 2 — the `image` table
on frog's alembic chain, manifest ingestion, and the Cloudinary upload. **Phase 2's upload
step blocks on a Cloudinary account, which the owner is creating.** Everything else in
Phase 2 can be built and tested without it.

Do not start Phase 3 (assignment) before there are real cards in `spoin_db_2`: it needs a
similarity floor, and ADR-0095 is explicit that the floor is calibrated against real cards
rather than guessed — the same mistake `card_duplicate_threshold` made and
[task 0042](../tasks/0042-recalibrate-thresholds-against-real-vectors.md) now has to undo.
