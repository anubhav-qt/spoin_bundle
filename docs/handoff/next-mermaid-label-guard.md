# Handoff: mermaid edge-label guard + fix card `0afd7193`

**Written:** 2026-08-31 (end of session 7) — paste the "Prompt" block below into a
fresh session.

---

## Prompt

> Continue spoin v1 work on branch `feat/v1-finish-line` (pushed, HEAD `b79a41d`).
>
> Read `CLAUDE.md` first, then the section below. Two linked tasks, then continue
> down the v1 finish line.
>
> ### Task A — stop new cards being minted with unparseable mermaid
>
> **Symptom.** Card `0afd7193-75e6-4f35-bb53-ee8145ef8819` ("Bridging Screen
> Clicks to Game Worlds", topic "Building a Game Engine using RayLib") renders in
> the feed as a raw monospace source box instead of a diagram. Its body carries:
>
> ```
> flowchart TD
>   MP[GetMousePosition] -->|Screen Pixels (e.g., 500, 300)| CST[GetScreenToWorld2D]
>   CAM[(Camera2D State)] --> CST
>   CST -->|World Coordinates (e.g., 1250, -420)| GE[Interact with Game Entities]
>
>   style MP fill:#e2f0d9,stroke:#595959
>   style CST fill:#fff2cc,stroke:#d6b656
>   style GE fill:#d9ead3,stroke:#6aa84f
> ```
>
> The `(` inside the `|Screen Pixels (e.g., 500, 300)|` / `|World Coordinates
> (e.g., 1250, -420)|` edge labels is invalid mermaid — the flowchart grammar
> rejects an unquoted `(` in a pipe-delimited label (`Expecting … got 'PS'`).
> One bad label fails the whole diagram. `MermaidBlock.tsx` already catches the
> parse failure and falls back to the source box quietly (fixed session 7,
> commit `3023b73`); this task is about the **generation** side so new cards
> don't ship broken.
>
> **Do:**
>
> 1. **Add a check** to `_mermaid_structural_issue` in
>    `apps/api/src/spoin/generation/langchain_impl.py` (~line 706 — the
>    "deliberately permissive" light structural check). Detect an edge label
>    (`|…|`, or the `-- text -->` form if the grammar allows it) that contains an
>    unquoted `(`, `)`, `[`, `]`, `{`, or `}`, and return a short reason string
>    (e.g. `"edge label 'Screen Pixels (e.g., 500, 300)' has unquoted
>    parens/brackets — wrap the label in double quotes"`). Keep it permissive in
>    spirit: a quoted label (`|"… (…)"|`) must pass. Existing behaviour — bracket
>    balance count, known-diagram-type keyword, has-edges — stays.
> 2. **Add a prompt rule** in `apps/api/src/spoin/generation/prompts/cards.py`
>    (the mermaid instructions block, ~lines 376–449): any edge label containing
>    punctuation — parens, commas, brackets, colons — must be wrapped in double
>    quotes, e.g. `A -->|"Screen Pixels (e.g. 500, 300)"| B`. This is the
>    "generator trusted for taste, check enforces the constraint" pattern from
>    CLAUDE.md — the check in step 1 is the real enforcement, the prompt line
>    just reduces how often it fires.
> 3. **Test.** Find the existing tests for `_mermaid_structural_issue` (grep
>    `_mermaid_structural_issue` / `malformed mermaid` under `apps/api/tests/`)
>    and add cases: unquoted-paren label rejected, quoted-paren label accepted,
>    the `CAM[(Camera2D State)]` cylinder-node shape (a legitimate `[(` ) NOT
>    falsely rejected. That last one matters — `[(...)]` is a valid node shape,
>    only `|…(…)…|` labels are the problem.
> 4. No ADR needed (small check + prompt line, no decision with alternatives).
>    If you disagree, write one — next number is **0078**.
>
> ### Task B — fix the existing card
>
> Card `0afd7193-75e6-4f35-bb53-ee8145ef8819` is live and broken. Two routes:
>
> - **Direct `UPDATE` (recommended, faster).** It's a pure syntax fix that
>   doesn't change meaning, so a body edit on the active row is defensible.
>   **This is a live-DB write to `spoin_db_2` — get the owner's explicit
>   approval first (CLAUDE.md), every time.** Replace exactly:
>   - `-->|Screen Pixels (e.g., 500, 300)|` → `-->|"Screen Pixels (e.g., 500, 300)"|`
>   - `-->|World Coordinates (e.g., 1250, -420)|` → `-->|"World Coordinates (e.g., 1250, -420)"|`
>   Change nothing else. Verify after: the card renders as a real diagram in the
>   feed.
> - **Repair lane.** Report the card on `/admin/repairs` and run a Fix. Correct,
>   but a multimodal LLM call for a two-character quote fix is overkill, and the
>   repair "fix" prompt has over-reached before (session 6 note).
>
> ### Then: continue the v1 finish line
>
> Per `docs/handoff/v1-finish-line-plan.md` (read its "Session progress log" —
> session 7 entry is current). Remaining, in plan order:
> 1. **Cockroach sequence** — task 0016 spike (go/no-go gate), then 0017→0021.
>    0016 is a big, self-contained investigation; consider giving it its own
>    session.
> 2. **B7 bring-your-own study material** (XL) — needs an ADR (0078) + its own
>    task sequence.
> 3. **Task 0034** — extract one shared `CollectionView` from Saved/Notes/Liked
>    + sweep dead `.saved-tile*` CSS + fold in leftover F6 microcopy. No gate,
>    pickup-ready. Plan wants it done before Phase 3 review.
>
> ### Environment / process
>
> - Live DB is `spoin_db_2` (`.env` points there; CLAUDE.md's "spoin_db" prose
>   is stale). Read-only SQL is fine; **any write needs owner approval every
>   time.**
> - Lint through the container: `docker compose exec api sh -c 'ruff check src
>   tests && ruff format --check src tests'` (host ruff version differs).
> - `make check` = ruff + `mypy src` (not tests) + pytest via
>   `docker compose --profile test run --rm test`. Keep green per commit.
> - Windows bind-mount HMR is unreliable for `.tsx`/`.css` — `docker compose
>   restart web` after web edits before trusting the browser. (Backend-only
>   here, so N/A for Task A.)
> - `git fetch` and check `origin/feat/v1-finish-line` before pushing — the
>   remote has had outside pushes.
> - Commit per logical change; deferred work gets a task doc + a row in
>   `docs/tasks/README.md`.
> - Don't start generation runs or touch `docs/notes/topic-queue.md` — the owner
>   drives runs.

---

## Session 7 recap (what's already on the branch)

Commits on `feat/v1-finish-line` since `4103658`:

- **`3023b73`** `fix(web): report feedback, mermaid fallback noise, hero visual
  for twinned art`
  - `submitReport` no longer swallows failures silently — surfaces an error,
    with specific "card was updated, reload" copy on a 404 (a superseded card
    row still held by a stale feed; that was the "report not submitting" bug).
  - `MermaidBlock` pre-parses with `mermaid.parse({suppressErrors:true})` and
    logs at `warn`, so a handled diagram-fallback no longer trips Next 15's dev
    error overlay.
  - `/admin/repairs` renders card bodies through the real `Markdown` component
    (now exported from `Card.tsx`) instead of dumping raw markdown.
  - `resolveHero`: when `visual_slots.art` and the body's leading fence are the
    same scene (`sameScene()` — ≥60% whitespace-token overlap), lead with the
    fuller copy and carry `visual_slots.alt` as a caption on any hero kind, not
    just the ascii branch. Fixes cards that showed the abbreviated body copy and
    dropped the caption.
- **design(loader)** + **`b79a41d`** `feat(web): SpoinWave — one branded loader
  everywhere (F12)`
  - `components/SpoinWave.tsx` + `.spoin-wave*` CSS: the "spoin" wordmark on a
    staggered baseline wave, `o` in accent, pure CSS, reduced-motion freezes it
    flat. `variant="page"` (full-viewport gate) / `variant="inline"` (buttons,
    modal loading lines — glyphs take `currentColor`).
  - Replaced `.auth-loader` (AuthProvider gate, AuthForm + onboarding buttons),
    `.btn-spinner` (RequestTopicBox), and the `.modal-loading` text lines
    (QuizModal, TopicDiscoveryModal, TopicStatsModal ×2). Deleted `.auth-loader`
    / `.btn-spinner` / `@keyframes auth-spin`.
  - `button:has(.spoin-wave[data-variant="inline"])` gets `min-width: 7rem` so a
    label→wave swap doesn't make the button jump.
  - `CardSkeleton` and `MermaidBlock`'s "drawing…" placeholder left as-is
    (content-shaped placeholders, not spinners).
  - `/design` concept canvas sources live in
    `docs/design/mockups/loader-concepts/` (the 2.4MB seeded payload is
    gitignored; `.dc.html` + `canvas.json` are the record). "Wave" was chosen.
- **F12 is done** — it was the last Wave-3 item.
