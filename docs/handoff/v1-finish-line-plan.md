# The v1 finish line: build plan, review plan, deployment plan

**Written:** 2026-08-30 — **Owner:** Anubhav — **Status:** proposed, not started

This is the plan for closing out spoin v1. It covers three phases in order:

1. **Build** — the frontend and backend items on the finish-line list.
2. **Review** — one whole-codebase quality pass, run as a defined process rather
   than "read everything and hope".
3. **Deploy** — hosting options for API, worker, web, and database, priced for
   free-tier-now and real load later, including an honest answer on Kubernetes.

Read [CLAUDE.md](../../CLAUDE.md) first. Every item names the ADR or task it inherits
from. Where an item contradicts an accepted ADR, that is called out as needing a
superseding ADR rather than silently done.

---

## Session progress log

Read this before Phase 0 — it is more current. Append to it, don't replace it, as more
lands.

**2026-08-30, session 1 — Wave 1 shipped and verified live** (not just typechecked —
actually clicked through in a browser against the running dev stack):

- **F2** (like lags the screen) — fixed in [lib/refresh.ts](../../apps/web/lib/refresh.ts).
  `invalidate()` now defers for any view that isn't the active one; `active` threaded
  through Feed/LikedView/SavedView/NotesView/ProfileView from `AppShell.tsx`. Verified via
  network trace: liking off-screen produced zero refetch; opening that view afterward
  produced exactly one, with the new data.
- **F9** (adding a topic refreshes the feed) — fixed. `AppShell.tsx`'s `onFollowed` only
  invalidates the feed when the topic already has cards; `GenerationProgressPanel.tsx`
  invalidates once its poll observes `completed`. Not exercised through a real generation
  run (that spends live quota) — worth one real end-to-end pass before calling this fully
  proven.
- **F1** (progress-card hover bug) — root-caused and fixed. `.progress-row` had
  `transition: all`, which animated `border-radius` from 0→8px on every hover, visibly
  morphing the highlight's corners. Scoped to `transition: background` in
  `app/globals.css`. Confirmed via computed style in the browser after a container
  restart (Windows bind-mount doesn't reliably hot-reload CSS in this dev setup — a real
  container restart, not just a page reload, was needed to see the fix take effect;
  worth remembering for the rest of this project).
- **Bonus, found during F13 verification, not on the original list**: `offerUndo` was
  being called from inside `setRows`'s functional updater in all three of LikedView,
  SavedView, NotesView — a genuine React violation ("update UndoToast while rendering
  LikedView"), not a lint nit. Fixed all three with a `rowsRef` mirror so the undo offer
  runs as a plain call in the event handler. Verified clean in the console across all
  three views' remove→undo cycles.
- **F3** (one-liner caption under art/diagrams) — the ASCII-art half shipped: `Card.tsx`'s
  `AsciiArt` now renders `visual_slots.alt` as a visible `.card-visual-caption` under the
  art, only when the server actually sent one. Verified live against a real card
  ("Financial Literacy & Investing Mechanics" topic has good examples). **In-body mermaid
  diagram captions are still unshipped** — no caption source exists for those yet; the
  plan folds that into B14's repair lane rather than a separate backfill.
- **F11 / F13** — verified already-shipped behavior still works (no-color opt-out, 5s
  undo toast in all three collection views).
- **F4 / F5** — design work only so far, **not implemented**. See those sections below —
  the design direction changed mid-session (see "still to do" just below) and needs to be
  finished and confirmed before any code.

**Environment note for the next session:** the docker stack (`db`, `api`, `worker`, `web`)
was found already running from a previous session; the `api`/`worker` containers had
stopped externally at some point (not from anything in this session) and were restarted
with `docker compose up -d api worker` — non-destructive, no data touched. If things look
dead, check `docker ps -a` before assuming something is broken.

**What's still open from this session, in priority order:**

1. **F4/F5 need a second design pass with REAL content, not illustrative placeholders.**
   The first draft (canvas below) proved out the *interaction* — 3-row/5-row fixed-height
   scrolling grids, hover-reveal edit/delete on saved items, the font import's inline
   "name it" row instead of a popup — using invented preset names to fill the grid. The
   owner does not want placeholders: **the actual preset theme list and the actual preset
   font list need to be curated for real**, wide enough to cover genuinely different
   aesthetic tastes people actually have — not just variations on one look. See F4/F5
   below for what "wide enough" means in practice. This is real curatorial work, not a
   mechanical follow-up — budget real thought for it, and check both lists render
   correctly (contrast, legibility) before calling it done.
2. Once the presets are real, get the owner's sign-off on the design, *then* build F4/F5
   against the server-side preferences store (already decided, see F4's entry).
3. Continue down Phase 1 Wave 2 / Phase 2 per the rest of this doc.

**Design canvas so far:** [Appearance Pickers](https://claude.ai/code/artifact/05a4e6ab-f296-44c8-9672-71885802deea)
— theme dropdown, font dropdown, and the theme edit modal, all matching the app's real
Notebook-palette tokens. The interaction design (scroll containers, hover affordances,
inline font-naming row, no-popup layout) was confirmed and carries forward unchanged.

**2026-08-30, session 2 — F4/F5 curated AND built.** Branch `feat/v1-finish-line` (off
`origin/main`, pushed). Commits: preset curation → ADR-0070/0071 → API → web → task 0033.

- **Curation.** 11 themes (5 shipped + Daylight / Terracotta / Meadow / Fog / Ember /
  Amethyst) and 20 fonts (5 shipped + 15 across serif / slab / sans / rounded / display /
  mono). Every new theme contrast-checked in a browser (`--fg` on `--bg` ≥ 12.7:1,
  `--accent` on `--bg` ≥ 4.9:1). Source of truth:
  [`docs/design/mockups/appearance-pickers.html`](../design/mockups/appearance-pickers.html).
  Theme dropdown gained a "Create your own theme" row mirroring "Upload a font".
- **[ADR-0070](../adr/0070-server-side-appearance-preferences.md)** (amends 0045) —
  palette + saved themes + font + imported fonts move to `user_preference` /
  `user_font`, `localStorage` demoted to a pre-paint cache reconciled against `/auth/me`.
  **[ADR-0071](../adr/0071-drop-font-keep-revert.md)** (amends 0037) — FontPicker drops
  Keep/Revert. Both Accepted.
- **API.** `GET/PUT /profile/me/preferences`, `GET/POST/GET{id}/DELETE{id}
  /profile/me/fonts`; `preferences` on `/auth/me`. Per-user font scoping enforced twice
  (dep + `test_architecture.py`). 13 new tests, `make check` green for touched files.
  Migration `f0a1c2b3d4e5` (two additive tables) **applied** to the running DB
  (`spoin_db_2` — note: `.env` points the stack there, not `spoin_db`; CLAUDE.md's
  "`spoin_db` is the only database" is stale against the local `.env`). API smoke-tested:
  defaults, PUT round-trip, `/auth/me` embed all working.
- **Web.** `lib/preferences.ts` (client source of truth), `PreferencesSync` (reconcile),
  rewritten `ThemePicker` / `FontPicker` / `CustomThemeModal`, `CustomFontModal` deleted,
  6 palettes + Newsreader wired in `globals.css`, layout inline script learns
  `custom:<id>` + migrates the legacy `custom` slot. `tsc --noEmit` clean; web container
  compiles clean.
- **Not yet done:** owner's manual frontend test pass (checklist handed over). The
  Wave-1 working-tree changes (`generation/pipeline/*.py`, several `apps/web/components/*.tsx`,
  `lib/refresh.ts`) are still uncommitted and untouched.
- **Task [0033](../tasks/0033-grow-the-curated-ascii-library-over-time.md)** added — the
  standing "keep growing the curated ASCII library" todo, after task 0030's verify pass.

**Next:** owner tests F4/F5 in the browser; then continue Phase 1 Wave 2 (F6 rename, then
its `CollectionView` rework) and Phase 2 Tier 1 (B2/B8, B4).

**Uncommitted changes as of this log** (`git status` in `apps/web`, plus pre-existing
unrelated changes already in the working tree before this session started — do not
attribute `generation/pipeline/{nodes,persistence,state}.py`,
`docs/notes/topic-queue.md`, or `apps/api/tests/test_technical_topic_guard.py` to this
session, they predate it): `app/globals.css`, `components/AppShell.tsx`,
`components/Card.tsx`, `components/Feed.tsx`, `components/GenerationProgressPanel.tsx`,
`components/LikedView.tsx`, `components/NotesView.tsx`, `components/ProfileView.tsx`,
`components/RequestTopicBox.tsx`, `components/SavedView.tsx`, `lib/refresh.ts`. Nothing
has been committed yet — the user has not asked for a commit. `tsc --noEmit` is clean
across the whole frontend as of the last check.

**2026-08-30, session 3 — F4/F5 signed off; F6 rename + B2/B8 + B4 shipped.**

- **F4/F5 polish verified.** The three `1618822` items hold — but the web
  container was serving **stale JS** (pre-`1618822`), so the theme-modal-reopen bug
  "reproduced" until `docker compose restart web`. Windows bind-mount HMR is
  unreliable (session-1 already flagged this for CSS); it applies to `.tsx` too —
  **restart the web container after any component edit before trusting the browser.**
  Found + fixed a follow-on: `1618822`'s `onOpenChange` fired inside
  `PickerDropdown`'s `setInternalOpen` updater → React "setState during render of
  another component" on every dropdown open/close. Moved it to a transition-watching
  effect — commit `48b64ba`. Console clean after.
- **F6 rename shipped** — `1b2cbf7`. Sidebar label + the `SavedView` eyebrow (all 4
  states) now say "Revisit". Copy only: `saved` view key / `RefreshScope` /
  `card_bookmark` / `api.saved*` untouched; the card action is still "Save". The
  leftover "SAVED CARDS" / "Search saved cards…" / "Removed from Saved" microcopy
  was entangled with the pre-existing uncommitted `SavedView.tsx` Wave-1 diff, so it
  goes to the rework (task 0034) which rewrites that file anyway.
- **F6 rework shipped** — `be96077`. Owner's call: *"why do you need design for F6?
  It's literally the same as Liked and Notes"* — right. No `/design` canvas; the
  three collection views were already the same `.collection-*` shell, and Saved's
  only real difference was a bespoke 2-col tile grid + card-overlay portal.
  `SavedView.tsx` is now a near-mirror of `LikedView.tsx` (vertical `Card` list,
  new `.collection-list` class, same undo wiring, bookmark semantics). ~150 lines
  of component + ~200 of CSS deleted (the `.saved-tile*` CSS is dead now — task
  0034 sweeps it). **[ADR-0072](../adr/0072-revisit-drops-its-bespoke-grid.md)**
  (amends 0046) records it. This supersedes SavedView's uncommitted Wave-1 diff.
  **[Task 0034](../tasks/0034-collectionview-rework-saved-notes-liked.md)** is now
  just the shared-`CollectionView` extraction (unblocked — all three views
  identical) + the dead-CSS sweep; no ADR/design gate left. Verified live in
  Obsidian: card list matches Liked, empty state matches, unbookmark→undo works.
  (`b598ff3` was the earlier "defer" doc commit, now superseded.)
- **B2/B8 shipped, end to end** — `1f72fc6` (API) + `3c699fb` (web), design-reviewed
  first. `POST /topics/batch` + `TopicsService.request_topics_batch`: one
  `validate_topic_names` + one `match_and_create_topics` call for the whole list,
  per-row outcomes (`generating` / `subscribed` / `already_subscribed` /
  `rejected`+detail), capped at `Settings.custom_topic_batch_max` (5), guest-gated,
  7 tests. `RequestTopicBox.tsx` is now a rows form — name + optional description
  each, `+` up to 5, per-row remove, one batched submit, per-row outcome view
  after. The rewrite keeps the F9 `onFollowed(topic, hasCards?)` contract so it
  cleanly supersedes the file's uncommitted Wave-1 diff. **[Task 0032](../tasks/0032-batch-topic-requests.md)
  is DONE.** Verified live (rows/add/remove/counters/disabled, guest 403, per-row
  results via a stubbed batch response).
- **B4 shipped, end to end** — `99d3fb9` (API) + `6134ee4` (web).
  `GET /admin/quota` → `read_quota_status` (`generation/quota_report.py`,
  read-only): one cell per `(key, model)` with daily spend / ceiling /
  `exhausted_at` / `cooldown_until`, plus `model_unavailable` rows. ADR-0065's
  three conditions kept as **separate counts** (`cells_daily_exhausted` /
  `cells_minute_throttled` / `models_parked`), never one boolean. `env !=
  "production"` gated like `/dev/*`; real admin-role gate is
  [task 0035](../tasks/0035-admin-role-and-production-admin-surface.md). `dev.py`
  docstring corrected. Frontend is a plain dev-only Next route
  `apps/web/app/admin/quota/page.tsx` (no shell view, reached by URL): three
  rollup tiles kept separate, per-pool model rows with a 33-square key strip
  (shaded by spend, ringed if throttled, hatched if parked), parked-models list.
  4 API tests; verified live against the running DB (198 cells, all zero today).
- `make test` green (451). `mypy --strict` green (86 files). New API files pass
  `ruff` + `ruff format`. `packages/api-types/schema.d.ts` is gitignored (CI
  regenerates); regenerated locally to confirm it's clean.
- **Still untouched:** the pre-existing Wave-1 working tree
  (`generation/pipeline/*.py`, `components/*.tsx`, `lib/refresh.ts`,
  `docs/notes/topic-queue.md`, `tests/test_technical_topic_guard.py`). `git status`
  stays dirty from these — expected. Note `test_technical_topic_guard.py` currently
  fails `ruff check` (unsorted imports) — it's the owner's, not this session's.

- **Design canvas** (owner-approved, built from) — B2/B8's rows form + B4's quota
  panel, Obsidian theme:
  https://claude.ai/code/artifact/c85d9452-76bd-4264-a484-13c60eb3ed9f
- **Shell right-gap fix** — `49a6c65`. Owner: *"all screens have a visible gap on
  the right"*. `.app-grid` was `350px | 640 | 350px`, `max-width: 1400` → a fixed
  ~260px void each side on any wide screen. Side tracks are now
  `minmax(350px, 1fr)`, max-width 1720: centre thread still centred & capped at
  640 (feed reading width unchanged), rails spread to the edges. On 1920: right
  void ~289→~130px, right rail +~140px usable width. Only the `>=1401` breakpoint
  changes.
- **Two follow-ups from the owner after B2/B8 landed:**
  - **Generation is sequential now** — `9b9520e` / **[ADR-0073](../adr/0073-worker-runs-generation-jobs-sequentially.md)**.
    `run_once()` ran claimed jobs with `asyncio.gather`; it now runs them one at
    a time in `priority DESC, created_at` order. So a batch of topics added from
    the app generates in the order requested, one finishing before the next.
    Tradeoff (in the ADR): a pass takes ~N× longer, bursts spill to later cron
    passes; the fix if it bites is a *bounded* pool, not unbounded `gather`.
  - **Batch cap removed** — `dede0cb`. `custom_topic_batch_max` (5) + its 422 +
    the frontend `MAX_ROWS` guard were a defensive limit; the owner had them
    pulled. `POST /topics/batch` takes any non-empty list; `+ Add another` is
    always available. A deliberate ceiling stays task 0024's concern.

**Branch state:** `feat/v1-finish-line`, on top of session 2 — session-3 commits:
`48b64ba` `1b2cbf7` `b598ff3` `1f72fc6` `4edfc60` `99d3fb9` `a60e425` `be96077`
`a75ad9a` `49a6c65` `3c699fb` `6134ee4` `9b9520e` `dede0cb` (+ this log). **Pushed.**

**Session-3 net:** F4/F5 signed off + a follow-on fix; F6 done (rename `1b2cbf7` +
rework `be96077` / ADR-0072); B2/B8 done (API + rows form, then sequential
generation + cap removed); B4 done (API + panel); the shell right-gap fixed. New
docs: ADR-0072, ADR-0073, tasks 0034 / 0035; task 0032 closed.

**Untouched:** the pre-existing Wave-1 working tree — `generation/pipeline/*.py`,
`components/{AppShell,Card,Feed,GenerationProgressPanel,LikedView,NotesView,ProfileView}.tsx`,
`lib/refresh.ts`, `docs/notes/topic-queue.md`, `tests/test_technical_topic_guard.py`.
`git status` stays dirty from these — expected, they predate this effort. Note the
F6 rework (`SavedView.tsx`) and B2/B8 (`RequestTopicBox.tsx`) each superseded that
file's Wave-1 diff by carrying the equivalent change; the rest of Wave-1 is still
uncommitted and owner-owned.

**Next:** Phase 2 Tier 2 (B6 embedding topic colors → needs an ADR amending 0034;
B14 report-a-card repair lane → needs an ADR; B12/13 AskAI → needs an ADR), then
the Cockroach sequence (tasks 0016→0021), then B7 study material. Task 0034
(shared `CollectionView`) is unblocked and pickup-ready any time. Every new
frontend still goes through `/design` + owner sign-off (Phase 2.5); every
"Needs: an ADR" item gets one first, numbered from 0074.

**2026-08-30, session 4 — ADR-0074: one key per subtopic group; questions move to
a topic-wide phase.** Owner-driven design session; not on the Tier-2 list, it came
out of the question "why would 20 subtopics firing concurrently cause RPM failure?".

- **The answer was that it wouldn't, and the docs were lying about why.** ADR-0047
  deleted the global semaphore long ago; `max_concurrent_generation_calls` survived
  in `core/config.py` **read by nothing**, and `generation-pipeline.md` still claimed
  every call went through it. Both fixed — setting deleted, doc rewritten.
- **[ADR-0074](../adr/0074-key-per-subtopic-scheduling.md) (Accepted)** — a subtopic
  group claims ONE key for its whole card run (plan, every draft round, both gate
  passes, every redraft) and releases it at the end. **Parallelism = key count (33).**
  A group never borrows a claimed key; group K+1 waits. One caller per key is what
  makes an rpm violation structurally impossible rather than merely counted.
  Amends 0028/0065, **reframes** 0040/0047 (both stay — the ADR has a "what survives"
  section so a future session doesn't delete `cell_lock` as dead). Back-pointers
  added in all six ADRs + the README row.
- **Own-key-first ladder.** own 3.7 → own 3.6 → any unclaimed key's 3.7/3.6
  (least-spent) → own 3.5 → re-check → wait. `gemini-3-flash-preview` is a
  **reserve** (`gemini_thinking_reserve_rungs`, default 1): reached only when no key
  anywhere has daily room on an ordinary rung. **Contention waits, exhaustion
  descends** — the two waits are seconds vs. midnight UTC and must not collapse.
- **Ladder order regression fixed.** `gemini_thinking_ladder` led with 3.7 from
  ADR-0028 onward; commit `f2f63e5` (PR #17, the ASCII curation PR) silently flipped
  it to 3.6-first with no reasoning anywhere. Restored, and recorded in ADR-0074's
  Context so it doesn't flip back a third time.
- **Questions moved to the fan-in.** `_process_gate_item` writes cards only;
  `gate_and_persist` now runs a topic-wide question phase once every group clears its
  card bar, one claimed-key unit per subtopic-tier. So a tier's question budget is
  spent against its FINISHED card set, not its first gate round's survivors.
- **A real bug found and fixed in my own change, with a regression test.**
  `_redraft_until_bar` appends one item report **per round**, so a tier arrives at the
  fan-in named many times. Running the question phase per report generated a tier's
  questions once per round: measured live at **84 reports for 9 tiers → 653 questions
  for 70 cards** (~580 wasted LLM calls per run) and an equally inflated report.
  Reports are merged by (topic, subtopic, difficulty) first.
  `test_a_redrafted_tier_gets_exactly_one_question_pass` was verified to FAIL against
  the buggy version before being kept. **`PipelineState.item_reports` is per ROUND,
  not per tier** — its docstring now says so; anything needing per-tier semantics must
  merge first.
- **Enforced twice, per CLAUDE.md.** Two new `test_architecture.py` rules: the
  generation pipeline may not reintroduce a concurrency semaphore (ADR-0047/0074), and
  `_run_question_phase` may only be called from the topic-wide phase. Plus
  `tests/test_key_claims.py` (11 tests, real Postgres session): claim binds and stays,
  own-second-rung beats another key's first, the claim moves off a dying key, busy grid
  waits instead of spending the reserve, reserve opens on genuine exhaustion, two claims
  never share a key, release hands the key back, short ladders clamp the reserve.
- **`make check`:** `mypy --strict` green (86 files), **465 tests green**. Pre-existing
  and NOT mine: `ruff check src tests` fails E501 in `content/ascii_library.py`,
  `generation/prompts/cards.py`, `generation/langchain_impl.py` (5 prompt-string lines,
  confirmed identical at HEAD), `tests/test_technical_topic_guard.py`; and
  `prompts/cards.py` fails `ruff format --check`. **Note the container runs ruff 0.16.5
  and the host had 0.16.0** — they format differently, so run lint through
  `docker compose exec api`, not the host.
- **Not done, deliberately:** the B4 `/admin/quota` panel doesn't yet show claims
  (keys claimed / free / groups waiting) — ADR-0074 lists it under "Easier" but it is a
  separate frontend change and would need `/design`. Nothing is committed; the owner
  had not asked for a commit.
- **Untouched as always:** the owner's Wave-1 working tree. Note this session edited
  `pipeline/{nodes,persistence,state}.py`, which carry uncommitted Wave-1 changes —
  edits were purely additive and the technical-topic-guard work is intact.

**Run 7 (2026-08-30, post-ADR-0074) — the scheduler's first real run.** CockroachDB
end to end: **18m 50s**, 492 cards, 292 questions, 35 tiers at 100%, exit 0 — against a
30–50 min average before. Written up in
[generation-pipeline-run-7-benchmark.md](../architecture/generation-pipeline-run-7-benchmark.md).
Two findings worth carrying forward:

- **A compose default silently outranked the code.** `docker-compose.yml` set
  `SPOIN_GEMINI_THINKING_LADDER` with its own hardcoded 3.6-first default, on the `api`
  service only — so `api` and `worker` resolved the same setting differently and the 3.7
  restoration never took effect. Proof in the ledger: 141 requests on `gemini-3.6-flash`,
  **zero** on `gemini-3.7-flash`, no `model_unavailable` row. Fixed, but **3.7-first is
  still unproven — the next run is its first test.** Worth sweeping the other
  `${VAR:-default}` entries in compose against their `Settings` fields.
- **The concurrency ceiling was the curriculum, not the key pool.** 35 tiers collapse into
  18 groups, and the group is the fan-out unit, so 16–18 keys in use out of 33 IS full
  stretch. ADR-0074's "parallelism = key count" only binds at ≥33 groups.

Also: 6 rejections out of 498 is a suspiciously low rate and ran on the unintended thinking
model. Confirm against real reading before treating 1.2% as the new baseline.

**Next:** unchanged — Phase 2 Tier 2 (B6 → ADR amending 0034; B14 → ADR; B12/13 → ADR,
numbered from 0075 now), then the Cockroach sequence, then B7. Task 0034 still
pickup-ready.

---

## Phase 0 — What is already built (read before starting anything)

Several items on the list are already implemented, wholly or in part. Starting them
from scratch would duplicate shipped work and, in two cases, re-decide a question an
ADR already answered.

| Item | Reality on disk | What is actually left |
|---|---|---|
| **F11** no-color option | **Shipped.** `NO_TOPIC_COLOR = -1` sentinel (ADR-0051), wired end to end: `lib/topicColor.ts:55`, picker at `components/TopicStatsModal.tsx:197`, server accepts `hue: -1` via `TopicColorIn`. | Discoverability, and whether the topic *chips* in `TopicRail`/`TopicsProgressBox` honor it the way cards do. Verify, don't rebuild. |
| **F13** undo toast | **Shipped.** ADR-0052; `lib/undo.ts` (single slot, 5s, X dismisses without undoing), `components/UndoToast.tsx`, mounted once at `AppShell.tsx:284`, used by Notes/Liked/Saved. | Verify all three still route through `offerUndo`, and that the toast sits above the mobile tab bar. |
| **B2/B8** topic description | **Backend shipped.** `TopicRequestIn.description` (`api/schemas.py:41`) reaches `Topic.description` and the curriculum prompt (`langchain_impl.py:1188`, `pipeline/nodes.py:200`). | The **frontend never sends it** — `RequestTopicBox` calls `api.requestTopic(trimmed)` with the name only. A form field plus one `lib/api.ts` argument. |
| **B2** "DSA (interviews)" vs "DSA (CP)" | Handled by ADR-0025 batched LLM matching (`pipeline/topic_match.py`) — no thresholds; description is context for the call. | Nothing on the matcher. It only starts helping once the description actually reaches it. |
| **B4** quota persistence | **Answered: yes.** `quota_ledger` keyed `(day, backend)` with `requests_spent` / `exhausted_at` / `cooldown_until`; `quota_request` is the shared per-minute window (ADR-0058); `model_unavailable` parks dead models (ADR-0065). All three are DB tables every process reads. | No storage work. What's missing is a **read surface** — see B4. |
| **B9** CockroachDB | Already decided: ADR-0048, with a five-task sequence, tasks [0016](../tasks/0016-cockroachdb-spike.md) → [0021](../tasks/0021-cockroachdb-cutover.md), gated on the 0016 spike. | Execute the existing sequence. The **cache** half of the ask is genuinely new — see B9. |
| **B2** batched topic add | Task [0032](../tasks/0032-batch-topic-requests.md) already specifies it: several topics in one submission, each with a description, one batched call. | "Disable parallel custom topic adds" is the same fix from the other side — see B2. |

Every open decision was settled on 2026-08-30 — see "Decisions taken" at the end of this
doc. Nothing in this plan is blocked on an answer.

---

## Phase 1 — Frontend

Three waves. Wave 1 items are independent of each other and of Phase 2.

### Wave 1 — bugs and verifications (small, independent, first)

**F1. Progress-card hover visual bugs** — `components/TopicsProgressBox.tsx` + its rules in `app/globals.css`.

Not yet diagnosed; step one is a repro, not a fix. Record palette, viewport, and
whether the artifact is (a) a layout shift — padding/border added on hover moving
siblings, (b) a stacking bug — hover surface under a neighbour, `z-index` on a
non-positioned element, or (c) a transition on a non-interpolable property. The fix
differs per cause: (a) move the hover delta to `outline`/`box-shadow`, which don't
affect layout; (b) hoist to a positioned parent; (c) animate `transform`/`opacity` only.
**Size:** S once repro'd. **Risk:** low.

**F2. Like lags the whole screen** — diagnosed.

`lib/engagement.ts:88-94`: a like does two synchronous things — an urgent `flush()`
(network POST) *and* `invalidate("liked")`. `invalidate` calls every subscribed
listener synchronously, and `LikedView` stays mounted for the session (AppShell's
`visited` set), so a like re-fetches and re-renders the entire liked list **in the
same tick as the click**. Bookmark does the same to `saved`, but that list is usually
smaller, which is why only like is visible.

Fix — make invalidation non-blocking and coalesced. Two candidate designs:

1. **Lazy staleness (preferred).** `invalidate` sets a dirty flag; `useRefreshEffect`
   re-runs when its view next becomes visible, not immediately. This matches what
   `lib/refresh.ts`'s own docstring says it is for, and removes a class of wasted
   refetches.
2. **Deferred dispatch.** Keep eager refresh but schedule it off the interaction
   frame (`queueMicrotask` / `requestIdleCallback`).

**Size:** S. **Risk:** low, but it changes cross-view refresh timing — worth a short
ADR amending the refresh module's contract.

**F11 / F13.** Verification only, per Phase 0. One sitting for both.

### Wave 2 — component reworks

**F3. A one-line caption under every art and diagram.**

The data mostly exists: `Card.visual_slots` already carries
`{"art": ..., "alt": <one-sentence alt text>}` (`api/schemas.py:88-95`), and
`Card.tsx:650` passes it to `HeroVisual` as an `aria-label` only. Making it visible
under the art is a render change in `HeroVisual`/`AsciiArt` (`Card.tsx:1043-1055`)
plus a `figcaption`-style rule.

The gap is **in-body mermaid diagrams** (`Card.tsx:1640`, `MermaidBlock.tsx`) — fences
inside `body`, with no caption source at all. Options: *derive* one from the mermaid
title / first node (cheap, often bad), or *generate* one per diagram fence (correct,
but a prompt + schema change that only covers newly generated cards).

Recommend: ship the ASCII caption now from the existing `alt`, and fold diagram
captions into **B14's repair lane** rather than running a separate backfill.

Note this in the ADR-0042/0067 lineage: it changes what the visual slot is *for*
(screen-reader text → visible caption). Alt text written to be read aloud is not
automatically a good caption, so expect to revise the prompt's wording guidance.
**Size:** S (ASCII) + M (diagrams). **Risk:** low.

**F4. Save your own themes in the theme dropdown.**

Today `ThemePicker` has five presets plus a single `custom` slot in `localStorage`
(`spoin-palette` + four inline custom properties on `<body>`). The ask is *n* named
user themes listed alongside the presets.

Work: change storage from one slot to a list (`[{id, name, bg, fg, accent, accent2}]`),
have `CustomThemeModal` save-with-a-name into it, render them in `PickerDropdown` under
the presets with rename/delete, and make palette application resolve a custom id to its
four values. **The pre-hydration inline script in `app/layout.tsx` must learn to read
the list too**, or a saved custom theme flashes the default on every load.

**Interaction design confirmed 2026-08-30** (canvas link in the session log above; build
against this, don't re-derive it): the dropdown becomes a **fixed 3-row window** (126px —
3 × 38px pill + 2 × 6px gap), same hidden-scrollbar treatment `.progress-box-list`
already uses. Presets fill it; any number of *saved* themes beyond that scroll inside the
fixed window rather than growing the dropdown. A saved theme's swatch stays a clean
38px preview at rest; hovering it reveals two small circular controls — a pencil
(bottom-right, opens the edit modal pre-filled) and an × (top-right, deletes) — so nothing
crowds the resting state. A trailing `+` pill (same style as today's custom-slot trigger)
opens the edit modal for a new theme. The edit modal itself (`CustomThemeModal`) gains a
required **Name** field above its four color pickers, and a "Delete this theme" action
that only appears when editing an existing saved theme, not when creating a new one —
this part is unchanged from `CustomThemeModal`'s current chrome, confirmed as-is.

**Preset content — RESOLVED 2026-08-30 (session 2).** The final 11-theme list is curated,
contrast-checked, and locked in the canvas and in
[`docs/design/mockups/appearance-pickers.html`](../design/mockups/appearance-pickers.html).
The paragraph below is kept for the reasoning it records; it no longer blocks the build.

**~~Still needed before this is buildable~~ — real preset content, not placeholders
(added 2026-08-30):** the first design pass filled the 3-row grid
with invented palette names just to prove the layout holds up under a realistic count.
The owner wants the **actual, final preset list** — curated for real, wide enough to
cover genuinely different aesthetic tastes, not five variations on one look. Concretely,
think about covering (not a rigid checklist, a spread to aim for): a light/paper option
and a true dark option at both ends; at least one high-contrast/accessible-first choice;
something warm (amber/terracotta-leaning) and something cool (blue/teal-leaning);
something minimal/desaturated and something with more chroma or personality; and the
existing five (Notebook, Twilight, Skylight, Obsidian, Oscilloscope) should very likely
stay, since dropping a shipped default is its own decision. Check every candidate's
actual contrast (`--fg` on `--bg`, `--accent` on `--bg`) before it goes in the list — a
palette that looks fine as a swatch and is unreadable as body text is worse than not
shipping it. This is genuine curatorial work; budget real time for it rather than
generating a list quickly.

**Decided 2026-08-30: preferences move server-side.** A `user_preference` row on the
API (ADR-0045's settings surface already gestures at it) holds palette, custom palettes,
font, and imported-font references, so they follow a user to any device and the future
mobile client gets them for free — the "no business logic in `apps/web`" rule applied to
the one place it was quietly being broken. Build **F4 and F5 against the server from the
start**; doing them locally first means doing them twice.

Two things this makes load-bearing:

- **`localStorage` stays as the pre-hydration cache, not the source of truth.** The
  inline script in `app/layout.tsx` must paint from the last-known local value (it runs
  before any fetch can return), then reconcile with the server value once auth resolves.
  Get this wrong and every page load flashes the wrong theme.
- **Guests have no server row.** A guest's preferences live locally and must survive the
  guest→claimed-account transition (ADR-0033), or claiming an account silently resets
  someone's theme.

**Size:** L (server-backed). **Risk:** medium — the flash-of-wrong-theme and the guest
migration are both easy to miss and both very visible. **Needs:** a migration, an
endpoint pair, and a note in ADR-0045.

**F5. Font picker: dropdown only, no popup; plus font import.**

Today `FontPicker` is a `PickerDropdown` that opens `CustomFontModal` for "more fonts".
Ask: kill the popup, everything in the dropdown, match `ThemePicker`'s style, allow
importing a font that persists in that dropdown.

**Decided 2026-08-30: Keep/Revert goes away — click and it's saved**, exactly like
`ThemePicker`. This reverses a deliberate ADR-0037 choice ("legibility is harder to judge
from a small swatch than color is"), so it needs a **short ADR amending 0037** recording
that consistency with the theme picker won over the confirmation step, plus a
back-pointer in 0037 itself. The reversal is cheap to undo later precisely because it is
written down.

Import mechanics: `FontFace` + `URL.createObjectURL` for live preview; for persistence
you must store the file, not the blob URL — IndexedDB locally, or (preferred, same
reasoning as F4) uploaded and served by the API. Validate that the file is genuinely a
font (`woff2`/`ttf`/`otf`, magic-number check, not just the extension) and cap its size;
this is arbitrary binary you are handing the browser.

**Interaction design confirmed 2026-08-30** (same canvas as F4): font pills are restyled
to the **exact same 38px swatch-grid pattern** as the theme dropdown — that *is* "match
theme's dropdown style" — each pill showing "Aa" set live in its own face, in a **fixed
5-row window** (214px), same fixed-height/scroll treatment as F4's 3 rows. The one
structural difference from the theme dropdown: **"Upload a font" lives in its own row
above the scrollable grid**, separated by a hairline, not inside the wrapped pill grid —
because it has to stay reachable no matter how far down the (potentially long) font list
someone has scrolled, and a plain `+` pill wrapped in with everything else would scroll
away. Picking a file expands one inline row below it to name the font — text field plus
Save — still inside the one dropdown surface, never a second popup. Saved/imported fonts
get the same hover-reveal × as saved themes; no rename affordance was asked for on fonts,
only delete — if that asymmetry with themes turns out to bother you in use, re-import
under a new name is the workaround for now.

**Preset content — RESOLVED 2026-08-30 (session 2).** The final 20-font list is curated
and rendered-checked; it lives in the canvas and in
[`docs/design/mockups/appearance-pickers.html`](../design/mockups/appearance-pickers.html).
The paragraph below is kept for its reasoning; it no longer blocks the build.

**~~Still needed before this is buildable~~ — real preset content, not placeholders
(added 2026-08-30):** same requirement as F4. The first pass used
26 invented font names purely to prove the 5-row grid actually overflows at a realistic
count. The owner wants the **real, final font list**, wide enough to cover different
reading preferences, not near-duplicates of the existing five. Concretely, aim to cover:
a workhorse serif and a workhorse sans beyond what's already there; something genuinely
monospaced-technical (JetBrains Mono already covers this — a second option is optional,
not required); a high-legibility/dyslexia-considerate option (Atkinson Hyperlegible
already covers this); something with more character/display presence for a reader who
wants the app to look less generic; and something narrower/denser for anyone who wants
more text on screen. Every candidate needs a real Google Fonts (or self-hostable)
family that actually loads — verify it renders before it goes in the list, and check
each face at body-copy size, not just in a 15px "Aa" swatch, since some display faces
that look great tiny are unreadable at paragraph size.
**Size:** M + M. **Risk:** medium — font loading fails in interesting ways (CORS, FOUT,
a face with no glyphs for the content).

**F6. "Saved" → "Revisit" everywhere, and rebuild the view.**

Confirmed inconsistency: `MobileNav.tsx:32` already says "Revisit"; `Sidebar.tsx:118`
still says "Saved". Two halves:

- **Rename** — user-facing copy only. Keep the `saved` route, `RefreshScope`,
  `card_bookmark` table and `api.saved*` names as they are; renaming the wire format
  buys nothing and touches the DB. Change labels, headers, empty states, both navs.
- **Rework** — `SavedView.tsx` (519 lines) is the odd one out against `NotesView`
  (420) and `LikedView` (388); they have visibly diverged. Recommend extracting the
  shared shell — topic filter chips, empty state, row layout, undo wiring — into one
  `CollectionView` all three use. That is ADR-0046's "one collection surface" actually
  applied, and it is what keeps them from diverging again.

**Size:** S rename, L rework. **Risk:** medium — unifying three views means regressions
land in all three at once. Ship the rename as its own commit first.

**F9. Adding a topic refreshes the feed.**

Confirmed intentional: `AppShell.tsx:201`, `onFollowed` calls `invalidate("feed")`. The
reasoning is sound (a new subscription changes feed candidates) but the effect is wrong
— a brand-new topic has no cards yet (`status: "generating"`), so the refresh discards
scroll position to show nothing new.

Fix: invalidate only when the follow changed what the feed can serve — i.e. when
`result.status === "subscribed"`. For `"generating"`, invalidate later, when the
generation tracker reports the topic ready. Record the rule in `lib/refresh.ts`'s
docstring; it pairs naturally with F2's change to the same module.
**Size:** S. **Risk:** low.

### Wave 3 — the loader

**F12. Replace the initial loading state.**

Current: `AuthProvider.tsx:136` renders `.auth-loader` (`globals.css:5441`) at
`scale(1.5)` — a static glyph with a pulse. Replace with a branded loader built from
the spoin wordmark, themed by the user's persisted palette (Notebook by default). The
pre-hydration script in `app/layout.tsx` already resolves the palette before React
mounts, so the loader can be correct on first paint instead of flashing.

Process: use the `/design` skill to draft 5–10 loader concepts on one canvas, pick one,
implement it as inline SVG + CSS animation (no JS, so it renders before hydration).
Constraints for every concept: respects `prefers-reduced-motion` (there is already a
`getReducedMotion` helper), no layout shift when swapped for content, correct in all
five palettes plus a user custom theme.

Commit the chosen design under `docs/design/mockups/` per CLAUDE.md — an artifact link
is not a source of truth.
**Size:** M. **Risk:** low.

---

## Phase 2 — Backend

Ordered by dependency, not by your numbering. The three genuinely new subsystems
(B7 study material, B12/13 AskAI, B9 cache) each want an ADR before code.

### Tier 1 — small, independent

**B2 / B8. Description field in the frontend, and no parallel custom adds.**

Two changes to the same surface, and task [0032](../tasks/0032-batch-topic-requests.md)
already specifies the shape: a `+` to add rows, each `{name, description?}`, sent as
**one batched call**.

That batching *is* the fix for "parallel adds break things". Today `RequestTopicBox`
lets a user fire several independent `POST /topics` calls, each of which runs
`validate_topic_names` and `match_and_create_topics` — concurrent matchers can race to
mint two topics for names that should have merged, and each one burns quota
independently. One request carrying N topics goes through ADR-0025's batched matcher
once, which is what it was designed for.

Work: server endpoint accepting a list (or extend the existing one); `lib/api.ts`
gains the description and list form; `RequestTopicBox` grows the rows UI and **disables
submit while a request is in flight** (belt and braces, independent of batching).
**Size:** M. **Risk:** low. **Reuses:** ADR-0025, task 0032.

**B4. A read surface for quota/key usage.**

The data is already durable and cross-session (Phase 0). What's missing is being able
to *see* it without a `psql` prompt. Add a small authenticated endpoint —
`GET /admin/quota` returning today's rows per `(key, model)` cell: `requests_spent`,
ceiling, `exhausted_at`, `cooldown_until`, plus currently-parked models from
`model_unavailable` — and a modest panel wherever you already look (there is a
`routers/dev.py` precedent, which its own docstring flags as needing real auth before
public exposure; fix that as part of this).

**Keep the ADR-0065 distinction visible in the output.** "Ran out of daily budget",
"every cell throttled per-minute", and "every model unavailable" are three different
facts, and a panel that collapses them into "quota exhausted" recreates exactly the
misreading ADR-0065 was written to prevent.
**Size:** S. **Risk:** low.

**B11. Card indexing — DROPPED from this phase (decided 2026-08-30).**

The concern was that ADR-0054's ordering machinery is redundant now that the planner
(ADR-0059) decides a tier's card set. Decision: **no change for now** — if the redundancy
shows up as a real problem in production, revisit it then. Nothing to build, no ADR.

### Tier 2 — new subsystems

**B6. Embedding-based topic colors.**

Today the default hue is positional/hash-based: ten curated hues by subscription order,
then `hash(topicId) % 360` (`lib/topicColor.ts`). The ask is to pick a color whose
*meaning* fits the topic, avoiding colors already taken.

Design that fits this codebase:

- Build a **color vocabulary** offline — a few hundred named colors with their hue, each
  embedded once with the same local embedder the corpus uses (`spoin.embeddings`, free,
  never quota'd). Ship it as static data next to the ASCII library precedent
  (`content/ascii_library_data/`), not as a runtime LLM call.
- At topic-mint time, embed the topic name+description (already done for matching — reuse
  that vector, don't pay twice), take nearest color names, then **filter against hues
  already used by that user's other topics** with a minimum angular distance, and pick the
  best survivor. If nothing survives the distance filter, fall back to today's curated
  spread — never return a color that reads identical to a neighbour.
- Store it as an explicit `accent_hue` on `UserTopic` (ADR-0034's existing field), so the
  user's later manual change and the `-1` opt-out (ADR-0051) keep working untouched.

This respects "the generator is trusted for taste, never for constraints": semantics come
from embeddings, but *distinctness* is enforced server-side by arithmetic, not asked for.
**Size:** M. **Risk:** low. **Needs:** an ADR amending 0034 (default hue now derived, not
positional), plus a note that it must degrade to the old default when embeddings are
unavailable.

**B14. Report a card as defective, and a structure-only repair lane.**

The ask: readers flag a card whose *structure* is broken (bad art, a code block on a
non-technical card, a mangled diagram), and it goes back through the pipeline to be
fixed **without changing what it says**.

Shape:

- `card_report` table: `(card_id, user_id, reason enum, note?, created_at)`, unique per
  user+card. Reason as an enum (`art`, `diagram`, `code_block`, `formatting`, `other`) —
  a `GROUP BY`, not string parsing, the same argument `RejectedCard.stage` makes.
- `POST /cards/{id}/report` and a button in the card's action row next to AskAI.
- A **repair pass** in the worker, separate from generation: claim reported cards, run a
  narrowly-scoped LLM call that may rewrite only the visual/structural slots
  (`visual_slots`, fences in `body`) and is *forbidden* to alter meaning; then verify
  deterministically — art within column budget, no code fence on a non-technical card,
  mermaid within ADR-0067's shape budget, `body` prose unchanged modulo fences. Since the
  invariant is "content unchanged", the check can be exact: diff the fence-stripped body
  and reject the repair if it moved.
- Card families already exist (`card.py:46`, "exactly one active row per family"), so a
  repair should mint a new active row in the same family rather than mutating in place —
  the defective version stays auditable and the fix is revertible.
- **A threshold, not a hair trigger.** One report on a popular card shouldn't burn a
  generation call. Assumption unless you say otherwise: repair triggers at **two
  independent reports, or one report from the owner account**.

Fold F3's diagram captions into this lane — it is already the "touch existing cards
without changing meaning" pass.
**Size:** L. **Risk:** medium (an LLM asked to change only structure will change prose;
the deterministic diff is what makes this safe). **Needs:** an ADR.

**B12 / B13. AskAI, and whether an MCP server is the right shape.**

The button exists (`Card.tsx:732`, `aria-label="Ask AI"`) and does nothing. You proposed:
flash-lite through the quota ladder, plus an MCP server exposing the DB so the model can
retrieve the card, its subtopic, its topic, sibling subtopics, and the same subtopic at
higher difficulties.

**You asked whether that is the best way. My honest read: the model is right; the MCP
server is the wrong mechanism for this particular call.** Reasons:

- MCP exists so an *external, general* agent can discover tools it wasn't built with.
  Here the caller is your own backend, in the same process, with SQLAlchemy models
  already loaded. An MCP layer adds a protocol hop, a second deployable, and a second
  place where DB access is authorized — for retrieval you can express in one query you
  already know how to write.
- "The entire DB connected" is a security surface you do not want on a user-facing path.
  An LLM with general DB access, prompted by user text, in a request that returns to the
  user, is a prompt-injection target with a data-exfiltration payoff (other users' notes,
  emails, `app_user` rows).
- Multi-turn tool-calling is the *opposite* of your quota model: ADR-0005 says every
  LLM-facing method takes a collection because the free tier meters **requests**. An
  agentic retrieval loop is 3–6 requests per question, unbounded.

**Recommended shape:** deterministic retrieval, single call.

1. The client sends `card_id` + question. The server assembles context itself with one
   query — the card, its subtopic and topic, sibling subtopics, the same subtopic at
   adjacent difficulties, and (cheap, already available) the top-k nearest cards by
   embedding.
2. One flash-lite call through the existing quota governor, with the context inlined and
   a system prompt scoped to "answer from this material; say when it isn't covered".
3. Stream the answer back; persist the exchange (`card_qa`) so a repeated question is a
   cache hit, not a second call.

**Budget & Quota (decided 2026-08-30):** 33 keys × 2 flash-lite models × 500/day ≈ **33,000
requests/day** across the generator ladder, so AskAI and the pipeline have ample capacity
without needing any quota reservation or artificial partitioning between them.
The cap is **200 questions per user per day** — generous enough to be invisible in normal use,
low enough that a single account cannot walk off with the day. Implement it on the existing
ledger machinery (a `(day, user)` row), not a new subsystem, and return a clear "you have hit
today's limit" rather than a generic 429.

**Keeping questions on the card's topic** — the part you asked to be thorough about.
No single mechanism does this; four layers, cheapest first, and the last two are the ones
that actually hold:

1. **Context scoping (structural).** The model only ever receives this card, its
   subtopic/topic, sibling subtopics, and adjacent difficulties. It is not given a search
   tool, a browser, other users' data, or the rest of the corpus. Most off-topic questions
   fail here for free, because there is nothing in context to answer them from. This is
   the single biggest reason not to put a general DB tool behind this endpoint.
2. **A hard system prompt** stating the card's title and topic explicitly, instructing:
   answer only what the supplied material covers; if the question is outside it, say so
   and point back at the card. Prompt-level, so it is a *tendency*, not a guarantee — the
   codebase's own rule is that anything which must be true is checked outside the model.
3. **A cheap pre-check before spending a call.** Embed the question with the local
   embedder (free, no quota) and compare it against the card + subtopic + topic
   embeddings. Below a calibrated similarity floor, refuse *without* an LLM call and
   render a "that's outside this card — ask about X instead" state. This is the check that
   makes layer 2 enforceable, and it costs nothing per question.
4. **Structured output with a self-declared scope verdict.** The single call returns
   `{on_topic: bool, answer: str}`; when `on_topic` is false the server renders the
   refusal state and never shows the model's own prose. Combined with (3), an off-topic
   question has to beat both an embedding gate and a schema field to reach the reader.

Also treated as untrusted input, not stylistic detail: **card content and user question
both flow into a prompt**, so instruction-shaped text in either ("ignore the above…")
must not be able to change behavior. Keep the question in a clearly delimited user turn,
never concatenated into the system prompt; and since the response never carries privileged
data (layer 1), a successful injection buys an attacker an off-topic answer, not an
exfiltration. That is the property to preserve if this design is ever changed.

Where MCP genuinely pays off is **your own** tooling — an admin/debug MCP server over
`spoin_db` for you to query the corpus conversationally from Claude Code, read-only, not
on any user path. Worth building; keep it out of the request path.
**Size:** L. **Risk:** medium-high (quota exposure). **Needs:** an ADR covering the
retrieval shape, the quota policy, and the rate limit. If you still want MCP in the
user path after reading this, that is your call — say so and I'll design it with a
read-only, allow-listed-view credential rather than the full DB.

**B7. Bring your own study material (PDF, docx, txt).**

Biggest item on the list; genuinely new subsystem. Cards get generated from a user's
uploaded material *plus* the model's own knowledge on the topic.

Pipeline sketch, reusing what exists:

1. **Upload** — `POST /topics/{id}/materials`, multipart, with hard limits (file count,
   MB, page count) and real type sniffing rather than trusting the extension. Store the
   blob outside Postgres (R2/S3-compatible; a 30 MB PDF does not belong in a 10 GiB
   Cockroach budget) and a `topic_material` row with status.
2. **Extract — and PDFs go to the model directly (verified 2026-08-30).** You asked
   whether flash-lite can read PDFs itself. It can: `gemini-3.1-flash-lite` and
   `gemini-3.5-flash-lite` — both already in `SPOIN_GEMINI_GENERATOR_LADDER` — accept
   text, image, video, audio **and PDF** input, so no separate OCR dependency and no
   escalation to a flash model is needed. Two details that matter here specifically:
   native text embedded in a PDF is extracted by the provider and **not billed as input
   tokens**, and images inside a PDF are handled by the same call. Since the free tier
   meters *requests*, not tokens (ADR-0003), a whole document costs one request.

   So: parse docx/txt locally (free, no call at all), and send PDFs — including
   image-heavy and scanned ones — straight to flash-lite. Standalone image uploads
   (a photo of a page) are still deferred to a second milestone; they are the same
   capability but a different UX, and PDF covers the realistic case.

   Re-verify before building: model capabilities move, and ADR-0003's standing rule is
   that free-tier facts get checked, not assumed. Sources are in the session notes —
   [3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite),
   [3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite),
   [document understanding](https://ai.google.dev/gemini-api/docs/document-processing).
3. **Chunk + embed** — the local embedder again, into a `material_chunk` table with
   pgvector (or Cockroach's vector type post-cutover; verify in task 0016's spike, this
   is a new dependency on it).
4. **Feed the existing pipeline** — the curriculum call gets retrieved chunks as context
   alongside `Topic.description`; the card writer gets chunks relevant to its subtopic.
   Both are prompt-context changes, **not** a new pipeline. The blend you described
   ("material plus the LLM's own knowledge") is a prompt instruction plus a gate check
   that cards which claim to cite the material actually can.
5. **Scope the sharing — decided 2026-08-30: material-derived cards never enter the
   public topic pool.** Today content is generated once per topic and **shared by
   everyone** (the load-bearing fact in `docs/architecture/overview.md`); cards derived
   from one user's uploaded document are visible to that user only. Enforcement is not a
   flag the feed remembers to check — it is a filter in the candidate query itself, with
   an architecture test that fails if a card carrying a `source_material_id` can ever be
   selected for a user who does not own it. This is the first per-user content in the
   system, so the invariant gets wired the twice-enforced way like every other hard rule.

   **Say so in the UI, at upload time.** The user must be told, on the upload surface
   itself and not buried in settings, that their document and the cards made from it stay
   private to their account and are never added to public topics. That copy is part of
   this milestone's definition of done, not a follow-up.

Also: copyright and PII. Users will upload textbooks. Decide the retention and
takedown story now, in the ADR, not after.
**Size:** XL — split into milestones (PDF/docx/txt private topics first, standalone
image uploads later).
**Risk:** high. **Needs:** an ADR, and probably its own task sequence like 0016–0021.

**B9. CockroachDB as the store, plus a hot cache for online users.**

Two separable pieces.

*Piece one — the cutover* is already planned: ADR-0048 and tasks
[0016](../tasks/0016-cockroachdb-spike.md)–[0021](../tasks/0021-cockroachdb-cutover.md),
gated on the spike. Execute them in order; don't redesign. Two things to re-verify in
0016 given the newer items on this list: **vector support** (the corpus, B6's colors, and
B7's chunks all depend on it — Cockroach has a native vector type and index, but confirm
it against the queries `feed`/`topic_match` actually run), and **RU consumption**, which
is the meter ADR-0048 introduced and nobody is watching yet.

*Piece two — the cache* is new and is the right instinct. Cockroach Basic charges Request
Units for every read; the feed read path is the highest-frequency read in the system, and
serving it from a cache is what makes a free tier survive real users.

Design that matches your description:

- **What to cache:** per online user, their subscribed topics and the *candidate card
  pool* at the difficulties they can currently be served — beginner-only for a beginner,
  beginner+intermediate for an intermediate, and so on as the feed's difficulty mix
  shifts with cards read. That is exactly the read `feed`'s candidate generation does.
- **Where:** you have a Neon account doing nothing after the cutover — but a second
  Postgres is a poor cache (connection limits, cold starts, and it also meters). The
  better fit is a **Redis-compatible KV** on a free tier (Upstash: per-request pricing,
  scales to zero) or, cheapest and simplest at your current scale, **an in-process LRU in
  the API** with a short TTL. At one API instance the in-process cache costs nothing and
  removes most of the RU load; it stops being sufficient the moment you run two replicas
  that must agree.
- **Invalidation** is the whole problem, as always. Cache the *card pool* (changes only
  when generation writes) and keep *seen-state* uncached (changes on every swipe). That
  split is already how the read path is factored — `user_seen_bitmap` filters a candidate
  set — so the expensive, stable half is cacheable and the volatile half stays live.
- **Warm on session start**, not on demand: when a user opens the app you know their
  topic list, which is precisely the "whoever is online" trigger you described.

**Size:** L. **Risk:** medium — a stale feed cache serves cards a user already read,
which is the one bug the read path exists to prevent. **Needs:** an ADR (cache policy,
invalidation boundary, and what happens on a cache miss under load). Sequence it
**after** the cutover — caching against a database you're about to replace measures the
wrong thing.

### Suggested build order

1. Wave 1 frontend (F1, F2, F11/F13 verify) — days, unblocks nothing but fixes what you
   feel every day.
2. B2/B8 + F6 rename + F9 — small, high-value, all in the same neighbourhood.
3. F3, F4, F5, F12 — the UI polish block; decide the local-vs-server preferences question
   at its start.
4. B4, B6 — small backend.
5. F6 rework (`CollectionView`) — the one big frontend refactor, best done before the
   review phase so the review sees the final shape.
6. B14 repair lane, then B12/13 AskAI — both want ADRs first.
7. Cockroach sequence 0016–0021, then B9's cache.
8. B7 study material — last, largest, most likely to change the architecture.

---

## Phase 2.5 — Meta rules for this phase

- **Every new frontend design goes through `/design` first, and is confirmed by the owner
  before a line of it is implemented.** That covers the loader (F12), the theme and font
  dropdowns (F4/F5), the unified collection view (F6), the AskAI panel, the report-card
  affordance (B14), and the study-material upload surface (B7). Draft the concepts on a
  canvas, get the pick, *then* build — and commit the chosen design under
  `docs/design/mockups/` per CLAUDE.md, since an artifact link is not a source of truth.
- Every item marked **Needs: an ADR** gets one *before* implementation, using
  `docs/adr/TEMPLATE.md`, numbered from the current highest (0069).
- Every item deferred out of a milestone gets a task doc and a row in
  `docs/tasks/README.md` — not a TODO comment.
- Anything that must be *true* gets a check, not a prompt sentence: the repair lane's
  meaning-unchanged diff, B6's hue-distance filter, B7's file-type sniffing, AskAI's rate
  limit. This is the codebase's single most consistently applied rule; the new items are
  where it is easiest to drop.
- `make check` (ruff + mypy --strict + tests) stays green per commit, not per phase.

---

## Phase 3 — The review and quality pass

Run this **after** Phase 1–2 land, as its own phase with its own branch. The goal is
not "read the whole codebase" — 81 Python files and ~11.5k lines of TSX will not survive
an undirected read. The goal is a set of passes, each answering one question, each
producing either a fix or a task doc.

### Pass 1 — Invariant enforcement (mechanical, highest value)

The codebase's rule is that a hard architectural rule is enforced **twice** — a ruff
`banned-api` entry and an AST test in `tests/test_architecture.py`. Audit that every rule
that *should* be mechanical actually is:

- No LLM in the feed read path (exists — verify it still covers new modules).
- Only `langchain_impl.py` imports LangChain (exists).
- Every LLM-facing interface method takes a collection (exists).
- **New candidates from this phase:** no `fetch()` outside `lib/api.ts`; no business
  logic in `apps/web` (harder — at minimum, no direct DB or generation concepts leaking
  into components); the AskAI path must go through the quota governor; the repair lane
  must not write to `Card.body` prose.

Anything found stated only in a doc gets wired up or explicitly downgraded to a
convention. **Output:** new tests, not a report.

### Pass 2 — Read-path performance under real data

The read path has a stated budget (a swipe is ~50ms). Verify against the live corpus,
not a fixture:

- `EXPLAIN ANALYZE` the feed candidate query, the seen-filter, and the collection views'
  queries at current corpus size and at 10x (project, don't guess).
- Confirm every hot query has an index that actually serves it, and that no N+1 crept
  into the collection views or `TopicStatsModal`'s stats.
- Frontend: profile the feed with React DevTools for the same class of bug F2 turned out
  to be — synchronous work on an interaction handler, un-memoized lists, re-renders on
  every scroll event. `Card.tsx` at 1751 lines is the first place to look.

### Pass 3 — Generation-path correctness and honesty

- Re-read every place a "failed" count and a "rejected" count could be conflated —
  CLAUDE.md names this as a bug that already happened once. Grep for aggregate counters
  in `pipeline/nodes.py` and the benchmark reporting.
- Verify the quota governor's three terminal states (ADR-0065) are distinguished
  everywhere they surface, including the new B4 panel.
- Check retry/timeout boundaries (ADR-0056) still hold with AskAI added as a second
  quota consumer.

### Pass 4 — Security review

Run the `/security-review` skill over the branch, then specifically audit the surfaces
this phase adds, which are all of the interesting ones:

- **File upload** (B7): type sniffing, size caps, storage isolation, no path traversal,
  no serving user files from your own origin without a `Content-Disposition` and a
  sandboxed origin.
- **Font import** (F5): same, plus font parsers are historically a memory-safety target
  in browsers — cap size and type.
- **AskAI** (B12/13): prompt injection via card content and user question, rate limiting,
  and the absolute rule that the model's context contains no other user's data.
- **`routers/dev.py`**: its own docstring flags it as needing real auth before public
  exposure. It must not ship enabled.
- Auth: JWT handling (ADR-0033), guest→claimed account transitions, and that every
  router is transport-only (ADR-0043).

### Pass 5 — Doc/code drift

Cheap and it directly affects how useful the next session is:

- Every ADR whose subject changed in this phase has a forward pointer, and the superseded
  one has a backward pointer (CLAUDE.md's "both directions" rule).
- `docs/tasks/README.md` reflects reality — several tasks in the open table are partly
  or wholly shipped (0002, 0004, 0028's first two items, 0029's retrieval half).
- `packages/api-types` regenerated (`make api-types`); CI drift check green.
- Package READMEs still describe what their package actually owns.

### Pass 6 — Test coverage where it matters

Not a coverage percentage. Three specific questions: does every new invariant have a
test; does every bug fixed in Phase 1 have a regression test; and do the tests that
exercise DB behavior use the real Postgres `session` fixture rather than a mock
(CLAUDE.md's rule, and the thing that will break first on the Cockroach cutover).

### How to run it

Use `/code-review high` per merged branch as you go, and reserve the whole-codebase pass
for the six passes above, each as a separate session with a written output. Each pass
ends with either a commit or a task doc — a pass that ends with a paragraph in a chat
log has produced nothing.

---

## Phase 4 — Deployment

### What you are actually deploying

Four process types, from a repo that is already shaped for this (one image, three
entrypoints — see `apps/api/Dockerfile`):

| Process | Shape | Traffic pattern |
|---|---|---|
| `api` | Long-running HTTP (uvicorn) | Bursty, user-facing, <100ms budget |
| `worker` | **One batch pass, then exits** (`worker/__main__.py`) | Scheduled, minutes-long, quota-bound |
| `web` | Next.js, mostly static + client state | CDN-friendly |
| `db` | Postgres-wire (Cockroach after ADR-0048) | The only stateful thing |

That the worker is a *cron-shaped one-shot* is the most important fact for deployment,
and it is deliberate (ADR-0003 §3): at free-tier quota a persistent pool is idle 99% of
the time, and free hosts sleep idle services anyway. Any deployment that forces the
worker to be a long-lived process is fighting the design.

### Option A — Free tier now (recommended to start)

| Component | Host | Cost | Notes |
|---|---|---|---|
| web | **Cloudflare Pages** | free | Already the stated target; static + edge, generous free tier, no cold start. |
| api | **Fly.io** (or Railway / Render) | ~free–$5/mo | Fly gives you a small always-on VM close to the DB and real WebSocket/streaming support (AskAI wants streaming). Render's free tier sleeps, which adds a cold start to the first swipe. |
| worker | **GitHub Actions cron** | free | Exactly what `worker/__main__.py` was written for; already documented as the production shape. 2000 min/mo free on a private repo, and a 15-minute cadence of short passes fits easily. |
| db | **CockroachDB Basic** | free ($15 credit) | ADR-0048; 10 GiB + 50M RU. |
| blobs (B7) | **Cloudflare R2** | free tier | 10 GB + zero egress fees, which matters more than the storage. |
| cache (B9) | in-process LRU, or **Upstash Redis** | free | Start in-process; move to Upstash the moment you run 2+ API replicas. |

Total: **$0–5/month** at your current scale, with no architectural debt — every one of
these is a connection string or a Dockerfile away from its paid tier.

The one thing to get right early: **put the API in the same region as the database**.
Cross-region latency to Cockroach will dominate your 50ms swipe budget and no amount of
caching fully hides it.

### Option B — Growth (hundreds to low thousands of DAU)

Same shape, more of it. API to 2–3 replicas behind the host's load balancer; the cache
becomes external (Upstash/Redis) because in-process stops being coherent across replicas;
the worker may move from cron to a persistent loop once you are paying for quota and
generation runs continuously — which, per the module docstring, is a *process-type
change over identical code*, not a rewrite. Database goes to Cockroach's paid tier or a
managed Postgres. Realistic cost: **$30–80/month.**

### Option C — Kubernetes

You asked specifically, and you want to learn it, so: two honest answers.

**As a deployment decision for spoin v1: no, not yet.** Kubernetes solves problems you do
not currently have — many services needing independent scaling and rollout, multi-team
ownership, bin-packing many workloads onto shared nodes, portability across clouds. What
it costs is a control plane ($70+/month managed on EKS/GKE, or your time on a
self-managed one), plus the operational surface: ingress, cert-manager, secrets,
autoscaling, node upgrades, and a debugging story with more layers than the app has.
For four process types where three of them scale to zero or near it, a PaaS gives you
95% of the benefit for 5% of the operational load. Choosing Kubernetes now would be the
exact mistake ADR-0049 avoided when it rejected Kafka: one real fix at the price of a new
operational system.

**As a thing to learn: yes, and spoin is a good vehicle for it — off the production
path.** Concretely:

- Your repo already has the two hard prerequisites: **a containerized app with one image
  and multiple entrypoints**, and **externalized config via environment variables**. That
  is most of what makes an app Kubernetes-ready, and most apps don't have it.
- The mapping is unusually clean, which makes it a good teaching example:
  `api` → **Deployment** + Service + Ingress (HPA on CPU/RPS later);
  `worker` → **CronJob** (this is *precisely* the workload CronJob exists for — its
  one-pass-then-exit shape is a Kubernetes-native design by accident);
  `seed` (alembic) → **Job**, or an initContainer — note the compose file already
  explains why migrations must not run in the API container ("an API container that
  migrates on boot races itself the moment there is more than one replica"), which is a
  lesson people usually learn from Kubernetes the hard way;
  `web` → Deployment, or stay on Pages;
  `db` → **stays managed.** Do not run your database in your learning cluster.
  Secrets → Secret/ExternalSecrets for the Gemini keys and JWT secret.
- Learn it on **k3d or kind locally** (free, one binary, deletes cleanly), write real
  manifests for the above, then a Helm chart or Kustomize overlays for local/staging.
  If you want a cloud cluster, a 2-node GKE Autopilot or a $24/month DigitalOcean/Hetzner
  managed cluster is the cheapest realistic way to see a LoadBalancer and real ingress.
- **The migration path costs you nothing to preserve.** Deploying to Fly/Railway now does
  not make a Kubernetes move harder later — the artifact is the same image, and the work
  is manifests, not code. So there is no "decide now or regret it" here, which is the
  usual reason people adopt it too early.

**Suggested split:** run production on Option A. In parallel, keep a `deploy/k8s/`
directory in the repo with manifests you exercise on k3d as a learning track. When (if)
the API genuinely needs multi-replica autoscaling and you are already paying for a
cluster's worth of compute, the manifests are ready and the decision is boring.

### Deployment work items regardless of host

1. **Migrations as a separate step**, never on API boot — the compose file already gets
   this right; preserve it in whatever runs production.
2. **Secrets**: Gemini keys, JWT secret, DB URL out of the repo and into the host's secret
   store. Audit that nothing dev-flavored (`dev-secret-not-for-prod`) can reach prod.
3. **`routers/dev.py` disabled in production**, by config, verified by a test.
4. **CORS** locked to the real web origin.
5. **Health checks**: a real readiness endpoint that verifies the DB, so a replica that
   lost its connection is removed rather than serving 500s.
6. **Observability**: structured logs with the quota governor's terminal-state
   distinctions intact, plus the two Cockroach meters from task 0021 (storage *and* RU).
   You cannot run a free tier you cannot see.
7. **Backups**: the corpus is generated content that cost real quota to produce. Confirm
   the provider's backup story and take your own periodic dump — this predates any
   deployment decision and is the highest-value item on this list.

---

## Decisions taken (2026-08-30)

- **B11** — no change. Revisit only if the redundancy causes a real production problem.
- **B12/13** — deterministic retrieval, single flash-lite call, no MCP in the user path;
  MCP kept for owner-side admin tooling only. 200 questions/user/day; four-layer topic
  scoping (see B12/13).
- **B7** — material-derived cards are private to the uploader and never enter the public
  topic pool; the upload UI must say so.
- **Process** — every new frontend design is drafted with `/design` and confirmed by the
  owner before implementation.
- **F5** — Keep/Revert is dropped; clicking a font saves it, like the theme picker.
  Needs a short ADR amending 0037.
- **F4/F5** — preferences move **server-side** (`user_preference`), with `localStorage`
  demoted to a pre-hydration cache. Guest preferences must survive account claiming.
- **B7** — PDF/docx/txt first, standalone image uploads later. **PDFs go straight to
  flash-lite**, which handles them natively (verified); no OCR dependency.
- **AskAI budget** — 200 questions/user/day, and generation keeps a reserved floor
  (start 40/60), with the consumer tagged on every ledger row.

## Still open

Nothing blocking. The next session can start on Phase 1 Wave 1.
