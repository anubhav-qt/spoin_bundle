# Handoff: Continuing Corpus Authoring for `the_spoin_universe`

> **Written:** 2026-09-05 after authoring Human Biology, World Philosophy, Astronomy, World Mythology, Fullstack Engineering, Frontend Engineering, and Backend Engineering suites.  
> **Status:** 67 curated documents in `docs/the_spoin_universe/corpus/`.  
> **Validator Status:** ✅ **67 ok, 0 failing** against the machine ingestion contract
> (`apps/frog/src/frog/ingest/contract.py`). Was 8 ok / 59 failing when the validator
> first ran; the retrofit landed in `de3eac5`.  
> **Immediate Priority:** continue authoring. Run `make corpus-check` at the end of every
> run and keep it at 0 failing — the two rules that caused the retrofit (nothing before
> the first `##`; no section over 2,200 characters) are hard errors, and they apply to
> new documents exactly as they applied to the old ones.

---

## 1. What Already Exists in the Corpus

The corpus currently holds **67 documents** organized across 8 suites:

| Directory Path | Subject | Scope | Docs | Notes |
|---|---|---|---|---|
| `docs/the_spoin_universe/corpus/_canon/` | Spoin Product Canon | Canon | 5 | Card anatomy, dual titles, archetypes, ASCII box rules (discard-for-regeneration), quizzes. |
| `docs/the_spoin_universe/corpus/computer-science/software-engineering/backend-engineering/` | Backend Engineering | Survey | 9 | Protocols, APIs, persistence, caching, messaging, concurrency, security, observability, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/computer-science/software-engineering/frontend-engineering/` | Frontend Engineering | Survey | 9 | Rendering path, CSS layout, V8/event loop, reactivity, rendering architectures, web vitals, a11y, client security, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/computer-science/software-engineering/fullstack-engineering/` | Fullstack Engineering | Survey | 8 | End-to-end type safety, auth lifecycle, state sync, BFF/caching, execution boundaries, distributed tracing, zero-downtime migrations, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/mythology/world-mythology/` | World Mythology | Survey | 9 | Comparative archetypes, Mesopotamia, Egypt, Greco-Roman, Norse, Vedic/Hindu, East Asian (Chinese & Shinto), Mesoamerican/Indigenous, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/astronomy/physics/astronomy/` | Astronomy | Survey | 9 | Celestial mechanics, solar system, radiation/instrumentation, stellar structure, stellar evolution/H-R, galactic/ISM, extragalactic/cosmic web, cosmology/distance ladder, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/philosophy/world-philosophy/` | World Philosophy | Survey | 9 | Presocratics/methods, classical Greek (Socrates/Plato/Aristotle), Hellenistic/Late Antique, Eastern traditions, Medieval/Islamic Falsafa, Early Modern epistemology, German Idealism/19th-C critique, 20th-C Analytic/Continental, tips-and-tricks. |
| `docs/the_spoin_universe/corpus/science/biology/human-biology/` | Human Biology | Survey | 9 | Cellular bioenergetics, genetics/epigenetics, neurobiology & brain, cardiovascular, respiratory, immunology, endocrinology, digestive/renal, tips-and-tricks. |

---

## 2. The Ingestion Contract & Validator Invariants (`contract.py`)

The ingester validates all documents against `apps/frog/src/frog/ingest/contract.py` before embedding. Run validation offline via:
```bash
python -m frog.ingest --check --corpus docs/the_spoin_universe/corpus
# Or via make / PowerShell:
make corpus-check
.\make.ps1 corpus-check
```

### The Three Hard Validator Rules:
1. **⚠️ Nothing Before the First `##` (No Preamble Prose):**
   - *Rule:* The body must transition immediately from YAML front matter (or optional single `# H1` title line) straight into the first `## Heading`.
   - *Failure Mode:* Any prose paragraph between `---` / `# Title` and the first `##` raises a hard validation failure (`characters of prose before the first '##' heading`).
   - *Remedy:* Delete general introductory framing paragraphs entirely, or convert real facts into their own distinct `##` section.
2. **⚠️ Maximum Section Size: 2,200 Characters (~512 Tokens):**
   - *Rule:* One `##` section = one chunk. No automated recursive sub-splitter exists. Any section exceeding **2,200 characters** raises a hard failure.
   - *Remedy:* Do not compress. Split over-long sections into two or more focused, self-contained `##` headings. Each section must cover exactly one coherent conceptual idea.
3. **⚠️ Valid YAML Front Matter (Quote Colons):**
   - *Rule:* Any front-matter string containing a colon followed by a space (e.g. `source: "Author: Title (ed.)"`) must be enclosed in double quotes.

---

## 3. How to Write for the Chunker

- **One Idea per Section:** A section covering two ideas produces an embedding vector that is the muddy average of both, degrading retrieval ranking.
- **Informative Headings:** Headings are embedded directly into the chunk's contextual prefix (`Document Title — Section Heading`). Use descriptive headings (`## What REPEATABLE READ Actually Guarantees`), never vague generic markers (`## Overview`, `## Details`, `## Part 2`).
- **Front-Load Specifics:** The opening sentences carry the heaviest retrieval weight. Lead with concrete mechanisms, numbers, or rules, not rhetorical windups.
- **Strict Self-Containment:** Chunks are retrieved in isolation alongside chunks from other documents. Never use relative cross-references (`"as mentioned above"`, `"as we saw in the previous section"`, `"this demonstrates"`). Restate the noun directly.
- **Define Local Terms:** Define unfamiliar domain terms within the section that uses them, never in an introductory glossary chunk.

---

## 4. Current Audit Breakdown (60 Oversized Sections across 59 Failing Files)

```
Batch Breakdown of Oversized Sections (> 2,200 chars):
- science/biology/human-biology/: 38 sections over limit
- mythology/world-mythology/: 8 sections over limit
- computer-science/.../backend-engineering/: 7 sections over limit
- philosophy/world-philosophy/: 7 sections over limit
- All other batches: 0 oversized sections (only preamble prose cleanup needed)
```

---

## 5. The Ready-to-Paste Prompt for the Next Session

```markdown
You are authoring and maintaining the source-of-truth corpus for `the_spoin_universe`.

### Immediate Objective:
Run the offline validator and retrofit all 59 failing documents to achieve 100% compliance (67 ok, 0 failing):
```bash
python -m frog.ingest --check --corpus docs/the_spoin_universe/corpus
```

### The Three Mandates to Enforce:
1. **Wipe all preamble prose before the first `##` heading:**
   Every document must transition directly from front matter (and optional `# H1`) into the first `##` section. Delete introductory framing paragraphs.
2. **Split all sections exceeding 2,200 characters:**
   Do not compress. Split oversized sections into two or more distinct, self-contained `##` sections (one idea per section).
3. **Quote front-matter values containing colons:**
   Ensure valid YAML in `science/biology/human-biology/respiratory-physiology-and-gas-exchange.md`.

### Verification Step:
Run `python -m frog.ingest --check --corpus docs/the_spoin_universe/corpus`.
Do not stop until the output prints:
`checked 67 documents: 67 ok, 0 failing`

### After Reaching 67 ok, 0 failing:
Commit the fixes to git, report the clean audit, and run Phase A Intake for the next topic.
```
