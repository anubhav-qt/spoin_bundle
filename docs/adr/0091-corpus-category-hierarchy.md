# ADR-0091: Categories and sub-categories are a real level of the corpus schema, above surveys and topics

- **Status:** Accepted
- **Date:** 2026-09-05
- **Amends:** [ADR-0088](0088-the-spoin-universe.md) (adds three columns to `document`)

## Context

[ADR-0088](0088-the-spoin-universe.md) gave `the_spoin_universe` a `document`/`chunk`
schema whose only organising axis was `chunk.topic_tags` — a flat, unordered set of
normalized slugs. That was enough to file a document but not enough to *navigate* the
corpus.

Writing the authoring procedure
([`docs/the_spoin_universe/procedure.md`](../the_spoin_universe/procedure.md)) surfaced
what was missing. The procedure's first step asks the owner which category a new
subject belongs to, and it is supposed to offer **the categories already in use**
before proposing a new one. With tags alone there is no way to answer that question:
tags do not distinguish "this document is about mathematics" from "this document is
filed under Mathematics", and nothing says which tags are organising levels versus
which are subject matter.

The product database does not help. `spoin_db_2` has `topic`, `subtopic` and the
`is_survey` flag ([ADR-0007](0007-curriculum-driven-generation.md)), and **nothing
above `topic`**. There is no category anywhere in this project. The corpus is the
first thing that has needed one.

The full hierarchy the corpus is organised by:

```
category                 Mathematics, Science, Computer Science, ...
└── sub_category         (optional)  Science → Biology, Physics, Chemistry
    └── survey OR topic  ← the level `spoin_db_2` starts at
        └── subtopic
            └── cards
```

## Decision

**`document` gains three columns: `category`, `sub_category` and `scope`. The
hierarchy is stored, not merely conventional.**

| Column | Type | Notes |
|---|---|---|
| `category` | `String(120)`, nullable | Normalized by the same `normalize_topic_text` that produces `chunk.topic_tags` |
| `sub_category` | `String(120)`, nullable | Genuinely optional — see below |
| `scope` | enum `survey` \| `topic`, nullable | Mirrors `topic.is_survey` by value |

### Nullable columns plus a CHECK, not `NOT NULL`

```sql
CHECK (kind <> 'topic_source' OR (category IS NOT NULL AND scope IS NOT NULL))
```

`spoin_canon` documents — how Spoin itself works, distilled from CLAUDE.md and the
ADRs — sit **outside** the subject hierarchy. They are about the product, not about a
field. `NOT NULL` would force every canon document to invent a category, which puts
junk into the exact column the intake step reads back to offer the owner real options.

So the columns are nullable for canon and mandatory for subject matter, and the
distinction is enforced by the database rather than by the ingester remembering. This
is CLAUDE.md's "a hard rule gets enforced, not documented" applied to a schema
invariant.

### `sub_category` is optional in the real sense

"Science → Biology" earns the level. "History → History" does not. An absent
`sub_category` is a meaningful statement that the category is already narrow enough,
not missing data — so the procedure offers "none" as an explicit option at intake.

### `scope` is a property of the material, not a filing detail

`survey` and `topic` change what the document *contains*: survey material is breadth
(a field's branches, how they relate, its shared vocabulary), topic material is depth
(one subject from first principles to its edge cases). Both go to mastery; they extend
along different axes.

Nothing downstream can recover that from the prose. Retrieval assembling a survey
curriculum wants the breadth material; a deep-dive wants the depth material. Storing
it is what makes that distinction available later without re-reading every document.

### Stored normalized

`category` and `sub_category` go through the same `normalize_topic_text` as
`chunk.topic_tags` — lowercased, non-alphanumerics to spaces, whitespace collapsed. So
"Computer Science", "computer-science" and "COMPUTER SCIENCE" are one category rather
than three. Without this, the intake step's list of "existing categories" grows a
near-duplicate every time someone types a name slightly differently, which defeats the
purpose of offering it.

### It stays corpus-side for now

These columns are **not** being added to `spoin_db_2`. The corpus needs the hierarchy
today; the product does not yet have a surface that uses it. When one appears — a
browse-by-category view, a category-scoped feed — that is its own decision, and it can
read the corpus values as evidence of what the categories should be rather than
inventing a second vocabulary.

## Consequences

**Easier.** The authoring procedure's intake step becomes answerable with a query
instead of a directory walk. Retrieval gains two filters it did not have — "canon
only", "survey material only" — without a migration when they are wanted. The
`is_survey` distinction that already exists in the product is representable in the
corpus that grounds it.

**Harder.** Three more fields for the authoring track to get right, and their values
matter more than most because they are read back as options: an inconsistent
`category` proposes itself to the owner forever. Two vocabularies now exist for "what
is this about" — `category`/`sub_category` and `topic_tags` — and the boundary between
them is a judgment call rather than a rule. `scope` duplicates `topic.is_survey`
across a database boundary with no constraint keeping them in step, so they can drift.

**Committed to.** A hierarchy above `topic` existing in one database and not the
other, until something in the product needs it.

## Alternatives considered

**Leave it in front matter only.** What the procedure originally assumed. Rejected
once the intake step was written down: "list the categories already in use" is a
query, and answering it by parsing YAML out of every file in a directory tree is a
worse version of a `SELECT DISTINCT` that also silently misses malformed files.

**Encode the hierarchy in `source_path` and parse it.** The path already contains it
(`computer-science/databases/postgresql/...`). Rejected: it makes reorganising the
directory a schema change, and ADR-0088 already committed to front matter being
authoritative over layout precisely so a misfiled document is a *detectable*
inconsistency rather than a silent redefinition.

**Reuse `topic_tags` with a reserved prefix** (`category:mathematics`). No migration.
Rejected: a magic prefix inside a free-form array is a constraint nothing can enforce,
and the CHECK above becomes impossible to express.

**Add the columns to `spoin_db_2`'s `topic` table too.** Rejected as premature — no
product surface consumes a category yet, and inventing the vocabulary in two places
before either needs it is how they drift.

**A separate `category` table with foreign keys.** Properly normalized, and a category
could carry metadata later. Rejected as more machinery than two nullable strings earn
today; the normalization rule already prevents the duplicate-value problem a lookup
table would solve.

## Revisit when

- A product surface wants to browse or filter by category. That is when the vocabulary
  moves — or is copied — into `spoin_db_2`, and it deserves its own ADR.
- `scope` and `topic.is_survey` are observed to disagree for the same subject. There is
  no constraint keeping them in step, so the first divergence is the signal that one of
  them should be derived rather than authored.
- The boundary between `category` and `topic_tags` starts producing arguments. That
  means one of them is doing the other's job, and the fix is to say which.
