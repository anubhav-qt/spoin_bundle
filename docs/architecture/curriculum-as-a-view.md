# Curriculum as a view over the universe

> Design assessment and plan, written 2026-09-05. Not yet an ADR — the decisions here
> should be split into ADRs once the owner has agreed the shape.
>
> **Premise:** `the_spoin_universe` is the knowledge substrate. A curriculum is a generated,
> disposable **view** over it. The card is an expression of it. The model is a worker.

## 1. Current architecture assessment

### The finding that shapes everything else

**`generate_curriculum` is the only high-stakes generator call with no corpus context at
all.**

Grounding (ADR-0089, task 0038 Phase 3) was wired into exactly five calls —
`plan_cards`, `generate_cards`, `correct_cards`, `verify_cards`, `generate_questions`
(`langchain_impl.py:1610, 1897, 2026, 2086, 2140`). `generate_curriculum`
(`langchain_impl.py:1495`) builds its prompt from `topic_name`, `description` and
`existing_subtopics` only — its signature (`base.py:540`) has nowhere to put retrieved
knowledge.

Its own docstring calls it *"the highest-stakes call in the system: every card in the topic
inherits its quality."* So today:

```
curriculum   ← invented from parametric memory, no corpus
    ↓
subtopics    ← inherit that shape
    ↓
cards        ← grounded, but against a corpus that never informed the syllabus
```

The corpus is asked to support a curriculum it had no say in. When the model proposes a
subtopic the universe cannot support, nothing detects it — retrieval quietly returns the
two nearest passages (top-2, no floor, ADR-0089 as amended) and the card is drafted from
whatever came back. **A subtopic outside the corpus does not fail; it degrades silently.**
That is the same failure shape ADR-0100 identifies at the claim level, one level up.

### What already exists and is usable

Far more than I expected. This design needs less new machinery than it appears.

| Asset | Where | Why it matters here |
|---|---|---|
| `search_many` with `kinds`, `topic_tags`, `min_score`, `exclude_*` | `frog/retrieval.py:174` | Coverage probing needs no new retrieval primitive — a probe is a query plus a floor |
| `min_score` semantics | `retrieval.py:139` | *"A floor is a quality bar on what came back, not a request for more candidates"*, and an empty list is the honest answer. That is already gap detection's core predicate |
| `DocumentScope` = `survey` \| `topic` | `universe/models.py:66` | Its docstring already says *"retrieval assembling a survey curriculum wants the former; a deep-dive wants the latter"* — written for this, currently unused |
| `chunk.topic_tags`, `document.category` / `sub_category` | `universe/models.py:216, 133` | A coarse concept graph already exists, normalized by `normalize_topic_text` (ADR-0093) |
| `corpus_version(session)` | `retrieval.py:225` | A token that moves whenever the corpus does — exactly the key a recomputable curriculum needs |
| `##` sections as chunk boundaries | ingestion contract | A chunk is already a **human-authored semantic unit**, not a splitter artifact. It is much closer to a "concept" than a naive RAG chunk |
| `topic_edge`, `deep_dive` topics | `domain/models/topic.py` | Cross-topic composition has a persistence shape already |

### What blocks the flywheel today

1. **Curriculum is ungrounded** (above).
2. **Curriculum is generated once and never recomputed.** `topic.curriculum_generated_at`
   gates the call (`nodes.py:330`); once set, an improved corpus can never improve an
   existing topic's curriculum. Curricula are currently permanent, not disposable.
3. **There is no representation of a gap.** When the universe cannot support a subtopic,
   that fact exists nowhere — not in a table, not in a log line, not in the owner's queue.
   The curation flywheel has no input.
4. **`is_survey` is decided by the model, not by coverage.** A topic the corpus covers
   thinly should probably be a survey; that is currently a taste call made without the
   evidence.

## 2. Proposed architecture

```
REQUESTED TOPIC
      ↓
TOPIC UNDERSTANDING          what is this, and what does it decompose into?
      ↓
UNIVERSE RETRIEVAL           probe the whole universe, cross-topic by default
      ↓
COVERAGE ANALYSIS            per candidate area: supported / thin / absent
      ↓
CURRICULUM COMPOSITION       propose a path over what is actually there
      ↓
VALIDATION                   deterministic: every subtopic must cite chunks
      ↓
  ┌───────────────┴───────────────┐
  ▼                               ▼
SUBTOPICS (the view)        KNOWLEDGE GAPS (the curation queue)
  ↓                               ↓
CARDS / QUESTIONS           human curates into the universe
                                  ↓
                            universe grows → curriculum recomputes
```

The division of labour, which is the whole point:

| The universe decides | The model decides |
|---|---|
| What Spoin claims to know | Relevance |
| Which concepts exist | Ordering and progression |
| What relationships hold | Grouping and emphasis |
| What evidence supports a claim | Naming and framing |

The model **proposes** an arrangement. Deterministic code **grounds and validates** it. That
is "LLMs for taste, not structure" applied to the curriculum, and it matches how the
codebase already treats `archetype` (derived, ADR-0017), difficulty (re-rated, not trusted)
and scene reuse (counted server-side, ADR-0080).

## 3. What should change

**A. `generate_curriculum` takes retrieved knowledge.** Its signature grows a coverage
report: the candidate areas the universe can support, each with its evidence. The prompt's
instruction becomes *compose a path over this material*, not *invent a syllabus for this
topic*.

**B. A two-stage curriculum call.** One call cannot both decompose a domain and compose a
path over retrieved evidence, for the reason ADR-0100 gives about single prompts: it will do
whichever it is scored on. So:

1. **Decompose** — the model proposes candidate areas for the topic, from its own knowledge.
   This is deliberately parametric: *what does teaching this subject usually require?* It
   proposes areas, never facts.
2. **Probe** — deterministic. Each candidate area becomes a retrieval query. `search_many`
   answers with hits and scores.
3. **Compose** — the model receives candidates **annotated with what the universe actually
   has** and returns the learning path, ordered by prerequisite, plus the areas it had to
   drop.

Stage 1 is the only place parametric knowledge is allowed, and it is used to decide *what to
look for*, never *what is true*. That is the same posture as an embedding pre-filter feeding
batched topic matching (ADR-0025).

**C. Curricula become recomputable.** `curriculum_generated_at` gains a companion
`curriculum_corpus_version` (from `corpus_version()`). A topic whose curriculum was composed
against an older corpus is *recomputable*, and recomputation is an explicit operation —
never automatic mid-run, because subtopics have user progress hanging off them.

**D. Gaps become first-class rows.** A `knowledge_gap` table in `spoin_db_2`: what was
requested, which topic wanted it, what the probe found, its classification, when. This is
the flywheel's input and the owner's curation queue.

**E. `is_survey` gets evidence.** Coverage breadth and depth are inputs to that decision
rather than pure taste.

## 4. What should NOT change

- **frog stays retrieval infrastructure, never an authority.** It answers "what is near this
  query"; it never decides what is true or what should be taught.
- **The universe stays the source of truth**, and a curriculum never becomes one. A
  curriculum is derived and disposable by construction.
- **Cross-topic retrieval stays the default** (ADR-0088). It is the mechanism that makes
  reuse possible at all — a Quantum Computing request retrieving linear algebra is the
  system working, not leaking.
- **The ingestion contract is untouched.** `##` sections stay chunk boundaries, the token
  bound holds, human curation stays.
- **No LLM anywhere in the feed read path** (hard rule 1). None of this touches serving.
- **The dense authoring style** (ADR-0100).
- **`spoin` imports `frog`, never the reverse** — enforced twice.

## 5. V1 implementation plan

The minimum that produces the flywheel. Deliberately no new tables in the universe and no
concept graph.

**V1.1 — Ground the curriculum call.** `generate_curriculum` accepts a coverage report;
`CURRICULUM_SYSTEM` and its user prompt are rewritten to compose over it. Grounding block
reuses `grounding.render_block`.

**V1.2 — The coverage probe.** A new module, `spoin/generation/coverage.py`: takes candidate
areas, runs `search_many`, classifies each (§9), returns a `CoverageReport`. Deterministic —
no model call, and therefore unit-testable against a real corpus.

**V1.3 — Structural validation.** Every subtopic in the returned curriculum must cite at
least one chunk id that the probe actually returned. A subtopic citing nothing is not a
subtopic; it is a gap the model tried to paper over. Enforced in code and in
`tests/test_architecture.py`, per the enforce-twice rule.

**V1.4 — The gap table and its surface.** `knowledge_gap` rows written by the composition
step; a `/dev` or admin view listing them by frequency. **A gap requested by three topics
matters more than one requested by one** — that ranking is the highest-leverage thing the
flywheel produces.

**V1.5 — Recompute.** `curriculum_corpus_version` on `topic`, plus an explicit recompute
entrypoint. Not automatic.

**What V1 deliberately omits:** concept nodes, prerequisite edges, claim rows, a graph
walker, embeddings of concepts. V1 gets prerequisite ordering from the model, validated
against retrieved evidence — good enough to prove the loop, and it produces the data that
tells us whether the graph is worth building.

## 6. Future semantic-graph evolution

Only after V1 has run enough topics to show where model-proposed ordering is actually wrong.

- **Concepts as rows.** A `concept` table in the universe, each with an embedding, mapped to
  the chunks that teach it. A chunk is already a human-authored semantic unit, so this is
  mostly a labelling exercise, not a re-authoring one.
- **Typed edges.** `prerequisite`, `part_of`, `contrasts_with`, `applies_to`. Prerequisite is
  the only one V1's successor needs; the rest are speculative until something asks for them.
- **frog returns a neighbourhood, not a list.** `search` gains a sibling that expands from
  hits to the concepts around them, so a curriculum request gets a subgraph.
- **Claims as rows** (ADR-0100's own "revisit when"). Then a card can answer *why does Spoin
  believe this*.

The ordering matters: **concepts before claims before edges before neighbourhood retrieval.**
Each step must earn the next with evidence from real runs.

## 7. Required schema changes

**V1, product side (`spoin_db_2`):**

```
topic.curriculum_corpus_version   varchar, nullable   -- corpus_version() at composition
knowledge_gap                     new table
  ├─ requested_area   text          the area the curriculum wanted
  ├─ normalized_area  text          normalize_topic_text, for dedup and counting
  ├─ topic_id         uuid FK       who asked
  ├─ classification   enum          §9
  ├─ best_score       float | null  what the probe's best hit scored
  ├─ probe_query      text          reproducibility
  └─ corpus_version   text          which corpus said this was missing
subtopic.grounded_chunk_ids       uuid[]              -- provenance, mirroring card
```

`grounded_chunk_ids` on `subtopic` matters more than it looks: it is what makes a curriculum
auditable and its staleness computable, and `card.grounded_chunk_ids` already establishes the
pattern and the dangling-reference tolerance (cross-database by value, ADR-0088/0089).

**V1, universe side: none.** Everything the probe needs already exists.

**Future:** `concept`, `concept_chunk`, `concept_edge` in the universe. Their own alembic
revision on frog's chain (`make universe-migration`), never on `spoin_db_2`'s.

## 8. Curriculum-generation algorithm

```
1. DECOMPOSE   (model, parametric, proposes AREAS not facts)
     candidate_areas ← generator.propose_curriculum_areas(topic, description)

2. PROBE       (deterministic, no model)
     for each area:  hits ← frog.search(query(topic, area), k, min_score=floor)
     → CoverageReport: per area, classification + best_score + chunk ids

3. COMPOSE     (model, over evidence)
     draft ← generator.generate_curriculum(topic, coverage_report)
     the report carries, per area, the retrieved material and its verdict

4. VALIDATE    (deterministic, rejects rather than trusts)
     every subtopic cites ≥1 chunk id the probe returned
     every cited id exists
     prerequisite order is acyclic
     dropped areas are recorded as gaps, not silently discarded

5. PERSIST
     subtopics + grounded_chunk_ids + curriculum_corpus_version
     knowledge_gap rows for everything classified insufficient or absent
```

Step 4 is where "trusted for taste, never for constraints" lives. The model may order,
group, name and emphasise. It may not assert that the universe contains something.

## 9. Knowledge-gap model

A gap means **the requested topic needs knowledge the canonical universe does not
sufficiently represent.** It does not mean the model could not find something. Six states,
each with a deterministic predicate:

| State | Predicate | Consequence |
|---|---|---|
| `explicit` | hits above floor, from `scope=topic` documents in the area | Teach at full depth |
| `indirect` | hits above floor, but from adjacent `topic_tags` / another category | Usable; note the reach in provenance |
| `survey_only` | hits above floor, but only from `scope=survey` documents | **Teach at survey depth only.** Do not claim depth the corpus lacks |
| `insufficient` | hits exist but all below floor, or too few to support a tier | Gap row. The dangerous one — this is what silently degrades today |
| `stale` | hits above floor, but `source_date` / version scope fails the area's requirement | Gap row, flagged as refresh not authoring |
| `absent` | no hits above floor at all | Gap row, flagged as new material |

`survey_only` is the state that enforces the owner's quality principle directly: a corpus
holding TCP at survey depth **must not** be used to teach congestion control. The
classification makes that a mechanical outcome, not a judgment the model is trusted to make.

**This is the one place V1 needs a `min_score` floor** — and it is worth being explicit,
because ADR-0089 as amended deliberately removed the floor from *card grounding*, on the
reasoning that the corpus is guaranteed to cover a live topic. That guarantee is exactly
what curriculum composition is testing, so the floor returns here and only here. It is a
coverage predicate, not a retrieval quality knob, and it must be **calibrated against real
vectors before it is trusted** — the same discipline task 0042 exists for.

## 10. Retrieval requirements

V1 needs no new frog capability. It needs:

- **Probe queries per area** — `search_many` batches these into one embedding call.
- **`min_score`** — already implemented, calibration outstanding.
- **`kinds` / `scope` filtering** — `kinds` exists; classification needs `DocumentScope`
  exposed on `Hit`, which is a field, not a feature.
- **Breadth over depth for probing.** A probe asks *does anything here support this*, so it
  wants a wider `k` than card grounding's top-2, and it wants document diversity — five hits
  from one document is weaker evidence than five from five, and the classifier should say so.

That last point is the only genuinely new retrieval concern, and it is a property computed
over hits rather than a change to the search.

## 11. Failure modes and safeguards

| Failure | Why it happens | Safeguard |
|---|---|---|
| **Curriculum shaped by corpus accidents** | The universe's current contents bias what gets taught; a well-covered side topic outranks a central one | Stage 1 decomposes *before* seeing the corpus, so a central area that is absent is recorded as a gap rather than never proposed. This is the whole reason decomposition precedes probing |
| **Reuse becomes shallowness** | Keyword-adjacent material passes as support | Classification is by score, source depth (`scope`) and document diversity — never by name similarity. `survey_only` exists precisely for this |
| **Gap spam** | Every ambitious topic emits dozens of gaps and the queue is noise | Gaps are normalized and counted; the surface ranks by how many topics wanted them |
| **Model invents chunk citations** | It is asked for ids and can fabricate them | Step 4 verifies every id against what the probe returned. Fabrication fails the curriculum, not the check |
| **Recompute destroys progress** | Subtopics carry user progress | Recompute is explicit, never automatic, and must reconcile against existing subtopic rows the way `existing_subtopics` already does |
| **Floor set wrong** | Uncalibrated against real vectors | Calibrate before trusting (task 0042). Too high manufactures gaps; too low restores today's silent degradation |
| **Corpus changes mid-run** | Owner re-ingests while the worker runs | `corpus_version` is already the guard; the curriculum records the version it composed against |

The dominant risk is the first one, and it deserves stating plainly: **a system that composes
curricula from what it already has will, without care, teach what it happens to know rather
than what the subject requires.** Decomposition-before-probing is the structural answer, and
the gap queue is the evidence that it is working — a healthy system produces gaps.

## 12. Implementation tasks, in dependency order

| # | Task | Depends on |
|---|---|---|
| 1 | Calibrate `min_score` against real vectors (extends task 0042 to retrieval) | Real cards/corpus in place |
| 2 | Expose `DocumentScope` and document diversity on `Hit` | — |
| 3 | `coverage.py`: probe + classifier, deterministic, tested against the real corpus | 1, 2 |
| 4 | `propose_curriculum_areas` on `ContentGenerator` (stage 1) | — |
| 5 | Rewrite `generate_curriculum` to compose over a `CoverageReport` (stage 3) | 3, 4 |
| 6 | Structural validation + `test_architecture.py` rule (stage 4) | 5 |
| 7 | Migration: `knowledge_gap`, `topic.curriculum_corpus_version`, `subtopic.grounded_chunk_ids` | — |
| 8 | Persist gaps; rank the curation queue by demand | 6, 7 |
| 9 | Gap surface in `/dev` or admin | 8 |
| 10 | Explicit curriculum recompute, reconciling existing subtopics | 7 |
| 11 | Run a real topic the corpus half-covers; measure reuse and gap quality | 1–8 |
| 12 | ADRs, from what 11 actually showed | 11 |

Task 12 is last on purpose. The decisions here are worth recording, but the numbers from a
real half-covered topic should be in them.

## The distinction this must not lose

**The universe is the substrate. The curriculum is a view. The card is an expression. The
model is a worker.** Everything above is in service of keeping those four separable, so that
improving the substrate improves everything downstream without re-authoring any of it.
