# ADR-0076: Report a card, and an operator-triaged repair lane

- **Status:** Accepted
- **Date:** 2026-08-30
- **Operator lane replaced (2026-10-12, task 0045):** reports keep their shape, but each one
  wakes the frog of the card's topic, which judges it and writes the new version
  ([ADR-0106](0106-typescript-on-hono-and-the-authoring-harness.md)). The admin repairs page
  and its delete, fix and remake go in Phase 9.
- **Deciders:** Anubhav

## Context

Cards are generated once and shared by everyone (overview.md). A structurally
broken card — mangled ASCII, a code fence on a non-technical card, a diagram that
renders to nonsense, a caption missing under a diagram (F3's unshipped half) —
therefore reaches every reader of that topic, and today there is no path to flag
one or fix it short of editing the row by hand (which CLAUDE.md gates on owner
approval anyway).

The finish-line plan (B14) proposed: a reader flags a card, and at a threshold
(two independent reports, or one from the owner) it goes back through an automated
structure-only repair pass that is *forbidden to change meaning*, verified by a
byte-exact diff of the fence-stripped body.

The owner replaced the automated half. The failure mode that kills a "repair only
the structure" prompt is that an LLM asked to fix an ASCII scene will also reword
the sentence next to it, and a purely mechanical diff either rejects a good fix
for touching a comma or passes a bad one that stayed within the fences. Rather
than tune that tradeoff, **a human is the gate**: every reported card lands on an
operator page, and the owner chooses per card between *delete*, *fix* (with
optional written guidance), and *remake* (regenerate from a required brief). The
automated pass still exists — it is what *fix* and *remake* run — but it never
fires on its own and its output is judged by a person, not only by a diff.

Two mechanisms this is the first real user of:

- **Card families.** `card.py` describes `family_id` / `version` / a partial
  unique index enforcing one `ACTIVE` row per family, and a `SUPERSEDED` status —
  all so "improve a card" mints a new row instead of mutating one that engagement
  data is attached to. Nothing has ever written a `version > 1` row. Repair does.
- **An operator surface.** `/dev/*` is the only thing like it; there is still no
  admin role (task 0035). The repair page has destructive actions, so it is
  gated the same placeholder way (`env != "production"`) and task 0035 now points
  at it.

## Decision

### Reporting

**`card_report`** — `(id, card_id, user_id, reason, note, created_at)`, unique on
`(card_id, user_id)` so one account reports a given card at most once. `reason` is
a native enum **`CardReportReason`** = `art | diagram | code_block | formatting |
other`, kept as an enum for the same reason `RejectionStage` is: per-reason counts
are a `GROUP BY`, not string parsing. `note` is optional free text — the reader
saying what looks wrong.

**`POST /cards/{card_id}/report`** — body `{reason, note?}`. Idempotent: a second
report from the same user updates their existing row rather than 409-ing. Guest
users may report (unlike custom-topic requests — a report costs nothing and needs
no durable account). Not an `EngagementEvent`: a report is a moderation signal
with its own table and lifecycle, not a ranking input.

The client puts a small **flag** control in the card action row next to Ask AI
(`Card.tsx`), opening a one-tap reason picker with an optional note field.

### `CardStatus.RETIRED`

A new enum value (migration). `REJECTED` means "the gate threw this draft out";
`SUPERSEDED` means "a newer version in this family replaced it". Neither fits "was
live, an operator pulled it". The feed candidate query already filters
`status == ACTIVE`, so `RETIRED` drops the card from every feed with no query
change; the row and its engagement history stay for audit.

### The repair job

**`GenerationJob` gains `kind`** (`"generate"` default | `"repair"`) and a
nullable **`card_id`** FK. The single partial-unique coalescing index splits in
two: `(topic_id) WHERE kind='generate' AND status IN ('pending','running')` keeps
"one outstanding generate job per topic"; `(card_id) WHERE kind='repair' AND
status IN ('pending','running')` gives "one outstanding repair per card" while
letting a topic have any number of repairs in flight for different cards.

**`card_repair`** carries the payload and the audit trail, 1:1 with the job:
`(id, card_id, job_id, mode, guidance, source_image, status, result_card_id,
created_at, resolved_at)`. `mode` is `fix | remake`. `guidance` is the owner's
text — optional for `fix`, **required** for `remake`. `source_image` is the PNG
the admin page rendered (a `LargeBinary`, `deferred=True` like `User.avatar_image`
— a card screenshot at 2× is well under a megabyte, needed once, and never read
on a hot path). `status` is `pending | running | done | failed`; `result_card_id`
points at the new family version once one exists.

### The operator surface

Mounted only when `env != "production"`, same gate and same task-0035 caveat as
`/dev/*`.

- **`GET /admin/repairs`** — reported cards not yet resolved, each with the full
  card, its reports (`user_id`, `reason`, `note`, `created_at`), and any
  in-flight/failed `card_repair` row.
- **`POST /admin/repairs/{card_id}/delete`** — `card.status = RETIRED`, reports
  marked resolved. No LLM, no job.
- **`POST /admin/repairs/{card_id}/fix`** — multipart: `image` (PNG, type-sniffed
  from magic bytes, size-capped) + `guidance?`. Creates `card_repair(mode='fix')`
  + `GenerationJob(kind='repair', card_id=…)`.
- **`POST /admin/repairs/{card_id}/remake`** — multipart: `image?` +
  `instructions` (**required**). Creates `card_repair(mode='remake')` + the job.

The admin page renders each card to a PNG **client-side**, with the same
`html-to-image` `toBlob` call the share button uses (`Card.tsx:copyCardImage`),
and uploads it. The worker never renders — no headless browser in its image.

### What the worker does

`_run_job` branches on `job.kind`. `kind='generate'` is unchanged.
`kind='repair'` calls `run_card_repair`, which reads the `card_repair` row and:

**`mode='fix'`** — one call to a new interface method
**`ContentGenerator.repair_card_structure`** (single-item; multimodal). Inputs:
the rendered image, the card's current `title` / `summary` / `body` /
`visual_slots`, the aggregated reporter notes, and the owner's `guidance` — the
last two clearly delimited as **data to act on, never instructions to follow**,
the same discipline `grade_free_text` documents. Output: corrected
`{title?, summary?, body, visual_slots}`, plus a one-line caption for **every**
in-body mermaid fence (this is where F3's diagram-caption half lands — the schema
requires it, so a repaired card cannot come back with an uncaptioned diagram).

Then **deterministic *structural* checks only** — ASCII within the ADR-0021
column budget, mermaid within the ADR-0067 shape budget, `classify_archetype`
sane for the topic (no code fence on a non-technical card), every diagram
captioned. **No fence-stripped-body meaning-lock**: the owner's guidance is
allowed to fix a wrong sentence, and the owner reviewing the result is the check
that the meaning is still right. On pass: mint `version = old.version + 1`,
`status = ACTIVE`, same `family_id`; set the old row `SUPERSEDED`; both in one
transaction (the partial unique index enforces the single-active invariant).
`card_repair.status = done`, `result_card_id` set. On fail: `card_repair.status =
failed` with the reason, job `failed`, card stays as-is and reappears on the
admin page.

**`mode='remake'`** — fresh content from the owner's `instructions`, so it runs
the **full pipeline path for one card**: `plan_cards(count=1)` with the
instructions as the brief, `generate_cards`, then the normal quality gate
(`gate.py`) exactly as generation uses it — a remade card is new content and
earns the same scrutiny a generated one does. Same family-versioning write on
success.

Repair jobs run in the existing priority-ordered, one-at-a-time `run_once` loop
(ADR-0073). They default to a lower `priority` than demand-triggered generation,
so a repair backlog yields to a user waiting on a new topic. The owner paces how
many exist by how fast they triage.

### Enforced twice

`tests/test_architecture.py` gains a rule: `run_card_repair` (and the persistence
it calls) may only write a `Card` whose `family_id` equals the reported card's —
a repair can never fork an unrelated family or touch another card. Plus behaviour
tests on the fix/remake write and the structural checks.

## Consequences

**Easier**

- A broken card has a path off everyone's feed that isn't a hand-edited row.
- F3's diagram captions ship as part of a pass that already exists to touch old
  cards, instead of a separate backfill.
- Family versioning finally has a user, so the `SUPERSEDED` / one-active-per-family
  machinery gets exercised and tested rather than staying theoretical.

**Harder**

- A second job `kind` in a worker that ADR-0073 deliberately kept single-file and
  sequential. Repair and generation share the loop and the quota ladder, so a
  large repair batch and a generation run compete; the mitigation is priority and
  the fact that repairs only exist when the owner made them.
- PNG bytes in Postgres. Bounded (one screenshot, deferred column, deleted with
  the `card_repair` row on resolution) but it is binary in the primary store,
  which the B7 plan is otherwise trying to avoid.
- The operator surface is `env`-gated, not role-gated — it has *destructive*
  actions now (retire a card, spend LLM calls), so task 0035 matters more than it
  did for a read-only quota view.
- "Fix" can change meaning. That is deliberate (the owner asked for it) but it
  means the safety is entirely the owner's review, with only structural checks
  automated — a rushed approval ships a reworded card to everyone.

## Alternatives considered

**Automated repair at a report threshold (the plan's original).** Rejected by the
owner: an LLM told to fix only structure will reword prose, and a mechanical
fence-stripped diff either rejects good fixes for touching punctuation or waves
through bad ones that stayed inside the fences. A person per card avoids tuning
that knob at the cost of not scaling — acceptable at current volume, revisited
below.

**A separate `card_repair_job` table and a second worker claim loop.** More
isolation between repair and generation. Rejected: the owner chose the `kind`
column, and the two partial-unique indexes give per-card repair coalescing
without a second table's worth of claim/lease/retry code to keep in step with
`GenerationJob`'s.

**Worker renders the card image (headless Chromium / screenshot the
`/share/{id}` page).** Rejected: a browser in the worker image is a heavy new
dependency for something the admin page — which already has the card in the DOM —
can produce with the `html-to-image` call that already exists.

**Hard meaning-lock on "fix" (fence-stripped body must be byte-identical).**
Rejected: then correcting a single wrong word forces a full "remake" with a
written brief, which is disproportionate. The owner's guidance text is explicitly
allowed to direct a prose change, and the owner's review is the check.

## Revisit when

- Repair volume exceeds what one person can triage. The narrow, provably-safe
  cases (an ASCII scene that overflows its column budget → redraw and re-check,
  no prose touched) could then get an automated sub-lane with the strict diff,
  leaving only the ambiguous reports for a human.
- Task 0035's admin role lands — the `env` gate on `/admin/repairs` comes off and
  the destructive endpoints move behind the role check.
  > **Done 2026-10-11** ([ADR-0106](0106-typescript-on-hono-and-the-authoring-harness.md),
  > task 0045): every `/admin/*` route answers 403 without the admin role, in every
  > environment.
- If PNG-in-Postgres shows up as a real size problem, move `source_image` to the
  same object store B7 introduces for uploaded material.
