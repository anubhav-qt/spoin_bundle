# Handoff: Authoring 10M Air Pistol Shooting for `the_spoin_universe`

> **Written:** 2026-09-05 after completing the Psychology survey suite (`8c97c1e`).  
> **Status:** 85 curated documents in `docs/the_spoin_universe/corpus/`.  
> **Validator Status:** ✅ **85 ok, 0 failing** against `apps/frog/src/frog/ingest/contract.py`.  
> **Immediate Objective:** Author the **10M Air Pistol Shooting** suite following `docs/the_spoin_universe/procedure.md`.

---

## 1. Current State of the Corpus

The corpus contains **85 documents** across 10 suites:

| Directory Path | Subject | Scope | Docs |
|---|---|---|---|
| `docs/the_spoin_universe/corpus/_canon/` | Spoin Product Canon | Canon | 5 |
| `docs/the_spoin_universe/corpus/computer-science/.../backend-engineering/` | Backend Engineering | Survey | 9 |
| `docs/the_spoin_universe/corpus/computer-science/.../frontend-engineering/` | Frontend Engineering | Survey | 9 |
| `docs/the_spoin_universe/corpus/computer-science/.../fullstack-engineering/` | Fullstack Engineering | Survey | 8 |
| `docs/the_spoin_universe/corpus/mythology/world-mythology/` | World Mythology | Survey | 9 |
| `docs/the_spoin_universe/corpus/astronomy/physics/astronomy/` | Astronomy | Survey | 9 |
| `docs/the_spoin_universe/corpus/philosophy/world-philosophy/` | World Philosophy | Survey | 9 |
| `docs/the_spoin_universe/corpus/science/biology/human-biology/` | Human Biology | Survey | 9 |
| `docs/the_spoin_universe/corpus/history/world-history/` | World History | Survey | 9 |
| `docs/the_spoin_universe/corpus/psychology/general-psychology/` | General Psychology | Survey | 9 |

---

## 2. Ingestion Contract & Validator Invariants (`contract.py`)

The offline ingestion contract validator verifies every document under `docs/the_spoin_universe/corpus/`:
```powershell
$env:PYTHONPATH='apps/frog/src'; python -m frog.ingest --check --corpus docs/the_spoin_universe/corpus
```
Or via python:
```python
import sys; sys.path.insert(0, 'apps/frog/src')
import frog.ingest.__main__
sys.argv = ['frog.ingest', '--check', '--corpus', 'docs/the_spoin_universe/corpus']
frog.ingest.__main__.main()
```

### The Three Machine-Enforced Rules:
1. **Zero Preamble Prose Before First `##` Heading:**
   The markdown body must transition immediately from the closing `---` of the front matter straight into the first `## ` heading. No introductory paragraph, abstract, or summary before `##`.
2. **Hard Section Size Limit: `MAX_SECTION_CHARS <= 2200` (~512 tokens):**
   Every section under a `##` heading is treated as one chunk. If any section exceeds 2,200 characters, the document fails validation.
   - Target range: 1,200 to 1,900 characters per section.
   - Do not compress or delete facts: split dense topics into distinct, descriptive `##` headings.
3. **YAML Front Matter Contract:**
   Must include:
   ```yaml
   ---
   title: Exact Document Title
   kind: topic_source
   category: sports
   sub_category: target-shooting  # or omitted if none
   scope: deep-dive               # or survey
   source: "Author's Work Title, Second Author's Title"
   source_date: 2022              # YYYY, YYYY-MM, or YYYY-MM-DD
   topic_tags:
     - sports
     - shooting sports
     - 10m air pistol
     - issf
   ---
   ```
   *Note:* Any string containing a colon followed by a space must be wrapped in double quotes.

---

## 3. Authoring Guidelines

- **Self-Contained Chunks:** Chunks are retrieved individually alongside chunks from disparate domains. Never use relative cross-references (`"as discussed above"`, `"in the previous section"`, `"the aforementioned method"`). Name the concepts, apparatus, and techniques explicitly every time.
- **High Information Density:** Emphasize mechanical specifications, ISSF rules, physical dynamics, neurological/motor mechanics, and quantitative parameters (e.g. 4.5mm diabolo pellets, 500g minimum trigger pull weight, 11.5mm 10-ring diameter at 10m, SCATT optoelectronic tracing, holding arc oscillations, autonomic regulation).
- **Include `tips-and-tricks.md`:** The final document of the suite must be `tips-and-tricks.md`, covering common diagnostic faults (flinching, anticipation, trigger freeze, holding too long, canting errors), SCATT trace analysis diagnostics, and match-day epistemic/mental pitfalls.

---

## 4. Next Session Intake & Topic Scope

- **Topic:** 10M Air Pistol Shooting (ISSF Olympic 10-meter air pistol)
- **Proposed Path:** `docs/the_spoin_universe/corpus/sports/target-shooting/10m-air-pistol/` (or `docs/the_spoin_universe/corpus/sports/olympic-shooting/10m-air-pistol/`)
- **Recommended Taxonomy:**
  - Category: `sports`
  - Sub-Category: `target-shooting`
  - Scope: `deep-dive`
- **Core Curricular Modules to Cover:**
  1. Pneumatic mechanics, anatomy of competition air pistols, regulators, barrel harmonics, sights, and 4.5mm match pellets.
  2. Biomechanics: Stance, center of mass, skeletal support, foot placement, natural point of aim (NPOA), grip geometry, and head position.
  3. The Holding Arc, sight alignment, sight picture, optical depth of field, and aperture geometry.
  4. Trigger mechanics: First stage take-up, the wall, trigger break, follow-through, and finger placement kinematics.
  5. The Shot Process: Pre-shot routine, breathing cycle, lift, settling, sight picture verification, trigger release, call of the shot, and recovery.
  6. Neuromotor and physiological control: Heart rate deceleration, respiratory sinus arrhythmia, tremorgenic oscillations, and vision stability.
  7. ISSF Competition Rules and Match Formats: Qualification round (60 shots in 75 min), electronic scoring targets (EST / decimal scoring), finals elimination format, and equipment inspection rules.
  8. Training periodization, physical conditioning, dry-fire protocols, and optoelectronic diagnostics (SCATT trace interpretation).
  9. `tips-and-tricks.md`: Diagnostic errors (jerking, snatching, milking the grip), mental traps, match pressure management, and wind/light adaptation.
