# Handoff: build the v2 generation pipeline

> Written 2026-09-06, at the end of a design session. Everything below is decided — the
> owner made these calls, they are not defaults. **Do not re-litigate them.** Build.

Read [`CLAUDE.md`](../../CLAUDE.md) first, then
[`docs/architecture/generation-pipeline-v2.md`](../architecture/generation-pipeline-v2.md),
which is the design this handoff asks you to implement, and
[`docs/architecture/authored-curriculum.md`](../architecture/authored-curriculum.md) for why
the curriculum stops being generated.

## Where things stand

**Tasks 1-9 are built (2026-09-06).** `make check` is green -- 602 spoin tests, 78 frog,
`ruff` + `mypy --strict` clean across both packages. Tasks 10 and 11 are what remains,
and both need a real run: task 10 is that run plus reading its JSONL, task 11 is the ADRs
written from what it showed.

- **`spoin_db_2`:** unchanged by this work. The migration `c1d2e3f4a5b6`
  (`topic.curriculum_corpus_version`, nullable) is written and **not yet applied** --
  run `make migrate`.
- **`the_spoin_universe`:** the curriculum tables are a new frog revision,
  `d4e5f6a7b8c9`, also **not yet applied** -- run `make universe-migrate`.
- **`SPOIN_MISTRAL_API_KEYS` is not set anywhere yet.** `SPOIN_GENERATOR=hybrid` needs
  it; without it `MistralClient.__init__` refuses loudly rather than falling back.
- **No curriculum has been authored yet**, so nothing has been projected and no topic is
  generatable. That is the next step, and it is authoring work, not code.
- Uncommitted and **not yours**: `AGENTS.md`, `GEMINI.md`, `.agents/rules/*`. Leave them.

### The path, end to end

```bash
make migrate && make universe-migrate          # once: both new revisions
# author docs/the_spoin_universe/curricula/<topic>/curriculum.md
make curriculum-check                          # pure: no network, model or database
make curriculum-ingest                         # -> curriculum tables in the universe
make curriculum-project                        # -> Topic / Subtopic rows in spoin_db_2
python -m spoin.generate_topics "<topic>"      # SPOIN_GENERATOR=hybrid for Mistral
```

## What to build, in order

From [generation-pipeline-v2.md](../architecture/generation-pipeline-v2.md) § 6. Tasks 5 and
6 are independent of 1–4 — **land them first if you want the cheapest win**, because
persisting drafts immediately makes every later experiment cheaper to lose.

| # | Task | Status |
|---|---|---|
| 1 | Curriculum contract validator + `make curriculum-check` | **done** -- `frog/curriculum/{contract,runner}.py` |
| 2 | Curriculum tables in `the_spoin_universe` + ingestion | **done** -- revision `d4e5f6a7b8c9`, `make curriculum-ingest` |
| 3 | Projection into `Topic` / `Subtopic` | **done** -- `spoin/curriculum/projection.py`, `make curriculum-project` |
| 4 | Author Rust's curriculum end to end and project it | **owner's** -- nothing authored yet |
| 5 | Persist drafts immediately; the gate flips status in place | **done** -- `_persist_drafts`, gate updates rows |
| 6 | `MistralContentGenerator` -- httpx, semaphore at 5, JSONL logging | **done** -- `generation/mistral.py` |
| 7 | `HybridContentGenerator` routing per ADR-0090's table | **done** -- `generation/hybrid.py`, `SPOIN_GENERATOR=hybrid` |
| 8 | Delete `generate_curriculum` and its prompts; rewire `resolve_and_plan_topic` | **done** |
| 9 | CLI over an authored topic | **done** -- `python -m spoin.generate_topics "<topic>"` |
| 10 | Run Rust end to end, read the JSONL, write up what Mistral actually does | open -- needs 4 and a key |
| 11 | ADRs from what 10 showed | open |

**Task 4 was meant to come before task 8** -- prove the authored path on a real topic
before deleting the generated one. It did not: 8 landed first, on the owner's
instruction to finish the build. The risk that ordering was protecting against is real
but bounded -- `resolve_and_plan_topic` now refuses a topic with no projected
curriculum, so if task 4 turns up something the format cannot express, the failure is a
loud refusal at the start of a run rather than a bad corpus. The projection is a plain
upsert and the format is a file, so both are cheap to change.

## Decisions already made — do not re-open

**The curriculum is authored, never generated.** The owner writes it. No LLM call decides what
Spoin teaches or in what order. `generate_curriculum` gets **deleted**, not grounded.

**Contract:** [`antigravity-curriculum-authoring.md`](antigravity-curriculum-authoring.md) is
the format — one `curriculum.md` per topic under `docs/the_spoin_universe/curricula/<topic>/`,
YAML front matter, no prose body. Per subtopic: `title`, `description`, `prerequisites`,
`sources`, and per tier `target_cards` (5–25) and `card_types` quotas summing to it.

**Curricula are parsed, never chunked or embedded.** They go into their own tables in the
universe, not `document`/`chunk`. Teaching structure is not knowledge, and syllabus
scaffolding in the retrieval pool would let cards ground on it.

**Drafts persist immediately.** Write `Card` rows at `status=draft` the moment the writer
returns; the gate flips them to `active`/`rejected` in place. `CardStatus.DRAFT` already
exists for this, the feed already filters on `active`, and `uq_card_family_id_active` is a
partial index so drafts cannot collide — **no migration needed**. A rejected draft keeps its
row *and* still writes `rejected_card`; both loops stay.

**Provider split** is ADR-0090, unchanged: prose on Mistral, verdicts on Gemini.

| Setting | Value |
|---|---|
| Model | `ministral-8b` |
| Keys | 1 now; the client takes a list and round-robins |
| In-flight cap | **5** |
| Transport | raw `httpx`, `POST /v1/chat/completions`, `response_format: json_schema` strict |
| Parsing | the existing `_LenientWireModel` Pydantic models |

**Do not port the Gemini apparatus.** No key pool, no box leasing, no quota ledger, no load
balancer, no send-gap pacing, no rung ladder. Mistral gets a semaphore, a send path and
retry. The Gemini machinery stays untouched — the thinkers still use it.

**Log everything, classify nothing.** Per-run JSONL: status, **all** response headers,
latency, in-flight count at send, prompt size, usage, request id, and **full response bodies
on success as well as failure**. We do not know Mistral's error codes or failure shape, so
capture first and derive the taxonomy from real runs. Keep a one-line-per-call summary in the
main log so a terminal stays readable.

**On failure:** retry with backoff, then fail that item and continue — counted as a *call
failure*, never a rejection. **No cross-provider fallback**; a Mistral outage must stay
visible as a Mistral outage.

**Trigger:** a CLI over an authored topic, run locally (ADR-0094).

## Hard rules

- **Never** `docker compose down -v`, `make clean`, or `docker volume rm`. One volume holds
  four databases including the corpus.
- Reads on `spoin_db_2` are fine. Writes, schema changes, `alembic downgrade` — ask first.
- `make test` (→ `docker compose --profile test run --rm test`) is safe; it uses
  `spoin_db_test`.
- Cockroach/Neon portability work is remote-only, on a throwaway DB the owner provisions.
- `spoin` imports `frog`, never the reverse — enforced by ruff and an AST test. **The
  curriculum validator lives in frog and therefore cannot import spoin's enums**; mirror the
  vocabularies by value, as `DocumentScope` already does for `topic.is_survey`, and say so in
  a comment.

## Traps that will cost you time

- **The `test` compose service runs the WHOLE suite regardless of the paths you pass it**,
  and it **exits 0 even when tests fail**. Read the summary line; never trust the exit code.
- The working tree is **CRLF**. Scripted `str.replace` over repo files no-ops against `\n`
  patterns. Normalise on read, restore on write. `canon.py` and a few docs are LF — detect
  per file, do not assume.
- **The Bash tool collapses `\\` inside heredocs**, so a pattern containing a
  backslash-newline silently fails to match. Write patch scripts to a file in the scratchpad
  and run them. This will bite you; it bit twice last session.
- `MSYS_NO_PATHCONV=1` is not optional for container paths under Git Bash.
- `make` is not on PATH in the Bash tool. Use
  `docker compose run --rm --no-deps api ruff check src` / `mypy src` directly.
- `ruff format src alembic` reformats 14 historical migrations. `make lint` covers
  `src tests` only — don't widen it.
- Alembic does not autogenerate `CheckConstraint`s — write those by hand.
- Constraint names: pass the short form; the metadata convention adds the `ck_<table>_`
  prefix.
- Every autogenerated migration proposes dropping three `server_default`s on
  `ask_conversation.status`, `ask_message.on_topic`, `generation_job.kind`. That is task 0041,
  unrelated drift — strip those lines.
- `test_canon_preambles.py` enforces a **1200-token ceiling** per pinned preamble. Editing
  prompt canon can blow it; condense rather than raising the ceiling — that budget comes
  straight out of the grounding budget.

## How the owner wants to work

**Ask before deciding anything inside a task** — scope, mechanism, constants — with a
recommendation, in one line, before writing the code. Flagging a decision after the code
exists moves it to where it is most expensive to change.

**Do not re-ask what they have already approved.** Confirm a destructive action once, with the
blast radius, then act.

**Do not invent risks and then build safeguards for them.** There are no users and no
production data. Before writing a guard, state the failure it prevents and check the system
can actually reach that state. If one person authors both sides of an interface, mismatch
between them is not a system failure mode. This has now gone wrong twice — a round cap in
August, two invented failure modes in the curriculum design yesterday.

**End on the task at hand.** No trailing roundups of unrelated open threads, other tracks'
uncommitted work, or leftover follow-ups. Raise something outside the current thread only if
it blocks the work, or if asked.

**Match effort to stakes.** A small mechanical question does not need a design discussion.

## Where the corpus track is

Antigravity authors knowledge, images and curricula, supervised by the owner, in a separate
session. Its contracts:

| Delivery | Contract |
|---|---|
| Knowledge | [`antigravity-corpus-authoring.md`](antigravity-corpus-authoring.md) — now carries ADR-0100's epistemic fields |
| Images | § 10 of the same file, plus [`next-image-sourcing.md`](next-image-sourcing.md) |
| Curricula | [`antigravity-curriculum-authoring.md`](antigravity-curriculum-authoring.md) |

Per topic the order is **knowledge → images → curriculum**, and the curriculum step is
"propose one structure with brief reasoning, then ask the owner to proceed or change".

The corpus `_canon/*` documents state the rules that `generation/prompts/canon.py` condenses
into prompt preambles. Those two can drift; the owner keeps them aligned by updating
Antigravity's rules directly, and does not want a guard built for it.
