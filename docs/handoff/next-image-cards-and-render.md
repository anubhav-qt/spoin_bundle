# Handoff: finish the image-card path, then render it

> Written 2026-09-06. **Read [`CLAUDE.md`](../../CLAUDE.md) first**, then
> [ADR-0095](../adr/0095-open-licensed-image-catalog.md) and
> [`docs/tasks/0040-open-licensed-image-catalog.md`](../tasks/0040-open-licensed-image-catalog.md),
> which is the build this handoff continues. Everything below is decided. Do not
> re-litigate it — build it.
>
> **A previous session started this and stopped part-way, on the owner's instruction.**
> Roughly half the frog side exists on disk and is UNVERIFIED — it has never passed
> `ruff format`, `mypy --strict` or a single test. § 3 lists exactly what is there and
> what state it is in. Your first job is to finish and verify it, not to rewrite it.

---

## 1. Why this exists

Astronomy is the first authored topic. Its curriculum asks for **568 cards across 30
subtopic-tiers, and 76 of them are `image` cards.** An image manifest with **exactly 76
open-licensed images** has been delivered for it. The two were sized to each other.

But there is no image code in the product. Today `_card_matches_type` in
`apps/api/src/spoin/generation/pipeline/state.py` gives `IMAGE` and `PROSE` the
**identical predicate**:

```python
if card_type == CardType.IMAGE.value:
    return not tags and draft.visual_id is None
if card_type == CardType.PROSE.value:
    return not tags and draft.visual_id is None
```

So one prose-shaped draft satisfies both quotas. Prose's 155 fills image's 76 for free,
all four typed quotas report satisfied at 492 cards, and the remaining 76 fall through to
`chosen_type=None` rounds with **no card-type steering at all**. The cost is not
wrong-format cards; it is 76 of 568 cards drafted unguided, and a curriculum claiming a
mix it does not produce.

## 2. ⚠️ The one thing that must not go wrong

**Do not make `_card_matches_type` require a resolved image until assignment actually
works.** Task 0040 Phase 4 names the failure and it is real:

[ADR-0066](../adr/0066-redraw-over-budget-ascii-art.md) makes a card whose visual cannot
be produced **reject and regenerate** rather than degrade to an art-less card. So if a
card is planned as an image card, no image resolves, and the missing visual rejects it,
the pipeline regenerates, plans another image card, and fails again — **an unbounded loop
burning Mistral quota on a topic that can never satisfy it.**

Today's identical-predicate bug is ugly but safe. A half-finished fix is not. The order in
§ 5 exists for this reason: **availability first, matching last.**

"No image available" and "image is broken" must stay distinguishable for the same reason.
The first prevents the card being planned; the second is an ADR-0066 rejection. Conflating
them is what creates the loop. This is CLAUDE.md's *a failed outcome and a rejected
outcome are never the same number*, applied to visuals.

---

## 3. What already exists on disk — VERIFY BEFORE YOU TRUST IT

All of the following was written in one session and **never linted, formatted, typechecked
or tested.** `ruff format --check` reported **2 files would be reformatted** and the run
was stopped before `mypy --strict` ever executed. Treat it as a draft that is probably
90% right, not as working code.

| File | State |
|---|---|
| `apps/frog/src/frog/universe/models.py` | `ImageLicence` StrEnum + `Image` model **appended**. Needs formatting. |
| `apps/frog/alembic/versions/f6a7b8c9d0e1_image_catalog.py` | Written. `down_revision = "e5f6a7b8c9d0"`. **NOT APPLIED.** Its `sa.Column("created_at", ...)` line is long and will be reformatted. |
| `apps/frog/src/frog/images/__init__.py` | Empty, exists. |
| `apps/frog/src/frog/images/contract.py` | Written. Pure validator, `parse_manifest` / `parse_images` / `entry_hash`. |
| `apps/frog/src/frog/images/runner.py` | Written. `ingest_manifest` / `ingest_images`. |
| `apps/frog/src/frog/images/__main__.py` | Written. `--check` / `--force` / `--embedder`. |
| `apps/frog/src/frog/retrieval.py` | `ImageHit`, `search_images`, `count_images` **appended**; import line extended to `..., Image, ImageLicence`. |

### First actions, in this order

```bash
docker compose run --rm --no-deps api sh -c "cd /app/frog && ruff format src"
docker compose run --rm --no-deps api sh -c "cd /app/frog && ruff check src"
docker compose run --rm --no-deps api sh -c "cd /app/frog && mypy src"
```

Known likely problems to fix rather than work around:

- `search_images` builds `select(Image, (1.0 - distance).label("score"))`. `_select_hits`
  above it is annotated `-> Select[tuple[Chunk, Document, float]]`; if mypy complains
  about the untyped inline select, annotate it the same way, do **not** add `# type: ignore`.
- `ImageLicence` may be imported into `retrieval.py` but only used in an annotation.
  If ruff flags it unused, it is genuinely used by `ImageHit.licence` — check before deleting.
- `contract.py` uses `dataclasses.replace` to fill `content_hash` after building the entry.
  That is deliberate; `entry_hash` hashes a finished object.

**Do not rewrite these files to your own taste.** They were written to match
`frog/ingest/contract.py` and `frog/ingest/runner.py` line for line in structure and
comment style, which is what the next reader will expect.

---

## 4. Ground truth — the state of the world right now

Verified 2026-09-06, after this session's work. Do not re-derive; do re-check anything you
are about to depend on.

| Thing | State |
|---|---|
| `spoin_db_2` alembic head | **`d2e3f4a5b6c7`**, applied |
| `the_spoin_universe` head | **`e5f6a7b8c9d0`**, applied. `f6a7b8c9d0e1` written, NOT applied |
| Corpus | 14 documents, 172 chunks. 9 astronomy `topic_source` (152 chunks) + 5 `spoin_canon` (20 chunks) |
| `chunk.heading IS NULL` | **0** |
| Embeddings | all `Qwen/Qwen3-Embedding-0.6B`, 1024-d |
| Grounding refs | **148/148 distinct (195 total) resolve to real chunk rows** |
| `corpus-check` | green (14 ok, 0 failing) |
| `curriculum-check` | green (1 ok, 0 failing) |
| Curriculum ingested / projected | **NO — neither has been run** |
| `spoin_db_2` contents | 1 topic (`rust`), 47 subtopics, 86 cards — all from the OLD generated path. Untouched, and the projection will not touch it |
| `SPOIN_GENERATOR` | `hybrid` |
| `SPOIN_MISTRAL_API_KEYS` | set, validated live (`GET /v1/models` → 200). `ministral-8b-2512` exists, 262k context |
| Tests | 612 spoin + 88 frog passing, at commit `00dbb58` |
| Last commit | `00dbb58 killed all the orphans after migration` — **not pushed** |

**134 orphan documents / 868 chunks were deleted** from `the_spoin_universe` this session
(a corpus that no longer existed on disk). A consequence: the 86 Rust cards'
`grounded_chunk_ids` now point at chunks that no longer exist. That is the dangling
cross-database reference [ADR-0088](../adr/0088-the-spoin-universe.md) explicitly accepts.
Do not "fix" it.

### The delivered material

**Curriculum** — `docs/the_spoin_universe/curricula/astronomy/curriculum.md`:
10 subtopics × 3 tiers = 30 tiers, 568 target cards, `is_survey: true`.
Card-type quotas across the whole topic: `prose 155, comparison 146, ascii 122, image 76,
diagram 69`. Per-tier `grounding` scopes are 6–9 section refs (18 tiers have 6, 10 have 7,
1 has 8, 1 has 9).

**Images** — `docs/the_spoin_universe/images/astronomy/physics/astronomy/images.md`:
- `kind: image_manifest`, `category: astronomy`, `sub_category: physics`, `subject: astronomy`
- **76 entries**, every one carrying all 7 required fields, no duplicate `source_url`, no
  duplicate `title`
- Licences: `public-domain` 56, `cc-by` 15, `cc-by-sa` 20 → **5** (`cc-by-sa` is 5)
- Descriptions run 397–730 characters — genuinely written for retrieval, not alt text

⚠️ Note `category` is `astronomy` at the **manifest header**, inherited by every entry.
`Image.category` is NOT NULL. There is no per-entry category and there must not be.

---

## 5. What to build, in this exact order

The order is not a suggestion. § 2 is why.

### Task 1 — Verify and land the frog half

Do § 3's three commands. Then apply the migration and ingest:

```bash
make universe-migrate                                                    # applies f6a7b8c9d0e1
docker compose --profile frog run --rm --entrypoint python frog -m frog.images --check
docker compose --profile frog run --rm --entrypoint python frog -m frog.images
```

Expect `--check` to print `checked 1 manifests: 1 ok, 0 failing, 76 images`, and the
ingest to report `created=76`. Then confirm in SQL: 76 rows, `embedding_model` is Qwen3
(**not** hash), `category = 'astronomy'`, `cloudinary_url` all NULL.

Add the Makefile targets beside the curriculum ones, copying their comment style exactly:

```makefile
image-check: ## Validate docs/the_spoin_universe/images against the contract; writes nothing
	$(COMPOSE) --profile frog run --rm --entrypoint python frog -m frog.images --check

image-ingest: ## Ingest image manifests into the_spoin_universe (GPU; run universe-migrate first)
	$(COMPOSE) --profile frog run --rm --entrypoint python frog -m frog.images
```

Add both to the `.PHONY` list at the top (line 8-9 area). **Do not** add them to
`make check`.

### Task 2 — `VisualKind` and `card.visual_kind`

`apps/api/src/spoin/domain/enums.py` — add beside `CardType`:

```python
class VisualKind(StrEnum):
    ASCII = "ascii"
    IMAGE = "image"
```

Write its docstring to say **why it is not inferred**: an image `visual_id` is a UUID and
an ASCII scene id is not, so the kind is *technically* recoverable by inspecting the
string — and doing that would make rendering depend on an implicit format rule, which is
the class of hidden constraint this codebase enforces against rather than relies on
(task 0040 Phase 3 says this in as many words; cite it).

`apps/api/src/spoin/domain/models/card.py` — add beside `visual_id` / `visual_slots`:

```python
visual_kind: Mapped[VisualKind | None] = mapped_column(
    Enum(VisualKind, name="visual_kind", values_callable=lambda e: [m.value for m in e]),
    nullable=True,
)
```

with a `CheckConstraint` in `__table_args__`:

```python
CheckConstraint(
    "(visual_id IS NULL) = (visual_kind IS NULL)",
    name="visual_kind_accompanies_visual_id",
)
```

⚠️ **Alembic does not autogenerate `CheckConstraint`s — write it by hand in the
migration.** ⚠️ **Constraint names: pass the short form**; the metadata convention adds
the `ck_card_` prefix.

New migration on the spoin chain, `down_revision = "d2e3f4a5b6c7"`. ⚠️ **Every
autogenerated migration in this repo proposes dropping three `server_default`s on
`ask_conversation.status`, `ask_message.on_topic`, `generation_job.kind`. That is task
0041, unrelated drift — strip those lines.**

Backfill in the same migration: existing rows with a non-null `visual_id` are all ASCII,
so `UPDATE card SET visual_kind = 'ascii' WHERE visual_id IS NOT NULL` **before** adding
the constraint, or it will fail on the 86 existing cards.

### Task 3 — `CardDraft.visual_kind`

`apps/api/src/spoin/generation/base.py`, add to `CardDraft`:

```python
visual_kind: VisualKind | None = None
```

⚠️ **`CardDraft` is NOT the LLM wire schema.** `_WireCard` in `langchain_impl.py` is, and
`CardDraft` is constructed from it around line 1948. Adding this field therefore does
**not** expose images to the model, which is required: ADR-0095 says *the model emits no
image reference at any point; it is not told images exist.* Say that in the field comment,
because it is the exact thing a future reader will try to "improve".

The ASCII path must set `visual_kind=VisualKind.ASCII` wherever it currently sets
`visual_id`. Grep for `visual_id=` in `langchain_impl.py` and `pipeline/` and cover every
site, or the new CHECK constraint will start rejecting ASCII cards.

### Task 4 — `spoin/generation/images.py`, the assignment module

**Model this file on `spoin/generation/grounding.py`.** Same reasons apply and the
docstring should say so: it lives in `spoin` rather than `frog` because it is
product-shaped work — what a *card* gets — while frog answers only "what is most similar".

```python
async def assign_images(
    session_scope,               # universe_session_scope, same as grounding.py
    embedder: Embedder,
    *,
    topic_id: uuid.UUID,
    categories: Collection[str],
    drafts: Sequence[CardDraft],
    min_score: float,
) -> ImageAssignmentReport
```

Behaviour:

1. For each draft **that has no `visual_id` yet**, query with the card's own text —
   `f"{draft.canonical_title}. {draft.summary} {draft.body}"` — via `search_images(k=1, ...)`.
2. `exclude_image_ids` = every `visual_id` already used by an **active or draft** card in
   this topic, read as a **query, not caller-held state**. Task 0040: this is what makes
   intra-batch collisions impossible without a lock — a second card drafted concurrently
   simply gets the next best image.
3. On a hit, set `draft.visual_id = str(hit.image_id)` and
   `draft.visual_kind = VisualKind.IMAGE`. Put `title`, `attribution`, `display_url`,
   `source_page` and `licence` into `draft.visual_slots` — the renderer needs all five and
   must not have to reach across the database boundary to get them.
4. **Never raise.** Same contract as `Grounding`: an unreachable corpus degrades to
   unassigned rather than losing the run. Report the outcome; do not swallow it.
5. Return counts as **separate numbers**: `assigned`, `no_candidate` (catalog exhausted),
   `below_floor`, `unavailable` (corpus unreachable). CLAUDE.md: a fallback and a failure
   are different facts and never one number.

**Record every candidate's score in the report even when it is assigned.** That is what
lets the floor be set from a measured distribution later (§ 6).

### Task 5 — Wire assignment into the drafting loop

`apps/api/src/spoin/generation/pipeline/nodes.py`, in the drafting `while` loop. The
insertion point is immediately after the early-out and **before** `drafts.extend(...)` and
`_persist_drafts(...)`, around line 947:

```python
if not result.items:
    break  # no usable progress this round -- stop
if chosen_type == CardType.IMAGE.value:
    await _assign_images(runtime, tier=tier, drafts=result.items)
drafts.extend(result.items)
draft_card_ids.extend(await _persist_drafts(...))
```

Why here and not at planning time: task 0040 Phase 3 says assignment queries the card's
text, which only exists after drafting — a plan is a brief, not a draft (ADR-0059). And it
must be before `_persist_drafts` so `visual_id` / `visual_kind` / `visual_slots` are
written in the same row rather than as an update.

`_persist_drafts` in `pipeline/persistence.py` must carry `visual_kind` through. Check it
— it currently writes `visual_id` and `visual_slots`.

### Task 6 — The planner ceiling (Phase 4, the loop guard)

`nodes.py` around line 713 builds `tier_quotas` from `tier.get("card_type_quotas")`. Cap
the `image` entry at real availability:

```python
available = await count_images(session, categories=categories, exclude_image_ids=used)
tier_quotas["image"] = min(tier_quotas.get("image", 0), available)
```

The shortfall goes to `prose`, so `sum(tier_quotas.values())` still equals `target_cards`.

The precedent to follow is one line above: the `code` check already passes
technical-topic-ness into planning. Same principle — *the planner is trusted for taste,
not constraints* (CLAUDE.md). Cite it.

**This is a ceiling read from real availability, never a quota.** Astronomy will exceed
it comfortably (76 images ≥ 76 cards); a future topic with no sourceable imagery sits at
zero and simply gets no image cards. That is the correct outcome, not a degradation.

### Task 7 — `_card_matches_type`, LAST

Only now, in `pipeline/state.py`:

```python
if card_type == CardType.IMAGE.value:
    return not tags and draft.visual_kind is VisualKind.IMAGE
if card_type == CardType.PROSE.value:
    return not tags and draft.visual_id is None
```

Note `PROSE` gains nothing but now genuinely excludes image cards, because an assigned
image card has a `visual_id`. Check the `ASCII` branch above still reads
`draft.visual_id is not None or bool(draft.visual_slots)` — it should, and an image card
would now wrongly satisfy it. **Tighten ASCII to `draft.visual_kind is VisualKind.ASCII`
in the same change**, or image cards will start filling the ASCII quota, which is this
whole bug again with different nouns.

### Task 8 — Tests

Follow `apps/api/tests/test_scoped_grounding.py` and `apps/frog/tests/test_curriculum_*.py`
for shape. **Use the real Postgres `session` fixture** wherever the database's own
behaviour is the thing under test — the unique constraint on `source_url`, the new CHECK
on `card` — and mock the generator, never the database (CLAUDE.md).

Minimum coverage:

- `frog`: contract accepts the real delivered manifest; rejects a bad `licence`, a missing
  field, a short `description`, a duplicate `source_url` within one manifest and across
  two; `entry_hash` is stable and changes when `description` changes.
- `frog`: `ingest_manifest` is idempotent (second run → `unchanged=76, created=0`); a
  withdrawn entry is removed; `--force` re-embeds.
- `spoin`: assignment sets all three visual fields; a second card in the same batch gets a
  different image; an exhausted catalog reports `no_candidate` rather than raising.
- `spoin`: `_card_matches_type` distinguishes IMAGE from PROSE from ASCII.
- `spoin`: the planner ceiling caps `image` at availability and pushes the remainder to
  `prose`.

---

## 6. The one constant nobody has measured

`min_score`, the image similarity floor. Task 0040 Phase 3 demands a floor — *"an
irrelevant image is worse than none; it makes a card look sourced while showing something
else"* — and in the same breath says **do not pick it now, calibrate it against real
cards.**

**Ship run 1 with the floor at `0.0` and every score recorded.** The reasoning, which you
should put in the setting's comment rather than restate in a chat:

- No calibrated floor exists. Inventing a constant to defend a guess is worse than not
  having one — this is exactly [ADR-0101](../adr/0101-author-declared-grounding-scope-and-per-card-retrieval.md)'s
  posture on the grounding allowance, and it was right there.
- A **nonzero** floor makes availability an *estimate*, which reintroduces § 2's
  regeneration loop: `count_images` would over-report what can actually be assigned. At
  `0.0`, availability is exact and the loop is structurally unreachable.
- The catalog was authored *for* this curriculum, 76 images for 76 cards, so the realistic
  worst case is a mediocre assignment, not an absurd one.

Add it as `image_similarity_floor: float = 0.0` in `core/config.py`. After run 1, read the
score distribution out of the report and set it from data. **Flag this to the owner in
your first message — it is a constant, and the owner's rule is to ask before deciding one,
with a recommendation, before the code exists.**

---

## 7. Phase 5 — the renderer (owner wants this, and it is yours)

The generation run produces image cards that nothing displays yet. Build it after Tasks
1–8 land and after the owner has looked at what run 1 actually produced —
[ADR-0012](../adr/0012-feed-visual-design.md)'s posture is that visual decisions get
reviewed in the real feed, which needs the cards to exist first.

- The API exposes the image fields on the card wire schema. **`apps/web` gets zero
  business logic** — it renders what the API sends. If the web client can do something the
  future React Native client cannot, that is a bug (CLAUDE.md).
- **Attribution is displayed, always.** CC BY and CC BY-SA make it a licence condition.
  It is already on the card in `visual_slots`; the renderer must not have to decide
  whether it is required for a given licence, because a renderer that decides will get one
  licence wrong.
- Serve at card width. That cropping and resizing is a *derivative work*, which is exactly
  why ND licences are inadmissible — do not "helpfully" re-admit one.
- The card renderer must **survive a dangling `visual_id`**: the catalog is in
  `the_spoin_universe` and the card is in `spoin_db_2`, so this is a cross-database
  reference by value with no foreign key behind it, same as `chunk.topic_tags` (ADR-0088)
  and `card.grounded_chunk_ids` (ADR-0089). A missing image renders as a card without one,
  never as an error.
- A card **never** carries both a photograph and an ASCII gag (owner, 2026-09-05). One
  visual slot; `visual_kind` is what the renderer switches on.
- Every HTTP call goes through the `api` object in `apps/web/lib/api.ts`, grouped by
  domain. **Never call `fetch()` from a component.**
- Write it up as a benchmark doc with the **assignment-relevance rate measured, not
  asserted**.

---

## 8. Conventions — follow these exactly

- **`mypy --strict` and `ruff` (line length 100) are non-negotiable.** Fix the type error;
  do not reach for `# type: ignore`.
- **Comments explain *why*, never *what*.** If a comment restates the line under it, delete
  it. SQLAlchemy fields carry `#:` Sphinx-style comments recording provenance and citing
  the ADR behind the field's shape — `domain/models/card.py` is the canonical example, and
  the `Image` model in `frog/universe/models.py` was written to match it.
- **A module docstring names the doc that explains the file's purpose** rather than
  re-explaining it inline.
- **A hard architectural rule gets enforced twice, never documented once** — a ruff
  `banned-api` entry *and* an AST check in `tests/test_architecture.py`.
- **`spoin` imports `frog`, never the reverse.** Enforced by ruff and by
  `tests/test_architecture.py`. The image contract lives in frog and therefore cannot
  import spoin's enums.
- **Every LLM-facing interface method takes a collection, never a single item**
  (ADR-0005). Not directly relevant here — assignment makes no LLM call — but do not add
  one.
- **No LLM call anywhere in the feed read path.** Assignment is write-path only.

### Traps that will cost you time

- **The `test` compose service runs the WHOLE suite regardless of the paths you pass it,
  and it exits 0 even when tests fail.** Read the summary line; never trust the exit code.
- The working tree is **CRLF**, but several files are **LF** — including
  `generation/prompts/canon.py` and the corpus `_canon/*.md`. Detect per file; do not
  assume. Scripted `str.replace` over a CRLF file with `\n` patterns silently no-ops.
- **The Bash tool collapses `\\` inside heredocs.** Write patch scripts to a file in the
  scratchpad and run them. This has now bitten three sessions.
- `make` is not on PATH in the Bash tool. Use
  `docker compose run --rm --no-deps api ruff check src` / `mypy src` directly, and
  `docker compose run --rm --no-deps api sh -c "cd /app/frog && mypy src"` for frog.
- `ruff format src alembic` reformats 14 historical migrations. `make lint` covers
  `src tests` only — **do not widen it.**
- `MSYS_NO_PATHCONV=1` is not optional for container paths under Git Bash.
- **`test_canon_preambles.py` enforces a 1200-token ceiling per pinned preamble**, and a
  sha256 drift guard over the five `_canon` documents. You should not need to touch either:
  ADR-0095 says the model is never told images exist, so **no prompt changes and no canon
  changes are part of this work.** If you find yourself editing `canon.py`, stop and
  re-read § 2.

### Hard rules — no approval path, just don't

- **Never** `docker compose down -v`, `make clean`, or `docker volume rm`. One volume holds
  four databases including production `spoin_db_2` and the corpus. It has been destroyed
  four times.
- Reads on `spoin_db_2` are fine. Writes, schema changes and `alembic downgrade` — **ask
  first, every time.** That includes a `make migrate` for Task 2's migration.
- `make test` (→ `docker compose --profile test run --rm test`) is safe; it uses
  `spoin_db_test`.
- Cockroach/Neon portability work is remote-only, on a throwaway DB the owner provisions.

---

## 9. How the owner wants to work

- **Ask before deciding anything inside a task** — scope, mechanism, constants — with a
  recommendation, in one line, **before writing the code.** Flagging a decision after the
  code exists moves it to where it is most expensive to change. § 6's floor is the live
  example.
- **Do not re-ask what has already been approved.** Confirm a destructive action once,
  with the blast radius, then act. Asking twice reads as stalling.
- **Do not invent risks and then build safeguards for them.** Before writing a guard, state
  the failure it prevents and check the system can actually reach that state. There are no
  users and no production content. (§ 2 is not an invented risk — ADR-0066's rejection path
  is real and the loop is reachable. Everything else probably is invented.)
- **End on the task at hand.** No trailing roundups of unrelated open threads or other
  tracks' uncommitted work.
- **Match effort to stakes.** A small mechanical question does not need a design discussion.
- **Keep the loop closed.** A decision with real reasoning gets an ADR
  (`docs/adr/TEMPLATE.md`, number sequentially — highest is currently **0101**). Deferred
  work gets a task doc and a row in `docs/tasks/README.md`, never a TODO comment. If a doc
  turns out to be stale while you are working, fix it in the same session.

---

## 10. Definition of done

1. `make check` green — ruff, `mypy --strict`, and the full suite across both packages.
2. `make image-check` green; `make image-ingest` puts 76 Qwen3-embedded rows in `image`.
3. `_card_matches_type` distinguishes all six card types, and ASCII no longer matches an
   image card.
4. The planner cannot plan more image cards than there are unused images — with a test
   that proves it.
5. `card.visual_kind` is NOT NULL exactly when `visual_id` is, enforced by a CHECK, with
   the 86 existing ASCII cards backfilled.
6. An ADR written from what the build actually showed, and task 0040 updated to say which
   phases are done. **Cloudinary stays unbuilt and `cloudinary_url` stays NULL** — say so
   explicitly in both, with § 3's reasoning, so the next session does not read the empty
   column as an unfinished migration.

Then, and only then, Phase 5.
