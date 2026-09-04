# Handoff: authoring `the_spoin_universe`

> **Audience:** Antigravity, supervised by the project owner.
> **Written:** 2026-09-04, after task 0038's Phase 1 landed.
> **Status:** this is the ingestion contract, v1. Phase 2 builds the ingester
> *against this document* — so if a field here turns out to be wrong, say so before
> the corpus is large, not after.
>
> **Companion doc:** [`docs/the_spoin_universe/procedure.md`](../the_spoin_universe/procedure.md)
> is the *procedure* — the phases you run, in order, every time the owner hands you a
> subject. This document is the *contract* — what the files must contain and why.
> Read this one once; read that one every run.

You are authoring the source-of-truth corpus that Spoin's card generator will be
grounded in. This document tells you what the corpus is for, what shape it has to
arrive in, and — most importantly — what makes a bad corpus worse than no corpus.

Nothing here asks you to write code. The ingester, the retriever and the generator
are somebody else's track. **Your deliverable is content in a specified format.**

---

## 1. What Spoin is, in enough detail to write for it

Spoin teaches technical topics through a swipeable feed of **cards**. A card is a
small, self-contained explanation of one idea. Cards are grouped into **subtopics**,
subtopics into **topics**, and progression through a topic is **quiz-gated** — you
answer questions about what you just read before the next tier unlocks
([ADR-0009](../adr/0009-quiz-gated-progression.md)).

Two facts about the architecture matter to you:

**Cards are generated once and served to everyone.** There is no per-user
generation. Personalization is ranking over a shared corpus. So a card's quality is
not a per-user concern — a bad card is bad for every reader who ever sees it.

**The product's claim is quiz-gated mastery of _true things_.** Not "plausible
things", not "things an LLM believed". That claim is the reason your track exists.

Read [`docs/architecture/content-model.md`](../architecture/content-model.md) for
what a card actually contains. It is the highest-leverage document in the repo and
you should not author canon without it.

---

## 2. Why the corpus exists

Today the card writer drafts from the model's own parametric memory, and a
verification pass checks the result *after the fact*
([ADR-0030](../adr/0030-two-pass-quality-gate.md)). The truth guarantee is entirely
post-hoc.

That was survivable while the drafting model was large. It is not survivable now:
drafting is moving to `ministral-3b`/`8b`, which have materially weaker factual
recall. A 3B model asked to *recall* the isolation semantics of `REPEATABLE READ`
will produce something confident and possibly wrong. The same model asked to
*restate* a passage it has been handed will do it accurately.

**That is the entire job of your corpus: turn recall into restatement.**

Retrieval is cross-topic by default, and **both the writer and the verifier retrieve
from the same corpus**. Your material is not a hint to one model; it is the shared
ground truth two models argue against.

---

## 3. ⚠️ The one thing to internalise before writing anything

**The corpus is the ceiling on card quality, and a wrong corpus is worse than no
corpus.**

If a chunk states something false, three things happen at once:

1. The writer produces a confidently wrong card.
2. The verifier, retrieving the *same* chunk, agrees with it.
3. The card ships looking **sourced**, which is more credible than a guess.

A thin corpus is the milder version of the same failure: the writer falls back to
parametric recall on a small model, which is the situation we are trying to leave.

Practical consequence: **it is better to deliver ten dense, correct documents than a
hundred hedged ones.** Coverage is a nice-to-have. Correctness is the product.
If you are unsure about a claim, leave it out or flag it to the owner — do not
soften it into something vague, because vague-but-sourced is the worst outcome of
all: it passes the gate and teaches nothing.

---

## 4. The two content kinds

They are not interchangeable, and the ingester stores the distinction as a real
enum column so it can retrieve them differently.

### `spoin_canon` — how the product itself works

**Purpose:** a small model does not know our conventions. Left alone it writes
generic tutorial prose. This is the material that makes it write *on-spec*.

Largely distillable from what is already in this repo — `CLAUDE.md`,
`content-model.md`, and the ADRs. Your job is to turn those into dense, retrievable
prose, not to invent new rules. Where an ADR and this list disagree, the ADR wins;
tell the owner.

What canon needs to cover, at minimum:

| Topic | Source |
|---|---|
| What a card is; its fields and their meaning | [content-model.md](../architecture/content-model.md) |
| Dual titles — why a card has two, and what each is for | [ADR-0022](../adr/0022-dual-titles.md) |
| Card archetypes, and why `archetype` is *derived*, never requested | [ADR-0017](../adr/0017-card-archetypes.md) |
| Quiz-gated progression, and what a good question looks like | [ADR-0009](../adr/0009-quiz-gated-progression.md) |
| How the feed scrolls; what makes a hook stop a scroll | [ADR-0010](../adr/0010-feed-serving.md) |
| The ASCII scene library, and that it is **gags only** | [ADR-0021](../adr/0021-ascii-scene-library.md), [ADR-0079](../adr/0079-ascii-library-is-gags-only.md), [ADR-0080](../adr/0080-ascii-fetcher-node.md) |
| **The ASCII box rule** — art is a rigid box; nothing edited inside it, nothing inserted to its left, captions only top/bottom/appended-right, total width ≤ 40. **Failure drops the card for regeneration, never degrades to broken art or text-only prose.** | [ADR-0021](../adr/0021-ascii-scene-library.md), [ADR-0068](../adr/0068-curated-ascii-art-library-and-worked-few-shot-generator.md), `corpus/_canon/ascii-box-rule-and-gag-scenes.md` |
| Diagrams are mermaid, rendered client-side | [ADR-0067](../adr/0067-mermaid-diagrams-and-form-free-ascii.md) |
| **Silliness lives in the hook layer — title, summary, ASCII art. Never in `body`.** | `CLAUDE.md` |
| Difficulty tiers, and that difficulty is re-rated server-side rather than self-reported | [content-model.md](../architecture/content-model.md) |

The ASCII box rule is enforced by server-side validation: any line exceeding 40 columns
or containing invalid syntax discards the card entirely so it can be regenerated with
proper visual art.

### `topic_source` — authoritative material per topic

**Purpose:** the facts a card is built from.

- **Curated, short, dense.** Assume a chunk of yours will be dropped into a prompt
  next to five others and a token budget. Every sentence competes for space.
- **Authoritative.** Prefer primary sources: specifications, official documentation,
  papers, reference implementations. A blog post that summarises a spec is a worse
  source than the spec.
- **Concrete over general.** "Postgres' `REPEATABLE READ` prevents non-repeatable
  reads but permits phantom reads in the SQL standard; Postgres' implementation also
  prevents phantoms" is useful. "Isolation levels trade consistency for performance"
  is not — the model already knows that, and it displaces something it doesn't.
- **Include the exact things models get wrong**: version-specific behaviour, numbers,
  defaults, names that changed, the edge case everyone misstates. This is the highest
  value-per-token material you can write.
- **Mandatory `tips-and-tricks.md`:** Every subject (topic or survey) includes a dedicated
  file capturing field tips, subtle pitfalls, counter-intuitive nuances, and lessons
  learned from experienced practitioners, community discussions (StackExchange, Reddit),
  and real-world postmortems.

---

## 5. Delivery format

### Layout

```
docs/the_spoin_universe/corpus/
  <category>/
    <sub_category>/          omit this level entirely when there is none
      <survey-or-topic>/
        <document>.md
```

For example:

```
docs/the_spoin_universe/corpus/
  computer-science/
    databases/
      postgresql/
        mvcc-and-isolation.md
        tips-and-tricks.md
  science/
    physics/
      thermodynamics/
        entropy.md
        tips-and-tricks.md
```

Spoin canon — how the product itself works — sits outside the subject hierarchy,
since it is about Spoin rather than about a field:

```
docs/the_spoin_universe/corpus/
  _canon/
    card-anatomy.md
    dual-titles.md
    ascii-box-rule.md
```

The directory is organisational convenience for humans. **The `kind` in front matter
is authoritative**, not the folder — the ingester reads the field, not the path. Keep
them consistent anyway; a mismatch is a review signal that something is misfiled.

### File format

UTF-8 Markdown with YAML front matter.

```markdown
---
title: MVCC and transaction isolation in PostgreSQL
kind: topic_source
category: computer science
sub_category: databases
scope: topic
source: https://www.postgresql.org/docs/17/mvcc.html
source_date: 2026-08-01
topic_tags:
  - postgresql
  - databases
  - transactions
---

## Snapshot isolation

PostgreSQL implements ... (dense prose here)

## What `REPEATABLE READ` actually guarantees

...
```

| Field | Required | Notes |
|---|---|---|
| `title` | **yes** | Human-readable. Shown when a card cites this. |
| `kind` | **yes** | Exactly `spoin_canon` or `topic_source`. A typo is a hard error, not a silent third kind. |
| `category` | **yes** for `topic_source` | Where the subject sits — agreed with the owner at intake, not chosen unilaterally. Stored as `document.category` ([ADR-0091](../adr/0091-corpus-category-hierarchy.md)) and normalized on ingestion. Omit for `spoin_canon`. |
| `sub_category` | no | Omit the field entirely when the subject has none — its absence is a statement, not missing data. |
| `scope` | **yes** for `topic_source` | `survey` or `topic`. A survey is a tour of a field that emits `deep_dive` links; a topic is an exhaustive course on one subject ([ADR-0007](../adr/0007-curriculum-driven-generation.md)). It changes what you research, not just how it is filed. |
| `source` | **yes** | URL, or an origin description for canon (e.g. `Spoin ADR-0022`). This is what a card cites. |
| `source_date` | no | When the **source material** is from — not when you wrote the file. Lets a card cite material that later goes stale. Omit for canon. **Accepted forms: `YYYY-MM-DD`, `YYYY-MM`, `YYYY`** — shorter ones widen to the first of the period. Prefer a full date where the source has one; a bare year is right when it genuinely does not (accumulated practitioner experience, a forum thread, a body of postmortems). Anything else is a hard error. |
| `topic_tags` | **yes** for `topic_source`, optional for `spoin_canon` | See below. |

Two fields you do **not** write: `source_path` (the ingester derives it from the file's
path in the delivery) and `content_hash` (computed). Both are how re-ingestion stays
idempotent.

### Topic tags

Tags are normalized before storage: lowercased, every non-alphanumeric character
becomes a space, runs of whitespace collapse to one. So `PostgreSQL`, `postgresql`
and `Postgre-SQL` all become `postgresql`; `Distributed Systems` becomes
`distributed systems`.

Write them naturally — normalization handles the rest. Just be **consistent in
meaning**: prefer the name a reader would use for the topic, not an abbreviation
(`kubernetes`, not `k8s`).

Tags are a filter that is deliberately **off by default** — retrieval is cross-topic,
so a PostgreSQL card may legitimately ground itself in your distributed-systems
material. Tag for what a document *is about*, not for where you want it retrieved.

### How documents are chunked

**You do not chunk. The ingester does — and it does exactly one thing: one `##` section
becomes one chunk.** There is no splitter, no merger, and no cleverness. Your `##`
headings *are* the chunk boundaries, so the document structure you write is the
retrieval unit the model gets, one-to-one.

That is a deliberate choice: a section boundary is your judgment about where one idea
ends, and a recursive splitter would overrule it with machinery that has read less of
the material than you have. But it makes the shape of your document load-bearing in a
way it would not otherwise be, and two of the rules below are enforced rather than
suggested because of it.

**Write each section as though it were the only thing a model will see about your
subject — because it is.** A chunk is retrieved and pasted into a prompt beside five
chunks from other documents, with no title page, no neighbours, and no way to look
anything up.

#### The rules

- **Write in sections with `##` headings.** A section is the chunk.
- **⚠️ Nothing but an optional `# H1` may appear before the first `##`. Hard error** —
  the document does not ingest at all. An intro paragraph belongs to no section, so it
  would be either dropped silently or glued onto a chunk it does not describe. If the
  framing carries a real fact, give it its own `##`; usually it is general context the
  model already has, and the right move is to delete it.
- **⚠️ A section must be under 2,200 characters (~512 tokens). Hard error.** Nothing
  splits an over-long section for you — it becomes one enormous chunk that wins a
  retrieval slot and then spends a third of the prompt budget on material only partly
  about the query. If a section is too long it is almost always two ideas wearing one
  heading: split it into two `##` sections, each self-contained. **Aim for 1,000–2,000
  characters** — the corpus currently averages ~1,550, which is a good size.
- **One idea per section.** This is the same rule as the length limit, stated the way
  that actually helps. A section covering two ideas gets *one* vector that is the
  average of both — so it ranks mediocre for each and may be retrieved for neither.
  Two focused sections beat one thorough one, every time.
- **Make each section self-contained.** "As mentioned above", "as we saw", "in the next
  section", "this" referring to the previous heading — all arrive meaningless. Re-state
  the antecedent instead of pointing at it.
- **Define an unfamiliar term in the section that uses it**, not once at the top of the
  file. The top of the file is a different chunk, and it may not be retrieved.
- **Headings are read by the model, so make them descriptive.** They go into every
  chunk's header (below) and into the vector. `## What REPEATABLE READ actually
  guarantees` is a heading; `## Overview`, `## Part 2`, `## Details` and `## More` are
  not — they say nothing about the content and actively make the chunk harder to find.
- **Front-load the specifics.** The first sentence or two carry the most weight in the
  vector. Open with the concrete claim, not with a windup.
- **Quote any front-matter value containing a colon.** `source: West's Respiratory
  Physiology: The Essentials` is invalid YAML and fails the document; write
  `source: "West's Respiratory Physiology: The Essentials"`.

#### On reading level — write for precision, not for the beginner

It is tempting to write the corpus in easy language, since Spoin's readers are learning.
**Don't.** The reader never sees your documents; they see *cards*, generated from your
material and pitched at a difficulty tier. **Reading level is the generator's job, not
yours** (owner's decision, 2026-09-05).

Three reasons this is not negotiable:

1. **One corpus grounds all three tiers.** `difficulty` is a property of the card —
   beginner, intermediate, advanced — and the same chunk of yours must ground a beginner
   card *and* an advanced one on the same subject. Material written at beginner level
   leaves the advanced tier nothing to draw on, so softening the corpus caps the ceiling
   for every tier at once.
2. **Precision that is never written down cannot be recovered.** Your whole job is
   turning *recall* into *restatement*. The exact defaults, the version-specific
   behaviour, the boundary condition everyone misstates — that is the highest
   value-per-token material you can write, and it is the first thing lost when prose is
   simplified.
3. **The verifier retrieves the same chunks.** A softened passage leaves the gate without
   the precision it needs to check a claim, which turns a check against a source back
   into a disagreement between two models — the exact failure
   [ADR-0089](../adr/0089-retrieval-grounded-generation.md) exists to prevent.

What you owe the reader is not simpler language but **self-contained** language: use the
precise term, and define it in the section that uses it. "`REPEATABLE READ` prevents
non-repeatable reads — a row re-read within one transaction cannot have changed — but
the SQL standard still permits phantom reads" is exact *and* learnable. "Isolation levels
trade consistency for performance" is neither: vague, and it teaches nothing the model
did not already know.

So keep the real numbers, the real names and the edge cases. Cut jargon that is only an
insider's shortcut; define jargon that is load-bearing. Making it approachable is
downstream of you. Making it **true and precise** is yours, and nothing downstream can
do it for you.

#### What the ingester adds for you

Every chunk is stored and embedded with a *contextual header* built from the document
title and the section heading:

```
MVCC and transaction isolation in PostgreSQL — Snapshot isolation

PostgreSQL implements ...
```

You do not write this. Two things follow for you: your `title` is read by a model on
**every single chunk** of that document, so make it descriptive rather than clever; and
you need not repeat the subject in each section's opening sentence, because the header
already says it.

---

## 6. Revising the corpus

**Assume you will deliver this many times.** Ingestion is idempotent: a document's
identity is its path in the delivery, and change is detected by hashing the file.
Re-ingesting an unchanged document does nothing; re-ingesting a changed one replaces
its chunks.

The practical rules that fall out of that:

- **Paths are identity — keep them stable.** Renaming a file is, to the ingester, a
  deletion plus a new document. Fine occasionally, but don't reorganise casually.
- **Edit in place.** Do not create `mvcc-v2.md` next to `mvcc.md`; both will be
  ingested and retrieval will return whichever it likes, including the stale one.
- There is no version field to bump, and that is deliberate — a version bump can be
  forgotten and its failure mode is stale chunks silently surviving a revision. A
  hash cannot be forgotten.

---

## 7. What not to do

- **Do not invent facts to fill a gap.** An absent chunk makes the model fall back on
  its own knowledge, which is the status quo. A wrong chunk actively poisons both the
  writer and the verifier.
- **Do not write marketing prose or hype.** It occupies a token budget and grounds
  nothing.
- **Do not be funny in `topic_source` material.** Spoin's silliness lives in the hook
  layer — title, summary, ASCII art — and never in the explanation someone is tested
  on. A joke in your source material becomes a joke in a card's `body`, where it
  undermines the gate checks that read `body` as meaning.
- **Do not summarise what the model already knows well.** General framing is the
  cheapest thing a model produces; it does not need retrieval to say it.
- **Do not copy material you do not have the right to reproduce.** Cite it and
  restate it in your own words instead. Cards will be shown to real users.

---

## 8. What is still open

Honest list, so nothing here reads as more settled than it is:

- ~~**Chunking strategy** is Phase 2 and not yet built.~~ **Built (2026-09-05).** It is
  section-level, as intended: one `##` section, one chunk, in document order, no
  sub-splitter. Three things follow for you, all written into §5 above: **nothing before
  the first `##`** and **nothing over 2,200 characters** are hard errors, and every chunk
  carries an automatic **contextual header** built from your `title`.

  Worth knowing why the size limit is enforced rather than suggested: when the corpus was
  measured with the real `Qwen3-Embedding-0.6B` tokenizer, **17% of sections were over
  512 tokens** and the largest was 1,385 — against an earlier estimate of ~4%, which was
  wrong. A guideline was not holding, and the section size is what makes "no sub-splitter"
  a safe design rather than a liability.
- ~~**The front matter may gain fields** in Phase 2 as the ingester is written.~~ **It
  gained none.** Every field in §5 is the field the ingester reads, and nothing was
  removed. `source_date` gained *accepted forms* rather than a new field.
- **`category`, `sub_category` and `scope` are corpus-side only.** They are real
  columns on `document` ([ADR-0091](../adr/0091-corpus-category-hierarchy.md)), but
  nothing in the product database has them. A database CHECK makes `category` and
  `scope` mandatory for `topic_source` and optional for `spoin_canon`, so a canon
  document with no category is correct, not incomplete.
- **`author` and `licence` were deliberately dropped** from the schema
  ([ADR-0088](../adr/0088-the-spoin-universe.md)). If you find yourself needing to
  record either, that is a real signal — raise it rather than smuggling it into
  `source`.
- **The ASCII box rule's enforcement mechanism** is an open decision for the owner.
  Until it is made, canon quality is the mitigation.

## 9. Checking your work before you hand it over

The ingester's validator runs standalone. It needs no GPU, no database and no model, and
it reports **every** problem in **every** failing document rather than stopping at the
first:

```bash
make corpus-check
```

Ask the owner to run it at the end of a delivery. A run ends with a line like
`checked 67 documents: 67 ok, 0 failing`, and each failure names the file and the field:

```
FAIL mythology/world-mythology/tips-and-tricks.md
  - 374 characters of prose before the first `##` heading ('The comparative study...'...)
```

This is the contract made executable. Where this document and the validator disagree,
**say so** — one of them is wrong and it matters which.

## Where to read further

| | |
|---|---|
| The mental model everything assumes | [`docs/architecture/overview.md`](../architecture/overview.md) |
| What a card, subtopic and question are | [`docs/architecture/content-model.md`](../architecture/content-model.md) |
| Why the corpus exists, and how it is stored | [ADR-0088](../adr/0088-the-spoin-universe.md), [ADR-0089](../adr/0089-retrieval-grounded-generation.md) |
| The procedure you run each time | [`docs/the_spoin_universe/procedure.md`](../the_spoin_universe/procedure.md) |
| The full plan this is one track of | [task 0038](../tasks/0038-frog-rag-and-hybrid-generation.md) |
