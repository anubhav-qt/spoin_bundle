# Handoff: Continuing Corpus Authoring for `the_spoin_universe`

> **Written:** 2026-09-05 after authoring World Philosophy, Astronomy, World Mythology, Fullstack Engineering, Frontend Engineering, and Backend Engineering suites.  
> **Status:** 58 curated documents in `docs/the_spoin_universe/corpus/`.  
> **Purpose:** Hand off the corpus generation pipeline to a fresh session with complete operational context, invariants, and instructions.

---

## 1. What Already Exists in the Corpus

The corpus currently holds **58 fully compliant documents** organized by category and scope:

| Directory Path | Subject | Scope | Docs | Notes |
|---|---|---|---|---|
| `docs/the_spoin_universe/corpus/_canon/` | Spoin Product Canon | Canon | 5 | Card anatomy, dual titles, archetypes, ASCII box rules (discard-for-regeneration), quizzes. |
| `docs/the_spoin_universe/corpus/computer-science/software-engineering/backend-engineering/` | Backend Engineering | Survey | 9 | Protocols, APIs, persistence, caching, messaging, concurrency, security, observability, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/computer-science/software-engineering/frontend-engineering/` | Frontend Engineering | Survey | 9 | Rendering path, CSS layout, V8/event loop, reactivity, rendering architectures, web vitals, a11y, client security, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/computer-science/software-engineering/fullstack-engineering/` | Fullstack Engineering | Survey | 8 | End-to-end type safety, auth lifecycle, state sync, BFF/caching, execution boundaries, distributed tracing, zero-downtime migrations, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/mythology/world-mythology/` | World Mythology | Survey | 9 | Comparative archetypes, Mesopotamia, Egypt, Greco-Roman, Norse, Vedic/Hindu, East Asian (Chinese & Shinto), Mesoamerican/Indigenous, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/astronomy/physics/astronomy/` | Astronomy | Survey | 9 | Celestial mechanics, solar system, radiation/instrumentation, stellar structure, stellar evolution/H-R, galactic/ISM, extragalactic/cosmic web, cosmology/distance ladder, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/philosophy/world-philosophy/` | World Philosophy | Survey | 9 | Presocratics/methods, classical Greek (Socrates/Plato/Aristotle), Hellenistic/Late Antique, Eastern traditions, Medieval/Islamic Falsafa, Early Modern epistemology, German Idealism/19th-C critique, 20th-C Analytic/Continental, tips-and-tricks. |

Every document strictly satisfies the database schema contract (`the_spoin_universe.document` and `the_spoin_universe.chunk`):
- `title:` is explicitly declared in YAML front matter on every file (`document.title NOT NULL`).
- `kind: topic_source` includes `category:` and `scope:` (`survey` or `topic`).
- `sub_category:` is included when present, omitted when None.
- Every directory includes a dedicated, mandatory `tips-and-tricks.md`.
- All `##` sections are self-contained without cross-section relative pronouns.
- Prose is fact-dense (80–250 words per concept), dry, and free of jokes or filler in the body.

---

## 2. Essential Documents to Read Before Authoring

1. [`docs/the_spoin_universe/procedure.md`](../the_spoin_universe/procedure.md): **The Authoring Loop.** Follow the 7 phases in exact order (Intake $\to$ Coverage Check $\to$ Research $\to$ Temp Notes $\to$ Curation $\to$ Emission $\to$ Cleanup & Git Commit).
2. [`docs/handoff/antigravity-corpus-authoring.md`](antigravity-corpus-authoring.md): **The Ingestion Contract.** File layout, front matter specifications, and quality invariants.
3. [`.agents/rules/corpus-curation.md`](../../.agents/rules/corpus-curation.md): **Persistent Curation Rules.** Standing behavioral guidelines.
4. [`docs/the_spoin_universe/corpus/README.md`](../the_spoin_universe/corpus/README.md): Current corpus tree and conventions.

---

## 3. Invariants & Hard-Learned Lessons

- **Never Omit `title:` in Front Matter:** `document.title` is a `NOT NULL` database column in `the_spoin_universe`. Every markdown file must begin with:
  ```yaml
  ---
  title: Exact Title of Document
  kind: topic_source
  category: category name
  sub_category: optional sub-category
  scope: survey # or topic
  source: Primary authoritative source
  source_date: YYYY or YYYY-MM-DD
  topic_tags: [tag1, tag2, ...]
  ---
  ```
- **Phase A Intake is Mandatory:** Always run Phase A intake first using the `ask_question` tool, asking:
  1. Category (prioritize existing corpus categories: `computer science`, `mythology`, `astronomy`, then proposed).
  2. Sub-category (or `None`).
  3. Survey vs Topic (broad map of a field vs deep-dive course down to bedrock).
- **Phase B Coverage Check Enables Compositional Reuse:**
  - Before researching, check what existing corpus directories cover.
  - Do **not** re-fetch or re-explain concepts that neighbouring documents already treat well. (e.g. Fullstack Engineering reused protocol and database foundations from Backend, and DOM/rendering concepts from Frontend, needing only one targeted search for W3C Trace Context).
- **Domain-Agnostic Practitioner Wisdom:**
  - Phase C research and Phase F `tips-and-tricks.md` apply to **all** human disciplines (sciences, humanities, trades, philosophy, mathematics), not just software/tech.
  - Cover real-world operational traps, translation distortions, observational blunders, and counter-intuitive edge cases.
- **ASCII Degradation Policy:**
  - If a generated ASCII art diagram exceeds 40 columns or fails parser validation, the card is **discarded entirely for regeneration** (do not degrade to text-only prose).
- **No Waiting for Test Runs:** Keep generating corpus data continuously as instructed by the project owner.
- **Temp Directory Discipline:** Always write raw research to `docs/the_spoin_universe/temp/` (`00-scope.md`, `01-sources.md`, `10-...`). Always wipe `temp/` at the end of the run, leaving only `temp/README.md`.

---

## 4. Suggested Next Subjects

Depending on the project owner's curriculum goals, logical next candidates include:

- **Natural & Physical Sciences:**
  - *Organic Chemistry* (Survey under `science` or `chemistry`)
  - *Quantum Mechanics* (Survey or Topic under `physics`)
  - *Evolutionary Biology & Genetics* (Survey under `biology`)
- **Mathematics:**
  - *Linear Algebra* (Topic or Survey under `mathematics`)
  - *Calculus & Mathematical Analysis* (Survey under `mathematics`)
  - *Probability & Statistics* (Survey under `mathematics`)
- **Computer Science:**
  - *Distributed Systems* (Survey under `computer science / software engineering`)
  - *Operating Systems & Systems Programming* (Survey under `computer science`)
  - *Cryptography & Information Security* (Survey under `computer science`)
- **Humanities & History:**
  - *Classical Philosophy: Presocratics to Hellenistic Schools* (Survey under `philosophy`)
  - *History of the Ancient Silk Road* (Survey under `history`)

---

## 5. The Ready-to-Paste Prompt for the Next Session

```markdown
Continue authoring the source-of-truth corpus for `the_spoin_universe`.

Read in this order before doing anything:
1. `docs/handoff/next-corpus-authoring.md` (your operational brief and current corpus inventory)
2. `docs/the_spoin_universe/procedure.md` (the mandatory 7-phase loop to follow every run)
3. `docs/handoff/antigravity-corpus-authoring.md` (the ingestion contract)

Current state:
The corpus holds 49 documents across 5 suites (_canon, backend-engineering, frontend-engineering, fullstack-engineering, world-mythology, astronomy).
Every document has mandatory `title:` in YAML front matter and a dedicated `tips-and-tricks.md`.

Rules:
- Start each subject with Phase A Intake: use the `ask_question` tool to ask Category, Sub-category, and Survey-vs-Topic.
- Run Phase B Coverage Check before fetching anything to maximize compositional reuse across existing corpus files.
- Research breadth for surveys, depth for topics. Every domain includes a mandatory `tips-and-tricks.md` capturing authentic practitioner/field wisdom (domain-agnostic).
- Write raw notes to `docs/the_spoin_universe/temp/` (`00-scope.md`, `01-sources.md`, etc.).
- Curate dense, dry, self-contained `##` chunks. Never omit `title:` in front matter.
- Wipe `temp/` leaving only `temp/README.md`, commit your changes to git, and report back.

Ask me what subject we are authoring next, or present Phase A intake if I have already provided the subject.
```
