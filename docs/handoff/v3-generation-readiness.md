# Handoff: making the new generation pipeline ready for a real run

**Written:** 2026-08-28 · **Branch the work starts from:** `feat/ascii-mermaid-fixes-and-task-docs`
([PR #16](https://github.com/anubhav-qt/spoin_bundle/pull/16))

This is a self-contained brief. Read `CLAUDE.md` first, then this. It assumes no
memory of the session that produced the branch.

---

## What just changed, and what it means

The generation pipeline's visual layer was reworked across two ADRs
([0067](../adr/0067-mermaid-diagrams-and-form-free-ascii.md),
[0068](../adr/0068-curated-ascii-art-library-and-worked-few-shot-generator.md)):

- **Diagrams are now mermaid**, written as a ` ```mermaid ` fence and rendered
  client-side (`apps/web/components/MermaidBlock.tsx`). Hand-drawn ASCII box diagrams
  are gone from the prompts. Old cards keep rendering as they always did — dispatch is
  on the fence's language tag, so this is backward compatible with no migration.
- **ASCII scenes lost the mandatory stickman**. Any form is allowed; the prompt teaches
  through seven worked examples.
- **A curated ~2,487-entry ASCII reference library** is wired into the writer prompt by
  embedding retrieval (`apps/api/src/spoin/content/ascii_library.py`) — an `ascii`-typed
  planned card's `asset_direction` is the query, its top-10 nearest titles are offered
  as adaptable reference material.
- Three generation-time defects are now **enforced deterministically** server-side
  rather than asked for in a prompt: a stray fence wrapper around `visual_slots.art`,
  a duplicate copy of the lead visual inside `body`, and structurally-invalid mermaid.

**None of this is ready to generate against yet.** Six things stand between the branch
and a real run. They are listed below in the order they must happen.

---

## PHASE 0 — Preserve the current corpus as v1. BLOCKING; do this first.

`spoin_db` holds **14,470 real production cards, 14,182 questions, 75 topics, 27 users
and 10,056 engagement events** built over six benchmark runs. Everything after this
phase changes what future generation produces. Before any of it, freeze what exists so
the current corpus is recoverable and so v1-vs-v2 content can be compared later.

This is a **read-only** operation on `spoin_db` (`pg_dump` takes no locks that block
readers and writes nothing), so it needs no approval under CLAUDE.md's database rule.
Everything else in this document that touches the database does — see PHASE 6.

```bash
# ~99 MB database; the dump will be smaller. Store OUTSIDE the repo -- it contains
# real user rows (app_user, engagement_event) and must never be committed.
mkdir -p /e/spoin_backups
docker compose exec -T db pg_dump -U spoin -d spoin_db --format=custom --compress=9 \
  > /e/spoin_backups/spoin_db_v1_2026-08-28.dump
```

**Verify the dump actually restores — an unverified backup is not a backup.** Restore
it into a scratch database and diff the row counts. `spoin_db_v1_verify` is a new,
disposable database; creating and dropping it does not touch `spoin_db`:

```bash
docker compose exec -T db createdb -U spoin spoin_db_v1_verify
docker compose exec -T db pg_restore -U spoin -d spoin_db_v1_verify --no-owner \
  < /e/spoin_backups/spoin_db_v1_2026-08-28.dump

# must match: topics=75 cards=14470 questions=14182 users=27 events=10056
docker compose exec -T db psql -U spoin -d spoin_db_v1_verify -c \
 "SELECT (SELECT count(*) FROM topic) topics,(SELECT count(*) FROM card) cards,
         (SELECT count(*) FROM question) questions,(SELECT count(*) FROM app_user) users,
         (SELECT count(*) FROM engagement_event) events;"

docker compose exec -T db dropdb -U spoin spoin_db_v1_verify
```

Record the dump's path, size, sha256 and the verified row counts in
`docs/architecture/` alongside the existing run benchmarks. **Do not proceed to any
later phase until the restore has been verified.**

> **Naming note.** The owner has referred to the existing corpus as "v1/v2 and under"
> and the new pipeline's output as "v3". That maps onto a real column —
> `card.gen_meta->>'prompt_version'` — but **not with those numbers**. See PHASE 4:
> version 3 is already spent.

---

## PHASE 1 — Fix the embedder. One line; without it the whole library is inert.

`SPOIN_EMBEDDER` is **absent from `.env`**, so it falls back to the config default
`"hash"` (`apps/api/src/spoin/core/config.py:139`). `HashEmbedder`'s own docstring says
it plainly: *"**Not semantically meaningful.** It exists so the stack boots and the
tests run without pulling onnxruntime, not so anyone can reason about similarity."*

With it, `top_candidates()` returns ten semantically **random** pieces of art for every
card. There is no error, no warning, and the prompt looks perfectly well-formed — it
just silently offers the generator garbage. This is the single easiest way to waste an
entire generation run.

```bash
echo "SPOIN_EMBEDDER=fastembed" >> .env
docker compose up -d --build api worker    # first boot downloads the BGE-small ONNX model
```

Confirm it is actually working — the first result for a boxer query should be the
literal boxer entry, not something unrelated:

```bash
docker compose exec -T api python -c "
import asyncio
from spoin.content.ascii_library import top_candidates
async def m():
    for e in await top_candidates('a boxer in a fighting stance ready to fight', k=3):
        print(e.id, '|', e.title)
asyncio.run(m())"
```

> **Worth knowing:** topic matching (ADR-0025) uses the same embedder. If the live
> stack has always run on `hash`, topic dedup has been operating on meaningless
> similarity this whole time, which may explain near-duplicate topics in the corpus
> (`Cloud Native Infrastructure and Kubernetes` vs `Cloud Native Infrastructure &
> Service Mesh` vs `Kubernetes`, `Real Estate Investment & Private Equity Modeling` vs
> `Real Estate Private Equity`, `Macroeconomic Central Banking & Sovereign Debt` vs
> `Macroeconomics & Central Banking Policy` — all present today). Flip the embedder
> before requesting new topics, and expect matching to behave differently (better) than
> it has historically.

---

## PHASE 2 — Finish curating the ASCII library

Everything is set up; the work is a manual review of the remaining artwork.

**Full instructions: [`apps/helpers/curation/README.md`](../../apps/helpers/curation/README.md).**
Read it before starting — it explains *why* the titles need rewriting, which is the
part that determines whether the job is done well or just done.

**Status:** entries `0`–`188` of `0`–`2486` are reviewed and committed as the worked
reference (`apps/helpers/curation/decisions/0000-0188.tsv` — 143 RETITLE, 35 KEEP,
11 DELETE). **Entries 189–2486 remain.** Match the reference's style.

The headline finding, because it drives everything: the library's header claims every
title is *"100% DISTINCT, rich, search-friendly descriptive"*. It is not. **80% of gag
titles and 91% of informative titles are raw scraped captions with a `(WxH)` suffix
appended**, and **77% of entries share a title with another entry** once that suffix is
stripped — 50 identical `geometric decorative graphic design pattern`, 40 identical
`little mouse with round ears and curly tail`. Titles were written per *subcategory*,
not per artwork. Since `ascii_library.py` ranks candidates by title-embedding
similarity, forty identically-titled mice collapse the entire ten-candidate budget onto
one subject and hide the other 2,447 pieces.

When the review is complete:

```bash
python apps/helpers/curation/apply.py /tmp/entries.json \
    apps/helpers/curation/decisions \
    apps/helpers/use_for_gags.txt apps/helpers/use_for_informative_visualization.txt
python apps/helpers/curation/verify.py \
    apps/helpers/use_for_gags.txt apps/helpers/use_for_informative_visualization.txt
```

`apply.py` refuses to write unless **all 2,487 indexes have a decision** and no `ASK`
remains. Resolve every `ASK` with the owner first.

**Then sync the packaged runtime copy — generation reads this one, not
`apps/helpers/`:**

```bash
cp apps/helpers/use_for_gags.txt apps/helpers/use_for_informative_visualization.txt \
   apps/api/src/spoin/content/ascii_library_data/
cd apps/api && python -m pytest tests/test_ascii_library.py -q
```

This copy exists because `apps/api/Dockerfile` only `COPY`s `src` — it never ships the
sibling `apps/helpers/` tooling directory. **The sync is manual and easy to forget: an
edit in `apps/helpers/` changes nothing about generation until it is copied across.**
Worth adding a `make` target or a CI drift check while you are in here.

---

## PHASE 3 — Close the pipeline gaps that are still prompt-only

### 3a. Mermaid shape budget — [Task 0029](../tasks/0029-mermaid-shape-budget-and-curated-ascii-library.md) §1

`CARDS_DIAGRAM_SYSTEM` asks for a roughly **square** diagram (`flowchart TD` default,
~4-8 nodes, 2-4 rows deep, 2-3 nodes at the widest row, short labels) so a diagram
fills a phone card without becoming a one-node-per-row column or a wide strip. Node
count and label length are both countable from the mermaid source. **Nothing counts
them.** Add a check next to `_mermaid_structural_issue` in `langchain_impl.py`.

Deliberately **do this after a first smoke run** (PHASE 5), not before: thresholds
guessed without real v2 diagram output will reject diagrams that are actually fine, and
a false rejection costs a whole card. Look at what the model actually produces, then
set the numbers.

### 3b. The unplanned ASCII path gets no retrieval candidates

Retrieval is wired into `_format_plans`, which only runs on the **planned** path
(ADR-0059). Two routes bypass it and still generate unaided:

- `CARDS_ASCII_SYSTEM` — a whole batch forced to `card_type="ascii"`
- `HERO_CARDS_SYSTEM` — the hero card call

Neither has an `asset_direction` to embed. Extending retrieval there needs a different
query (the subtopic title + description is the obvious candidate). Small, self-contained
follow-up; noted in Task 0029.

### 3c. Resolve the ADR-0067 / ADR-0068 contradiction — **needs the owner, not a guess**

Both were accepted the same day and they disagree about the same prompt:

- **ADR-0068 §2** — ASCII cards *"must strictly contain pictorial artworks"*; checklists
  and typography are *"strictly prohibited."*
- **ADR-0067 §3** — no required form at all; several of its seven worked examples are
  deliberately non-pictorial (a checklist with no characters, pure typography with no
  drawing).

The shipped prompt (`ASCII_INSTRUCTIONS`) follows ADR-0067. Retrieval was wired to
match the shipped prompt. **Pick a side and amend the losing ADR** — do not leave two
accepted ADRs contradicting each other, per CLAUDE.md's "keep the loop closed."

---

## PHASE 4 — Bump the prompt version to 4, not 3

`CARD_PROMPT_VERSION` (`generation/pipeline/state.py:317`) **is already 3**, and the
live corpus already contains cards at every level:

| `gen_meta->>'prompt_version'` | cards | what it means |
|---|---|---|
| `NULL` | 9,002 | v1 by absence — predates the field |
| `2` | 2,259 | |
| `3` | 3,209 | ADR-0066's ASCII redraw + higher art quota |

The mermaid/ASCII/retrieval work is a materially bigger content change than v2→v3 was.
Shipping it under `3` would pool it with 3,209 existing cards and destroy the exact
comparison the field exists to enable.

**Set `CARD_PROMPT_VERSION = 4`** and extend the `#:` comment block above it in the
same style as the existing v2→v3 note — say what changed and why v4 content should not
be pooled with v3. Nothing backfills older rows; that is correct and deliberate (see
the comment already there).

---

## PHASE 5 — Smoke run before anything at scale

Generate **one** topic and read the output properly before committing quota to a batch.

```bash
docker compose exec -T api python -m spoin.generate_topics \
  "Formal Logic & Fallacies::Common reasoning errors and how to spot them"
```

That topic already exists with 0 cards, so it exercises the resume path rather than
minting a new topic. Then verify, in this order:

1. **Archetype tags are right.** Mermaid cards must tag `diagram`, never `code`:
   ```sql
   SELECT archetype, count(*) FROM card
   WHERE gen_meta->>'prompt_version'='4' GROUP BY 1 ORDER BY 2 DESC;
   ```
   Seeing `{code}` on a card whose body holds a ` ```mermaid ` fence means the
   `content/archetype.py` fix regressed. It also breaks the per-tier quota loop
   (`pipeline/state.py`'s `_card_matches_type`) and the feed's diversity ranking.
2. **Retrieval actually fired.** Search the worker logs for the candidates block, and
   confirm the offered art is topically plausible — not random, which is what a
   `hash` embedder produces (PHASE 1).
3. **Rejections are honest.** Count `malformed mermaid diagram:` failures. A handful
   is the check working. A flood means it is too strict — loosen
   `_mermaid_structural_issue`, do not disable it.
4. **Look at the cards in the actual feed**, on a phone viewport. Diagrams should
   render as drawn graphs, roughly square; ASCII scenes should be varied in form, not
   seven variations of one joke; no card should show the same visual twice.
5. **Quota accounting held.** Re-read `docs/adr/0065`'s distinction — a run that "hit
   quota" may have hit a provider outage. Check which of the three
   `QuotaExhaustedError` subclasses appears, if any.

---

## PHASE 6 — The real run

Only after PHASE 5 looks right. **Generation writes to `spoin_db`, which is real
production content — CLAUDE.md's database rule applies. Confirm scope with the owner
before starting: which topics, how many, and the expected quota spend.**

Existing entrypoints, both of which run generation as one batched pass:

```bash
make scan     # scan incomplete topics, run one generation pass
make worker   # one batch pass of the job-queue worker, then exit
```

There are 54 topics currently sitting at **0 cards** (`Number Theory`, `Topology`,
`Operating Systems`, `Docker`, `Calculus`, …) — the natural v2 corpus. Write the run up
as `docs/architecture/generation-pipeline-run-7-benchmark.md`, following the six
existing benchmark docs, and **keep "rejected" and "failed" as separate counts** —
CLAUDE.md is explicit that folding them together makes a quota-exhausted run look like
a content-quality catastrophe.

---

## Open decisions that need the owner — do not guess

1. **ADR-0067 vs ADR-0068** (PHASE 3c) — pictorial-only, or form-free?
2. **Every `ASK` from the curation pass** (PHASE 2) — mostly alcohol/tobacco, mild
   innuendo, religious iconography, weapons.
3. **Scope of the first v4 run** (PHASE 6) — all 54 empty topics, or a subset?
4. **Whether the "v1" corpus label in the backup filename should match
   `prompt_version`** — it does not today (the dump contains v1+v2+v3 content mixed).
   Suggest naming the dump by date and corpus state, not by a version number that
   means something narrower.

---

## What NOT to do

- **Do not skip PHASE 0.** Every later phase changes generated content.
- **Do not run generation with `SPOIN_EMBEDDER=hash`.** It fails silently and wastes
  the entire run's quota on garbage candidates.
- **Do not backfill `prompt_version` onto existing rows.** v1 is v1 by absence and the
  code documents that deliberately; a bulk `UPDATE` on real content to record what the
  absence already says is exactly what CLAUDE.md's database rule prohibits.
- **Do not re-seed, wipe, or "reset" any topic** to make a test cleaner. Ask first,
  every time, including when it would obviously be easier.
- **Do not paste the whole ASCII library into a prompt.** It is ~53k lines; that is
  what the retrieval step exists to avoid.
- **Do not tighten the mermaid shape thresholds before seeing real output** (PHASE 3a).
- **Do not edit `apps/helpers/*.txt` and assume generation changed.** Sync the packaged
  copy (PHASE 2).
