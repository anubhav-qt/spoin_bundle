# `the_spoin_universe` — the authoring procedure

> **Who this is for:** Antigravity, working under the project owner's supervision.
> **What it is:** the procedure you follow, start to finish, every time the owner
> hands you a survey or a topic to author.
> **Companion doc:** [`docs/handoff/antigravity-corpus-authoring.md`](../handoff/antigravity-corpus-authoring.md)
> is the *contract* — what the files must contain and why. This document is the
> *process* — what you do, in what order. Read that one first, once. Read this one
> every run.

---

## 0. The one-paragraph version

The owner gives you a subject. You ask where it belongs in the hierarchy and whether
it is a survey or a topic. You check what the corpus already covers so you do not
re-fetch knowledge you already have. You then research it hard — **breadth** if it is
a survey, **depth** if it is a topic, in both cases from zero to mastery — and dump
everything raw into `temp/`. Then you read all of it yourself and curate it by hand
into dense, correct, reusable documents under `corpus/`. Then you report what you
added and what you deliberately left out.

The whole thing exists so that a small, fast model can *restate* a fact instead of
*recalling* one. That is the bar every decision below is measured against.

---

## 1. The hierarchy

```
category                 Mathematics, Science, Computer Science, History, ...
└── sub_category         (optional)  Science → Biology, Physics, Chemistry
    └── survey  OR  topic
        └── subtopic     a curriculum slot, at a difficulty tier
            └── cards    what the user actually reads
```

### What already exists in the product, and what does not

This distinction matters, because it tells you which levels you are authoring *for*
and which you are authoring *into*.

| Level | Where it lives | Who creates it |
|---|---|---|
| **category** | `document.category` in `the_spoin_universe` ([ADR-0091](../adr/0091-corpus-category-hierarchy.md)). **Corpus-side only — no column in the product database.** | **You**, in front matter |
| **sub_category** | `document.sub_category`. Optional, same status. | **You**, in front matter |
| **survey / topic** | `topic` table, distinguished by the `is_survey` flag | The product, when a user requests a subject |
| **subtopic** | `subtopic` table — a curriculum slot with a difficulty tier | The generation pipeline's curriculum pass |
| **cards** | `card` table | The generation pipeline, grounded in *your* corpus |

**Categories and sub-categories exist in the corpus database and nowhere else.** You
are the first thing in this project that needed a level above `topic`, so
[ADR-0091](../adr/0091-corpus-category-hierarchy.md) introduced it on `document` —
`category`, `sub_category` and `scope`, with a CHECK making the first and third
mandatory for `topic_source` and optional for `spoin_canon`.

Two consequences for you:

- **Your front matter is what fills those columns.** Values are normalized on the way
  in (lowercased, non-alphanumerics to spaces), so "Computer Science" and
  "computer-science" are one category rather than two — but a genuinely different
  wording is a genuinely new category. Be consistent.
- **The values are read back to you.** Phase A's list of existing categories is a
  query against this column. An inconsistent value you write today proposes itself to
  the owner as an option forever.

### Survey versus topic — the distinction that changes your research

This is not a labelling detail. It changes what you go and fetch.

**A survey is a tour.** "Mathematics" is a survey. In the product it gets a survey
curriculum — a wide, shallow pass over the whole field — and it emits `deep_dive`
links to the narrower topics it introduces (Linear Algebra, Calculus, Probability).
Its honest completion state is *"you have seen the shape of this field; here is where
to go deeper."*

**A topic is a course.** "Linear Algebra" is a topic. It gets an exhaustive treatment
of one subject across all three difficulty tiers, and its completion state is *"you
know this."*

So:

- **Survey → research for BREADTH.** Every major branch, how they relate, what
  distinguishes them, the through-lines and the historical shape of the field, the
  vocabulary a newcomer needs to navigate any of them. You are mapping territory.
- **Topic → research for DEPTH.** One subject, exhaustively, including the parts that
  are hard, contested, version-specific, or commonly misunderstood. You are surveying
  a single site down to bedrock.

**Both go from zero to mastery.** Neither is "the beginner version". A survey covers
its whole field from a first-day framing to what a specialist would say about how the
branches connect; a topic covers its subject from first principles to the edge cases
an expert argues about. The difference is the *axis* you extend along, not how far
you go.

---

## 2. How a Spoin user actually learns — and why this makes accuracy non-negotiable

You are not writing an article. You are writing the ground truth that a machine will
shatter into hundreds of small pieces.

**The reader scrolls.** Spoin is a vertical feed. The user swipes through **cards** —
each one a small, self-contained explanation of a single idea, read in a few seconds,
one after another. They do not read your documents. They will never see them.

**Cards are generated once and served to everyone.** There is no per-user generation.
A wrong card is wrong for every reader who ever encounters it, forever, until someone
notices and reports it.

**Progress is quiz-gated.** After reading a tier's cards, the user answers questions
about them before the next tier unlocks. A card is not decoration — it is material
someone will be *tested on*. If your source material is subtly wrong, the user is
tested on the wrong thing and told they are correct.

**Your material grounds both the writer and the checker.** The pipeline drafts a card
from your corpus and then verifies it against *the same corpus*. This is the sharpest
edge of the whole design:

> If a passage of yours is wrong, the writer produces a confidently wrong card, the
> verifier retrieves your same wrong passage and **agrees with it**, and the card
> ships looking *sourced* — which is more credible to a reader than a guess would
> have been.

There is no third checker. **You are it.** This is why the research phase below
insists on thorough, current, primary-source web research rather than writing from
what you already know.

---

## 3. The procedure

Seven phases. Do them in order. Do not start researching before Phase B, and do not
start writing final files before Phase E.

### Phase A — Intake: ask the owner three questions

The owner gives you a subject. Before anything else, **ask** — do not infer, do not
assume, do not proceed on your best guess. These three answers determine everything
downstream, and getting them wrong wastes an entire research pass.

#### A1. Which category does this belong to?

Offer the owner a concrete list to pick from, assembled in this order:

1. **Categories already present in the corpus.** Read the `category` values already
   in use under `corpus/`. These are the real options and should be listed first —
   reusing an existing category is almost always right.
2. **Categories already implied by the product database**, if you can see it: existing
   topics in `spoin_db_2` suggest where a subject naturally sits.
3. **Your own proposals**, clearly marked as new, when nothing existing fits.

Present them as options, note which are existing and which are new, and let the owner
choose. **A new category is a real decision** — say so when you propose one, rather
than slipping it in as though it were established.

#### A2. Which sub-category, if any?

Same sourcing, same presentation. Sub-categories are **optional** — "Computer
Science → Databases" is useful; "History → History" is noise. If the category is
already narrow enough that a sub-category would just restate it, say so and offer
"none" as an option.

#### A3. Is this a survey or a topic?

Ask directly, and give the owner the two definitions from §1 alongside the question
rather than assuming they have this document open. Include your own recommendation
and the reason for it — "I'd call this a survey: it names a whole field and I can
list at least six distinct sub-fields under it" — but **the owner decides**.

If the subject is genuinely ambiguous, say that plainly. Some subjects can be either
depending on how the product wants to use them; that is the owner's call, not a
problem for you to resolve quietly.

**Do not proceed until all three are answered.** Ask all three at once if that is
easier for the owner, but do not begin Phase B with any of them still open.

---

### Phase B — Coverage check: what does the corpus already know?

**Do this before fetching anything.** The corpus is meant to grow compositionally, not
by accumulating near-duplicates of the same material under different names.

Read what is already under `corpus/` and answer three questions honestly:

1. **Is this subject already covered?** If a document already treats it well, the run
   may be finished before it starts. Say so.
2. **Which parts are already covered by neighbouring subjects?** A new topic
   "Database Indexing" sitting next to an existing "PostgreSQL Internals" and
   "Data Structures" may already have its B-tree foundations written. Do not write
   them again.
3. **What is genuinely missing?** This is your actual research scope, and it is often
   much smaller than the subject sounds.

**Why this matters more than it looks.** The intent is that once the corpus holds
enough depth across a set of topics, a *new* topic that sits among them can be
generated largely from material that already exists — and once it holds enough
breadth across a set of fields, a *new* survey can be assembled the same way.
Redundant near-duplicate documents actively break this: retrieval returns three
overlapping passages instead of three complementary ones, the prompt budget is spent
on repetition, and nobody can tell which copy is the maintained one.

**Report the result of this phase to the owner before you start researching**, as a
short note: what is already covered, what you intend to fetch, and what you are
deliberately skipping because it exists. If that note says "almost everything is
already there", that is a good outcome, not a failed run.

---

### Phase C — Research: fetch a lot, from the real world

Now go wide. This is the phase where effort is not the constraint.

#### The standing rules

- **Search the web thoroughly. Do not write from memory.** Your parametric knowledge
  has a cutoff, and the corpus's entire purpose is to be *better* than parametric
  knowledge. A document written from recall is worth less than nothing here, because
  it will be trusted as though it were sourced.
- **Prefer primary sources.** Specifications, official documentation, standards
  documents, papers, reference implementations, release notes. A blog post
  summarising a spec is strictly worse than the spec. A tutorial is worse than both.
- **Be current, and record it.** Software versions, defaults, deprecated APIs,
  renamed concepts, superseded results, changed best practice. Capture *when* each
  source is from — you will need it for the `source_date` field, and a reader
  deserves to know whether a claim is from this year or from 2018.
- **Corroborate anything surprising.** If one source says something the others do
  not, that is either a genuine subtlety worth capturing precisely or an error worth
  discarding. Find out which. Do not average them into a hedge.
- **Collect the disagreements.** Where authorities genuinely differ, that *is* the
  knowledge — record both positions and who holds them. Do not flatten it.
- **Mine practitioner experience, field lessons, and community debates.** Search places
  where experienced people, practitioners, enthusiasts, and specialists discuss
  real-world practice, subtle edge cases, and common missteps: community forums,
  Reddit discussions, StackExchange/StackOverflow, specialized publications,
  practitioner postmortems, and field notes. Textbook introductions cover the idealized
  happy path; practitioner communities surface the real pitfalls, counter-intuitive
  nuances, practical rules of thumb, and lived experience that standard guides overlook.

#### If the input is a SURVEY — research for breadth

- Enumerate **every** major branch of the field, not the popular ones.
- For each branch: what it studies, its central objects, why it exists as a separate
  branch, and what a first encounter with it looks like.
- Map the **relationships** — what depends on what, what historically came from what,
  which pairs are commonly confused, which branch a newcomer should meet first.
- Capture the field's **shared vocabulary** — the terms you cannot read any branch
  without.
- Capture its **shape over time**: what the field used to be about, what it is about
  now, where it is visibly moving.
- Reach mastery on the *connective tissue*: how a specialist describes the field as a
  whole, not just the sum of its parts.

#### If the input is a TOPIC — research for depth

- Cover the subject from **first principles** — assume the reader knows nothing — up
  to what a practitioner argues about with other practitioners.
- Gather the **exact things models get wrong**: precise definitions, real numbers,
  actual defaults, version-specific behaviour, the boundary condition everyone
  misstates. This is your highest value-per-token material.
- Gather **worked mechanics**: not "how it is used", but *how it works*. The
  causal chain, not the recipe.
- Gather **failure modes and edge cases** — where the simple mental model breaks.
- Gather the **history only where it explains the present**: why the design is odd,
  what constraint produced it.
- Gather **what it is not** — the neighbouring concept it is habitually confused
  with, and the actual distinction.

---

### Phase D — `temp/`: the raw dump

Everything Phase C produces goes into `docs/the_spoin_universe/temp/`, raw.

**Rules for `temp/`:**

- **It is wiped and rewritten for every new input.** One survey or one topic occupies
  it at a time. Clear it at the start of a run, not the end — a crashed run should
  leave its evidence behind.
- **It is scratch, and it is not the deliverable.** Nothing in `temp/` is ever
  ingested. Nothing in it is committed.
- **Keep the raw material raw.** Source URLs, retrieval dates, full passages, your own
  notes, contradictions you have not resolved yet, dead ends. Do not pre-summarise
  while dumping — summarising is Phase E's job and doing it early destroys the
  material you would need to do it well.
- **Keep provenance attached to every passage.** You will need the URL and the date
  when you write front matter, and reconstructing it later is miserable and
  error-prone.

A reasonable shape, though this is guidance rather than a schema — `temp/` is yours:

```
temp/
  00-scope.md              what Phase B said was missing; what you set out to fetch
  01-sources.md            every source consulted, with URL and date
  10-<subject-area>.md     raw gathered material, one file per area
  90-open-questions.md     contradictions, gaps, things to raise with the owner
```

---

### Phase E — Curation: by hand, by you

This is the phase that determines whether the corpus is worth having.

> **Curate manually, using your own reading and judgment. Do not write scripts to do
> it.**

No regex passes, no automated deduplication, no bulk transforms, no
"summarise every file in a loop", no clever pipeline that turns `temp/` into
`corpus/`. **Read every passage. Decide about every passage. Write the result
yourself.** A script cannot tell that two sentences say the same thing in different
words, that a claim is subtly out of date, or that a paragraph is true but useless.
That judgment *is* the deliverable. A script that appears to save you time here has
only moved the cost onto every card generated from the result.

#### What curating actually means

**Compress hard.** A chunk of yours will be dropped into a prompt next to five others
and a token budget. Every sentence competes for space against another true sentence.
Cut anything the model already knows well — general framing is the cheapest thing a
language model produces, and including it displaces something it genuinely lacks.

**Resolve, do not hedge.** Where sources disagreed, either establish which is right
and say it plainly, or state the disagreement explicitly and attribute both sides.
"Some say X, others Y" with no attribution is the worst possible output: vague,
sourced-looking, and it will pass the quality gate.

**Write self-contained sections.** Use `##` headings — these become the chunk
boundaries. A chunk is retrieved and shown to a model **without its neighbours**, so
a section that opens with "as mentioned above" arrives meaningless. Define an
unfamiliar term in the section that uses it, not once at the top of the file. Aim for
a few hundred words per section.

**⚠️ A section must be under 2,200 characters (~512 tokens). Hard error — the
document does not ingest.** One `##` section becomes exactly one chunk and **nothing
splits an over-long one for you.** An oversized section becomes one enormous chunk that
wins a retrieval slot and then spends a third of the prompt budget on material only
partly about the query. Aim for **1,000–2,000 characters**; the corpus currently runs at
a median of ~1,550, which is a good size.

When a section runs long it is almost always **two ideas wearing one heading** — which
is the deeper reason the limit exists. A section covering two ideas is embedded as *one*
vector that is the average of both, so it ranks mediocre for each and may be retrieved
for neither. Two focused sections beat one thorough section, every time. Split it.

**Headings are read by the model.** They go into every chunk's contextual header and
into its vector, so `## What REPEATABLE READ actually guarantees` is a heading and
`## Overview`, `## Part 2` and `## Details` are not — they say nothing about the content
and make the chunk harder to find.

**Front-load the specifics.** The opening sentence or two carry the most weight in the
vector. Start with the concrete claim, not a windup.

**⚠️ Do not write an intro paragraph before the first `##`.** The ingester **fails the
whole document** for it — not a warning, not a silent drop. Everything except an
optional `# H1` line must live inside a `##` section, because a paragraph belonging to
no section either vanishes or gets attached to a chunk it does not describe. This is the
common contract violation by a wide margin — by the end of task 0038's Phase 2 it was the
only one left, in 44 of 58 delivered documents. If the framing genuinely earns its tokens, give it its own `##` heading;
most of the time it is general context the model already has, and the honest move is to
cut it.

**Your `title` is read on every chunk.** The ingester prefixes each chunk with a header
built from the document title and the section heading — `MVCC and transaction isolation
in PostgreSQL — Snapshot isolation` — before embedding and storing it, so a chunk names
its own subject even when the prose does not. You do not write the header. Two things
follow: make `title` descriptive rather than clever, and stop repeating the subject in
every section's opening sentence, because the header already says it.

**Write for reuse across topics, not for this one topic.** This is the part that is
easy to get wrong. You are not writing "the background section of the Database
Indexing topic" — you are writing *what is true about B-trees*, in a form that the
indexing topic, the filesystems topic and the PostgreSQL topic can all retrieve. Do
not narrate the document toward the subject that happened to trigger this run. That
narration is exactly what makes a corpus non-compositional and forces the next
subject to re-fetch material that is already sitting there.

**Be specific, always.** "PostgreSQL's `REPEATABLE READ` prevents non-repeatable
reads and, unlike the SQL standard's minimum, also prevents phantom reads" earns its
tokens. "Isolation levels trade consistency for performance" does not.

**Do not simplify for the learner.** The reader never sees your documents — they see
cards generated from them, pitched at a difficulty tier. Reading level is the
generator's job (owner's decision, 2026-09-05). The same chunk must ground a beginner
card *and* an advanced one, so writing at beginner level caps the ceiling for every tier
at once, and the verifier retrieving a softened passage loses the precision it needs to
check a claim. What you owe the learner is **self-contained** language, not simple
language: use the precise term, and define it in the section that uses it.

**Keep it dry.** Spoin's playfulness lives in the hook layer — a card's title, its
summary, its ASCII art. **Never in the explanation.** A joke in your source material
becomes a joke in a card's `body`, which is the text the user is quizzed on and the
text the quality gate reads as meaning.

**Cut ruthlessly, and say what you cut.** Ten dense correct documents beat a hundred
hedged ones. If you were not able to establish something confidently, **leave it out
and tell the owner** — do not soften it into something vague. An absent passage makes
the model fall back on its own knowledge, which is merely the status quo. A wrong
passage poisons the writer and the verifier at once.

---

### Phase F — Emit: write the final files

Curated documents go under `corpus/`, laid out by the hierarchy:

```
corpus/
  <category>/
    <sub_category>/          omit this level entirely when there is none
      <survey-or-topic>/
        <document>.md
```

For example:

```
corpus/
  computer-science/
    databases/
      postgresql/
        mvcc-and-isolation.md
        indexing-and-access-paths.md
        tips-and-tricks.md
  science/
    physics/
      thermodynamics/
        entropy.md
        tips-and-tricks.md
```

Alongside the conceptual breakdown documents, **every subject (survey or topic) must
emit a dedicated `tips-and-tricks.md`**. This file gathers hard-learned practitioner
lessons, real-world traps, counter-intuitive edge cases, and field rules of thumb that
dispel common beginner myths and prevent painful mistakes across the subject.

Each file is UTF-8 Markdown with YAML front matter:

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

...
```

| Field | Required | Notes |
|---|---|---|
| `title` | **yes** | Human-readable. Shown when a card cites this. |
| `kind` | **yes** | `topic_source` for subject matter, `spoin_canon` for how Spoin itself works. Exactly one of the two — a typo is a hard error, not a silent third kind. |
| `category` | **yes** for `topic_source` | As agreed in Phase A. Normalized on ingestion. Omit for `spoin_canon`, which sits outside the subject hierarchy. |
| `sub_category` | only if one was chosen | Omit the field entirely when there is none — its absence is a statement, not missing data. |
| `scope` | **yes** for `topic_source` | `survey` or `topic`, as agreed in Phase A. Omit for `spoin_canon`. |
| `source` | **yes** | URL, or an origin description for canon. This is what a card cites. |
| `source_date` | strongly preferred | When the **source material** is from — not when you wrote the file. **`YYYY-MM-DD`, `YYYY-MM` or `YYYY`**; shorter forms widen to the first of the period. Use a full date when the source has one, and a bare year when it genuinely does not — accumulated practitioner experience or a body of postmortems has no single date, and inventing one would be a false precision. Anything else fails the document. |
| `topic_tags` | **yes** for `topic_source` | Normalized on ingestion: lowercased, non-alphanumerics become spaces, whitespace collapses. Write naturally; prefer full names over abbreviations (`kubernetes`, not `k8s`). Tag for what a document *is about*, not where you want it retrieved — retrieval is cross-topic by default. |

Two fields you never write: `source_path` (derived from the file's location) and
`content_hash` (computed). Both are how re-ingestion stays idempotent.

**On revising:** a document's identity is its path, and change is detected by hashing
the file. So — **edit in place**. Never create `entropy-v2.md` beside `entropy.md`;
both would be ingested and retrieval would return whichever it liked, including the
stale one. Renaming a file reads as a deletion plus a new document, so do not
reorganise casually.

The full contract, including what the ingester does with each field, is in
[`docs/handoff/antigravity-corpus-authoring.md`](../handoff/antigravity-corpus-authoring.md).

---

#### Before you hand it over: run the validator

The ingester's contract check runs standalone — no GPU, no database, no model — and
reports **every** problem in **every** failing file, named by path and by field:

```bash
make corpus-check
```

Ask the owner to run it at the end of the run and to paste you the output. A clean
delivery ends `checked N documents: N ok, 0 failing`. Anything else is work still to do,
and it is far cheaper to fix now than after the owner has moved on to the next subject.

If the validator and this document disagree, **say so in your Phase G report** — one of
them is wrong and it matters which.

### Phase G — Report back

Close every run with a short written summary to the owner:

- **Where it landed** — category, sub-category, scope, and the paths of the files you
  added or changed.
- **What Phase B found** — what already existed, and what you therefore did not fetch.
- **What you deliberately left out**, and why. Especially anything you could not
  establish confidently. This list is as valuable as the corpus itself.
- **Open questions and contradictions** you could not resolve.
- **Anything stale you noticed** in the existing corpus while working — a superseded
  version number, a claim that no longer holds. Say it; do not fix it silently in a
  run that was about something else.

---

## 4. The rules that do not belong to any one phase

- **Never invent a fact to fill a gap.** Covered above, and worth repeating because it
  is the single most damaging thing you can do here.
- **Never copy material you do not have the right to reproduce.** Cite the source and
  restate it in your own words. Cards are shown to real users.
- **Coverage is a nice-to-have; correctness is the product.**
- **ASCII Art validation failure degrades to 'no card'.** If any line in an ASCII art
  block exceeds the 40-column monospace limit or contains invalid syntax, the card is
  discarded entirely (not published as prose) and scheduled for regeneration to ensure
  the subtopic receives high-quality visual art.
- **When something in this procedure turns out to be wrong or unworkable, say so in
  the same run.** A procedure that is quietly worked around is worse than no
  procedure — it makes every later run harder to reason about.

## 5. Where to read further

| | |
|---|---|
| The contract your files must satisfy | [`docs/handoff/antigravity-corpus-authoring.md`](../handoff/antigravity-corpus-authoring.md) |
| What a card, subtopic and question actually are | [`docs/architecture/content-model.md`](../architecture/content-model.md) |
| Why surveys and topics differ, and what `deep_dive` edges are | [ADR-0007](../adr/0007-curriculum-driven-generation.md) |
| Quiz-gated progression | [ADR-0009](../adr/0009-quiz-gated-progression.md) |
| Why the corpus exists and how it is stored | [ADR-0088](../adr/0088-the-spoin-universe.md), [ADR-0089](../adr/0089-retrieval-grounded-generation.md) |
| The full plan this is one track of | [task 0038](../tasks/0038-frog-rag-and-hybrid-generation.md) |
