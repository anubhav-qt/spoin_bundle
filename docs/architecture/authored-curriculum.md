# The authored curriculum, and cards as the only generated layer

> Design assessment and plan. Written 2026-09-05, **rewritten the same day** after the first
> draft got the premise backwards — it designed an LLM that composes curricula from the
> corpus. The owner authors the curriculum. Only cards and questions are generated.
>
> Not yet an ADR; split into ADRs once the shape is agreed.

## The premise

```
the_spoin_universe    the substrate      knowledge AND its teaching structure, human-authored
        ↓
curriculum            a projection       deterministic, no model
        ↓
cards / questions     generated          grounded in the substrate
        ↓
thinkers              verify             against the substrate
```

The curriculum is **not** generated and **not** a view an LLM composes. It is authored beside
the corpus, by the same hand, and projected into the product database by deterministic code.
The model's entire remaining job is writing cards and questions for a subtopic somebody
already decided should exist.

## 1. Current architecture assessment

**Curriculum generation is an LLM call today, and it is the one high-stakes call with no
corpus context at all.** `generate_curriculum` (`base.py:540`, `langchain_impl.py:1495`)
takes `topic_name`, `description` and `existing_subtopics` — nothing else. Grounding
(ADR-0089) went into five calls: `plan_cards`, `generate_cards`, `correct_cards`,
`verify_cards`, `generate_questions`. Not this one.

Its own docstring calls it *"the highest-stakes call in the system: every card in the topic
inherits its quality."* So today the syllabus is invented from parametric memory, and the
corpus is then asked to support a shape it had no say in. Under the new premise that call
does not need grounding — **it needs deleting.**

**There is no authoring path.** `Subtopic` rows are created only by
`pipeline/persistence.py:133` and the seed fixtures (`seed.py:163`,
`seed_generated.py:124`). `/topics/{id}/curriculum` (`routers/topics.py:160`) is read-only.
Nothing in the system accepts an authored curriculum.

**What the corpus already carries that a curriculum needs:** `document.category` /
`sub_category` (ADR-0091), `DocumentScope` = `survey` | `topic`, `chunk.topic_tags`
normalized by `normalize_topic_text` (ADR-0093), and `corpus_version()`
(`retrieval.py:225`) as a change token. `##` sections are human-authored chunk boundaries,
so a chunk is already a semantic unit rather than a splitter artifact.

**What stays useful from the generated pipeline:** everything downstream of the curriculum.
`plan_cards`, the drafting loop, the two-pass gate, dedup, question generation, the ASCII
fetcher — all of it operates per subtopic-tier and does not care where the subtopic came
from.

## 2. Proposed architecture

```
AUTHORED (human, in git)                    GENERATED (model)
─────────────────────────                   ─────────────────
the_spoin_universe/
  corpus/…            knowledge
  curricula/<topic>/
    curriculum.md     structure  ─┐
                                  │
        ↓ make universe-ingest    │
                                  │
  curriculum tables in            │
  the_spoin_universe              │
                                  │
        ↓ deterministic project   │
                                  │
  Topic + Subtopic rows  ─────────┴──────→  cards + questions per subtopic-tier
  in spoin_db_2                             grounded in the corpus (ADR-0089)
```

A user request no longer triggers curriculum generation. It resolves to an **authored** topic
or it becomes a **curation request**.

```
user requests a topic
      ↓
validate + match (ADR-0025, unchanged)
      ↓
  ┌───┴────────────────────────────┐
  ▼                                ▼
authored curriculum exists    no authored curriculum
  ↓                                ↓
generate cards for its        curation_request row, demand counted
subtopics, grounded           user told it is being prepared
                                   ↓
                              owner authors curriculum + any missing corpus
                                   ↓
                              ingest → project → generation proceeds
```

**Nothing is generated for a topic whose curriculum you did not write.** That is the
strictest reading of "the universe is the substrate", and it is what the owner chose.

## 3. What should change

**A. Delete `generate_curriculum`.** Remove it from `ContentGenerator`, `langchain_impl`,
`fake`, and the prompts. Remove the curriculum branch from `resolve_and_plan_topic`
(`nodes.py:330`) — `topic.curriculum_generated_at` stops meaning "we generated one" and
becomes "a curriculum was projected, at this corpus version".

**B. A curriculum delivery format**, authored beside the corpus and covered by the same
contract discipline: required fields, a closed vocabulary, validated by `--check` with no
network and no model, reporting every problem rather than the first.

**C. Curriculum structure is parsed, not chunked.** It goes into its own tables in
`the_spoin_universe` — **not** into `document`/`chunk`. A curriculum is teaching structure,
not knowledge, and embedding it would put syllabus scaffolding into the retrieval pool where
cards would ground on it. Same instinct as ADR-0096 keeping canon pinned rather than
retrieved.

**D. A deterministic projection into `spoin_db_2`.** Reads the curriculum tables, creates or
reconciles `Topic` and `Subtopic` rows, and is idempotent by content hash the way ingestion
already is. No model call anywhere in it.

**E. Unauthored requests become a demand-ranked curation queue.** A topic requested by four
people outranks one requested by one. This is the signal that tells you what to author next,
and today it is thrown away.

**F. Authored subtopics may name their supporting material.** A subtopic that names the
documents backing it lets card grounding retrieve within that scope rather than guessing from
a query string — a real quality gain, since the human already knows which documents teach it.

## 4. What should NOT change

- **frog stays retrieval infrastructure.** It does not decide what is taught, and it now
  never sees a curriculum decision at all.
- **Card grounding stays exactly as it is** — top 2, no floor, no token budget (ADR-0089 as
  amended). The reasoning holds *more* strongly now: the owner's guarantee that the corpus
  covers a topic before it is live becomes structurally true, because the same person
  authors both.
- **Cross-topic retrieval stays the default** (ADR-0088). Card grounding still reaches across
  the whole universe.
- **Everything downstream of the subtopic is untouched**: `plan_cards`, drafting, the
  two-pass gate, dedup, ASCII fetch, question generation, the quiz ladder.
- **No LLM in the feed read path** (hard rule 1).
- **The corpus ingestion contract** — `##` boundaries, token bound, human curation.
- **`spoin` imports `frog`, never the reverse.**

## 5. V1 implementation plan

**V1.1 — The curriculum contract.** Written before anything is authored, same rule the image
contract follows (ADR-0095): a format retrofitted after twenty curricula exist is expensive.
Draft shape, one file per topic:

```yaml
---
topic: Rust
description: Systems programming with ownership, borrowing and fearless concurrency
is_survey: false
subtopics:
  - title: Ownership & Move Semantics
    description: Why a value has exactly one owner, and what a move costs
    tiers: [beginner, intermediate]
    target_cards: 18
    prerequisites: []
    sources:                          # documents that teach this
      - computer-science/programming-languages/rust/foundations-ownership-borrowing-and-lifetimes.md
  - title: Smart Pointers (Box, Rc, Arc)
    tiers: [intermediate]
    prerequisites: [Ownership & Move Semantics]
    sources: [...]
---
```

**V1.2 — `--check` for curricula.** Pure validation: required fields, tier vocabulary,
`target_cards` inside the 5–25 band the DB already enforces
(`topic.py:269`, `target_cards BETWEEN 5 AND 25`), prerequisites resolving to titles in the
same file, acyclic, and **every `sources` path existing in the corpus**. No network, no
model, no database — so you can run it while authoring.

**V1.3 — Curriculum tables in the universe + ingestion.** Extends `frog/ingest/` rather than
building beside it; its own alembic revision on frog's chain
(`make universe-migration`). Idempotent by content hash.

**V1.4 — The projection.** `spoin_db_2` side: create or update `Topic` and `Subtopic` rows
from the curriculum tables, matched on (topic, title, difficulty). A subtopic dropped from the
file is dropped from the database. There are no users and no production content, so this is a
plain upsert — not a reconciliation. Records `curriculum_corpus_version` so staleness is
computable.

**V1.5 — Delete `generate_curriculum` and rewire the pipeline.** The topic branch now asserts
a projected curriculum exists instead of generating one.

**V1.6 — The curation queue.** `curation_request` rows for unauthored topics, demand-counted
and normalized; a surface listing them by demand.

## 6. Future evolution

Only once V1 has run: **concepts as rows**, so a subtopic references concepts rather than
document paths, and the same concept is reusable across curricula without duplication;
**typed prerequisite edges across topics**, so Quantum Computing can declare a prerequisite on
Linear Algebra's authored subtopics rather than restating them; **claims as rows**
(ADR-0100's own revisit condition), so a card can answer *why does Spoin believe this*.

A **coverage probe** — given a subtopic, what does the universe have for it and at what
depth — is worth building only if authoring at scale makes it useful. It is a convenience for
the author, never a gate: the person writing the curriculum wrote the corpus and already knows
what is in it.

## 7. Required schema changes

**Universe (`the_spoin_universe`), V1:**

```
curriculum                     one per authored topic
  ├─ topic_name, description, is_survey
  ├─ source_path (unique), content_hash, ingested_at
curriculum_subtopic
  ├─ curriculum_id FK, ordinal
  ├─ title, description, tiers[], target_cards
  ├─ prerequisites text[]        titles within this curriculum
  └─ source_paths text[]         documents backing it
```

Deliberately **no** vector column and **no** `chunk` rows — structure is not retrieved (§3C).

**Product (`spoin_db_2`), V1:**

```
topic.curriculum_corpus_version   varchar, nullable
subtopic.source_document_ids      uuid[]   -- authored provenance, cross-DB by value
curation_request                  new table: normalized_name, raw_name, demand_count,
                                  first_requested_at, status
```

`subtopic.source_document_ids` crosses a database boundary by value, exactly as
`card.grounded_chunk_ids` and `chunk.topic_tags` already do (ADR-0088/0089) — so it inherits
the same obligation to tolerate a dangling reference.

## 8. The projection algorithm

```
1. PARSE      curriculum.md → validated structure         (deterministic)
2. VALIDATE   --check: fields, vocabulary, DAG, sources exist
3. INGEST     upsert curriculum tables by content hash    (skip if unchanged)
4. PROJECT    for each curriculum:
                 upsert Topic (canonical_name, description, is_survey)
                 for each subtopic × tier:
                     upsert Subtopic, matched on (topic, title, difficulty)
                     set target_cards, min_cards, source_document_ids
                 subtopics no longer in the file are removed
5. STAMP      topic.curriculum_corpus_version = corpus_version()
```

No model call at any step. The file is the truth and the database follows it — which is what
makes a curriculum editable by editing the file and re-running the projection.

Card generation then runs unchanged against the projected subtopics.

## 9. The curation-request model

Replaces my earlier "knowledge gap" model, which assumed a machine discovering gaps. The
human decides what is missing; the system only reports **demand**.

| State | Meaning |
|---|---|
| `requested` | Users asked; no authored curriculum exists |
| `authoring` | Owner has taken it |
| `authored` | Curriculum exists and has been projected |
| `declined` | Deliberately not in scope |

Ranked by demand count, so the queue answers *what should I author next*. Requests are
normalized by `normalize_topic_text` (ADR-0093) so spellings collapse into one row — which
means the matching machinery (ADR-0025) still earns its place: it decides whether a request
is an existing topic, an alias, or genuinely new.

## 10. Retrieval requirements

**V1 needs no change to frog.** Card grounding already works per subtopic and is unchanged.

The one optional improvement: if an authored subtopic names its `sources`, grounding can pass
those documents as a preference. `search` already takes `exclude_document_ids`; an *include*
filter is its mirror and is a small addition. Worth doing only if scoped grounding measurably
beats today's open query — an open question, since cross-topic retrieval finding an unexpected
supporting passage is a feature, not a leak.

## 11. Failure modes and safeguards

| Failure | Safeguard |
|---|---|
| **Curriculum references a document that moved or was deleted** | `--check` fails when a `sources` path does not exist; `curriculum_corpus_version` makes staleness computable |
| **Prerequisite cycles** | Rejected at `--check`, before ingestion |
| **`target_cards` outside the DB's band** | Caught at `--check` rather than as a constraint violation mid-projection |
| **Authoring becomes the bottleneck** | Real and accepted: this trades marginal cost per topic for control. The demand queue is what keeps the effort pointed at topics people actually want |
| **Two classes of topic** | Avoided by choice — no LLM fallback, so every live topic is authored |

Two failure modes are deliberately absent from that table. **Losing user progress** is not
one — there are no users and no production content; `spoin_db_2` holds one test topic. And
**a subtopic the corpus cannot teach** is not one either: the same person authors the corpus
and the curriculum, in the same tree, so coverage is a fact the author already holds rather
than a condition the system has to detect.

## 12. Implementation tasks, in dependency order

| # | Task | Depends on |
|---|---|---|
| 1 | Curriculum delivery contract + `--check` (pure, no network/model) | — |
| 2 | Curriculum tables in the universe + ingestion, own alembic revision | 1 |
| 3 | Migration: `curriculum_corpus_version`, `subtopic.source_document_ids`, `curation_request` | — |
| 4 | The projection, with reconciliation that preserves progress | 2, 3 |
| 5 | Author one real curriculum (Rust — the corpus already covers it) end to end | 1, 4 |
| 6 | Delete `generate_curriculum`; rewire `resolve_and_plan_topic` | 5 |
| 7 | Curation-request capture + demand-ranked surface | 3, 6 |
| 8 | ADRs, written from what 5 actually showed | 5 |

Task 5 before task 6 on purpose: prove the authored path works on a real topic before
deleting the generated one.

## The distinction

**The universe is the substrate — knowledge and its teaching structure both. The projection
is deterministic. The card is an expression. The model is a worker**, and its work now starts
at a subtopic somebody already decided should exist.
