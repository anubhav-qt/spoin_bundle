# Content Model — what a card is

> Prerequisite: [`overview.md`](overview.md). This document assumes you understand
> that cards are **generated once and shared across users**, and that the feed read
> path never calls an LLM.

This is the highest-leverage schema in the project. The generation prompt, quality
gate, dedup logic, ranker features, chat context, and UI all inherit its shape.

## The card

```
card
  id                  uuid, pk
  family_id           uuid    groups all versions of the same card
  version             int     1, 2, 3...
  status              draft | active | rejected | superseded

  topic_id            fk -> topic (canonical topic; see ADR-0004)
  subtopic_id         fk -> subtopic (curriculum slot; see ADR-0007)
  difficulty          beginner | intermediate | advanced

  title               str     display title; playful some of the time (see note below)
  canonical_title     str     literal title; what machines read (see note below)
  summary             str     the collapsed-state hook (see note below)
  body                str     markdown; scrolls inside the expanded card
  archetype           str[]   content shapes present in body (see note below)
  is_hero             bool    at most one true per subtopic (see note below)

  visual_id           str     null; key into the ASCII scene catalog (see note below)
  visual_slots        jsonb   null; {slot_name: text} for that scene

  source              generated | authored
  author_id           fk -> user, null for generated

  content_embedding   vector  for near-duplicate detection
  gen_meta            jsonb   model, prompt_version, generated_at, batch_id

  created_at
```

### Field provenance

| Field | Origin |
|---|---|
| `title`, `canonical_title`, `summary`, `body` | **Generated** (or authored, for user-submitted cards) |
| `visual_id`, `visual_slots` | **Selected** by the generator from a curated catalog — never drawn by it, and validated deterministically after (see [ADR-0021](../adr/0021-ascii-scene-library.md)) |
| `difficulty` | **Requested** at generation time, then **independently verified** by the quality gate |
| `topic_id` | Requested at generation time, verified by the quality gate |
| `content_embedding` | **Derived** locally, post-generation |
| `archetype` | **Derived** locally from `body`, post-generation — never requested, never LLM-self-reported (see [ADR-0017](../adr/0017-card-archetypes.md)) |
| `is_hero` | **Planned** by a curriculum/content step, one per subtopic — today set by the fixture seeder only (see below); never a per-card LLM self-report |
| `status`, `version`, `family_id` | **System-owned**. Never set by the generator |

### On `title` / `canonical_title`

**Decided in [ADR-0022](../adr/0022-dual-titles.md); schema and generation prompt built,
see [generation-pipeline.md](generation-pipeline.md).** `title` is what the feed card
face shows and is playful some of the time (the proportion is a config value, not a code
path). `canonical_title` is the literal, descriptive name of the concept and is always
present. `CardDraft.canonical_title` is a required field (`generation/base.py`), and
`langchain_impl.py`'s card-writing prompt explicitly instructs the model not to make it
identical to `title` every time. What's still open: whether the *proportion* of playful
titles the prompt actually produces matches ADR-0022's intent — unverified without a
live Gemini key.

**`canonical_title` is the default for every consumer except the feed face.** Quiz stems,
remediation links, progress and coverage lists, and search all read it. The one that is
easy to get wrong and silent when you do: the generation prompt's already-covered list
takes **both** — canonical so the model can tell a subject is taken, display so it doesn't
invent the same joke twice.

`content_embedding` stays derived from `body`. Neither title feeds dedup.

### On `visual_id` / `visual_slots`

**Decided in [ADR-0021](../adr/0021-ascii-scene-library.md); schema fields exist, catalog
does not.** Cards may carry an ASCII scene. The generator **selects** a scene from a
curated, hand-authored catalog and writes its dialogue slots; it never draws art. Models
are unreliable at ASCII art and none of the four quality-gate checks below can detect a
broken drawing — the catalog is what replaces the missing detector.
`card.visual_id`/`visual_slots` and `CardDraft.visual_id`/`visual_slots` exist (so a
future catalog needs no migration or corpus regeneration to land), but with no catalog to
select from, nothing populates them today — see
[generation-pipeline.md](generation-pipeline.md).

The card stores a reference plus text, never rendered art, so fixing a scene improves
every card using it with no regeneration. Three constraints are enforced server-side, not
prompted: slot text over the scene's `max_chars`, an unknown `visual_id`, and a scene
already used on two active cards in the topic all cause the **visual to be dropped and the
card kept**. Failure degrades to "no art", never to "broken art".

### On `summary`

The collapsed card shows a short preview; the expanded card scrolls the full `body`.

`summary` is a **purpose-written hook**, not a truncation of `body`. It costs nothing:
it is one additional field in the same structured output on the same request, and the
free tier meters **requests, not tokens** (see [ADR-0005](../adr/0005-batch-llm-calls.md)).

The reason it is a separate field rather than the first N lines of `body`: the opening
of a good explanation is usually throat-clearing, and the line that stops a scroll is a
different job from the line that opens an essay. Truncation also cuts mid-sentence.

**Fallback:** if `summary` is missing, render `body` with CSS `line-clamp`. Truncation
is the safety net, not the design.

### On `archetype`

A set of content-shape tags — `code`, `diagram`, `comparison`, `ascii`, any subset, `[]`
for plain prose — used by the web client to pick a collapsed-state preview shape (a code
snippet gets a language badge + first line, a diagram gets a breadcrumb, and so on).
Full reasoning in [ADR-0017](../adr/0017-card-archetypes.md); the one thing worth
repeating here: it is **derived, not requested**. Unlike `difficulty`, whether a body
contains a fenced code block is objectively checkable from the text itself, so there is
no self-report to independently verify — the classifier (`content/archetype.py`) just
runs on `body` after it exists. The generation prompt is still expected to *use* these
markdown shapes where a subtopic calls for it (same spirit as `summary` below), it just
never emits `archetype` as a field.

`ascii` follows the same rule and is the easiest case of all: it is derived from
`visual_id is not null` (see [ADR-0021](../adr/0021-ascii-scene-library.md)). Note it is
derived from the *field*, not from `body` — ASCII scenes deliberately live outside the
markdown so the renderer owns their monospace box and column width.

### On `is_hero`

The card the web client renders as a never-collapsed visual anchor, with distinct
typography and a border treatment. Real mechanism (not yet built — see
[docs/tasks/0006](../tasks/0006-curated-hero-cards.md)): a content-planning step
designates exactly one hero per subtopic. Until that exists, the fixture seeder marks
the first card listed per subtopic. Either way this is a **planning decision**, not a
per-card judgment the generator makes about its own output — same category of thing as
`status`/`version`, just not fully automated yet.

### On `source` / `author_id`

Every card today is `generated`. The columns exist now because adding them later means
a data migration, and because user-authored cards (and monetising them) is a planned
direction. Cost today: two columns. No UI exposes authoring yet.

## The curriculum

Cards do not float loose inside a topic. Each topic is decomposed **once** into subtopics
across all three difficulties, and generation targets a specific subtopic. Full reasoning
in [ADR-0007](../adr/0007-curriculum-driven-generation.md).

```
subtopic
  id
  topic_id
  difficulty        beginner | intermediate | advanced
  title
  description       what this subtopic covers; feeds the generation prompt
  target_cards      planner's ideal count (ceiling + priority weight), 5-25
  min_cards         threshold at which the subtopic counts as covered
  position          ordering hint within the topic
  created_at
```

**The real bound is a card budget on the whole topic (~750 cards), not on any one factor.**
Capping cards-per-subtopic alone would just push unbounded growth into the subtopic count.
The budget is derived from completability: a tier should take 5-10 sessions, ~30 cards a
session, ~250 cards per tier, x3 tiers. Within that budget: 5-25 cards per subtopic,
~15-20 subtopics per tier.

Two self-correcting rules follow:

- **>25 cards wanted for a subtopic** → the subtopic is too broad, decompose it.
- **>~20 subtopics wanted per tier** → the topic becomes a **tour**, and the curriculum
  pass also emits the deeper sibling topics it introduces. The broad topic is *not*
  deleted. "Mathematics" stays subscribable and gives a genuinely good tour; its
  completion screen points at Linear Algebra, Calculus, Probability.

```
topic_edge(from_topic_id, to_topic_id, kind='deep_dive')
```

A **flat edge, not a tree** — hierarchy would rebuild the unbounded-nesting problem one
level up. Deep-dive topics are created as canonical topics immediately but get curricula
lazily, on first subscription. This seeds the topic graph and helps ADR-0004: a user
typing "linear algebra" later matches an existing topic instead of minting a new one.

Depth is fixed at **two levels**. Consequence: broad topics get *survey* curricula, and
their completion copy must say so honestly ("covered the essentials of Mathematics", not
"mastered Mathematics").

**Coverage is measured against `min_cards`, not `target_cards`.** The planner guesses before
generation happens and cannot know the quality-gate rejection rate; defining coverage
against its aspirational number leaves users stuck at 94% forever.

## Progression, quizzes and mastery

Full reasoning in [ADR-0009](../adr/0009-quiz-gated-progression.md), entry tier amended by
[ADR-0027](../adr/0027-self-selected-entry-tier.md).

**Difficulty past your entry tier is earned; the entry tier itself is trusted.** The user
picks their entry tier at subscribe time and starts there immediately — no quiz gates it.
Quizzes at or below that tier are open for unlimited practice retries (never change
progression); promotion past it still requires the same 80%-coverage-gated quiz described
below.

```
seen 80% of cards in EVERY subtopic of a tier
   └──▶ tier quiz unlocks   (LATCHED — never recomputed)
         └──▶ pass at 80% ──▶ promoted to next tier
               └──▶ ... ──▶ advanced ──▶ mastery quiz
```

**The unlock is latched.** Recomputing it would let background generation revoke earned
progress: a user at 8/10 cards (80%, unlocked) drops to 8/20 (40%, locked) the moment ten
more cards are generated. Once earned, recorded on `user_topic_progress` permanently.

**Quiz shape:** 9 MCQ (graded deterministically, returned immediately) + 1 free-text answer
graded by LLM against an explicit rubric. Weighted **70/30**, pass at **80%**. Unlimited
retries; a failed attempt returns a remediation card list rather than a cooldown.

**Questions are generated from cards** (`question.card_id`), never from the topic in the
abstract. This makes it structurally impossible to test material the corpus never taught,
and it means every wrong answer links directly to the card that teaches it.

Being asked about a card the user has not seen is **deliberate** (they only need 80%
coverage). The results screen surfaces those explicitly, which turns the quiz into a
discovery tool: *here is exactly what you did not know, and here is where to learn it.*

```
mastered = tier_content_complete[advanced] AND tier_quiz_passed[advanced]
```

Content completion alone triggers the *prompt* to take the mastery quiz. The mastery quiz
stays available after passing, with fresh questions each time; **mastery is permanent** and
never revoked by a later failed attempt.

After completion the topic enters **revisit mode**: seen cards are re-served at the user's
tier, with the completion state shown honestly rather than disguised as new content.

## Difficulty

Difficulty is a property of the **card**, not the user and not the pairing. Users hold a
current tier (earned via quiz, see above) and the feed mixes levels around it.

### Feed mix by user level

| User level | Current | Lower | Higher |
|---|---|---|---|
| Beginner | 80% | — | 20% (intermediate) |
| Intermediate | 70% | 20% (beginner) | 10% (advanced) |
| Advanced | 90% | 8% (intermediate) | 2% (beginner) |

**These percentages live in config, not code.** They will be tuned against engagement
data, and tuning must not require a deploy.

**The upward slice is a promotion signal.** A beginner who consistently engages with
their 20% intermediate cards is telling you they are ready to move up. v1 keeps
difficulty user-selected, but do not discard the data needed to make it adaptive.

### When the pool cannot satisfy the mix

**Partially superseded by [ADR-0026](../adr/0026-one-shot-generation-to-completion.md):**
point 2 below (the async fill trigger) no longer applies — generation is now a one-shot
run per topic to a fixed budget, not an ongoing refill loop, so there is no recurring
"starved slot" to trigger a fill for. Whether points 1/3/4 (degraded mode, hysteresis,
end-of-feed copy) still apply during a topic's *initial* one-shot run — the window before
its cards exist at all — is flagged as an open question in ADR-0026 and not resolved here.

The mix is a **target, not a guarantee**. With a thin corpus under free-tier quota,
this will fire constantly. Policy (see the note above on which parts still hold):

1. **Keep the mix honest.** Do not silently backfill with the current difficulty.
   Serve a shorter page instead.
2. **Trigger an async fill** for the starved `(topic, difficulty)` slot.
3. **Enter degraded mode** below `POOL_LOW`, exit above `POOL_HIGH`.
   Two distinct thresholds, deliberately. A single threshold flaps: the pool sits on
   the line, one card generates, you exit degraded, the user consumes it, you re-enter.
4. **End-of-feed state is honest.** On free tier a fill can take hours, not seconds
   (cron cadence plus possibly-exhausted daily quota). Show "more coming soon", never
   an indefinite spinner.

See [ADR-0006](../adr/0006-demand-driven-pool-fill.md) for job coalescing and the
fairness cap, both of which are required for this to be safe.

## Versioning

Improving the generation prompt and regenerating produces a **new row**, not an update.

```
family_id   groups versions          exactly one row per family is `active`
version     increments               older versions become `superseded`
```

**Why rows and not a column:** engagement data attaches to a specific card `id`. If v2
overwrote v1's row, every like and save collected against v1's text would silently
re-attribute to different content, quietly corrupting the ranking signal that the whole
personalization layer depends on.

v1 only records versions. How to *use* them (backfilling, A/B testing prompt versions,
retiring old text) is deliberately deferred.

## Quality gate

A generated card is `draft` until it passes. It never reaches the corpus otherwise.

**This is the target design; only structural validation exists today**
(`generation/gate.py`: non-empty body, nothing else) — cards go straight to `active`.
None of the four checks below (dedup, topic conformance, difficulty, factual accuracy)
are built. See [generation-pipeline.md](generation-pipeline.md).

Note the division of labour established in [ADR-0007](../adr/0007-curriculum-driven-generation.md):
**prevention** (curriculum targeting + title lists in the prompt) optimizes *cost*;
**detection** (below) guarantees *correctness*. We keep both. A cheap preventive layer never
earns the right to remove the check.

### 1. Near-duplicate detection

Embed the card body locally (`fastembed`, free and unlimited) and compare against
existing cards **within the same subtopic**. Above the duplicate threshold, mark `rejected`.

**Intra-batch dedup is also required.** Comparing against the stored corpus does not catch
a model writing three near-identical cards *within a single response of ten*. The batch must
be compared against itself before insert.

Note this is a **different embedding** from the topic embedding used for canonicalization
in ADR-0004. Same technique, different vectors, different thresholds. Calibrate
separately.

### 2. Topic conformance

Compare `content_embedding` against the topic embedding. Cheap, local, catches drift
where the generator wandered off subject.

### 3. Difficulty conformance — must be an independent judgment

The subtlety that makes or breaks this check:

- "Generate a **beginner** card about X" returns a card tagged `beginner` **because that
  is what was asked**. The tag echoes the request and validates nothing.
- Only an **independent** rating, made without knowledge of the requested level, can
  disagree, and disagreement is the entire point of a gate.

Models are unreliable at critiquing their own output inside the same call, so the
self-report is not sufficient.

**Implementation:** a **batch judge**. Collect ~20 `draft` cards, strip their requested
difficulty, send them in one request, receive 20 independent ratings, flag only the
disagreements for review. One request validates twenty cards, which makes it affordable
to run on everything. See [ADR-0005](../adr/0005-batch-llm-calls.md).

### 4. Factual accuracy

Checks 1-3 all pass a confidently-wrong card. For a product whose value is teaching people
true things, a hallucinated fact in a **shared** corpus reaches every subscriber of that
topic — the most serious failure mode in the system.

This check runs in the same batch judge pass, and matters most for locally-generated cards
([ADR-0008](../adr/0008-local-gpu-generation.md)), where the generating model is weaker.
The scarce cloud model is deliberately spent here, on *judgment*, rather than on prose:
one cloud request verifies twenty locally-generated cards.

`gen_meta` records which backend produced each card, so quality can be compared across
backends and a bad batch can be traced and retired.

## Quiz schema

```
question
  id
  subtopic_id
  card_id           source card; makes remediation and coverage possible
  difficulty
  kind              mcq | free_text
  stem
  options[]         mcq only
  correct_index     mcq only
  rubric            free_text only; explicit 0-3 levels
  reference_answer  free_text only; grading context
  explanation
  status            draft | active | rejected
  embedding         dedup within subtopic
  gen_meta          always cloud + strongest model (see ADR-0009)

quiz_attempt
  id, user_id, topic_id, difficulty
  kind              placement | promotion | mastery
  score, passed
  started_at, submitted_at

quiz_attempt_question
  attempt_id, question_id, user_answer, correct, rubric_level

user_topic_progress
  user_id, topic_id
  current_difficulty
  tier_unlocked[3]          latched, never recomputed
  tier_content_complete[3]
  tier_quiz_passed[3]
  mastered_at
```

## Engagement surface

From the card UI: like, bookmark, note, ask AI, share. Plus implicit signals (view,
dwell time, swipe-past).

Engagement rows reference a specific card `id`, which is what makes the versioning rule
above load-bearing rather than bookkeeping.

Notes are **per-user, per-card** and private. Ask AI opens a synchronous streaming chat
scoped to the card, on the side path in `overview.md`, with its own rate limit.

Full schema and the events/state/aggregates split in [ADR-0011](../adr/0011-engagement.md).

**Seen-state is three states, not a boolean** ([ADR-0010](../adr/0010-feed-serving.md)):

```
UNSEEN     never shown
DEFERRED   shown, not expanded  -> returns after the difficulty cycle completes
SEEN       expanded AND ("Got it" tapped OR dwell >= threshold)
                                -> counts toward the 80% gate, never returns
```

Scrolling past never counts. Beyond that, either an explicit **"Got it"** tap or a dwell
threshold marks the card seen — fast readers tap, everyone else is covered by dwell with no
friction. The two are recorded as **separate events**: explicit completion is a much stronger
signal for ranking than elapsed time.

**Superseded by [ADR-0012](../adr/0012-feed-visual-design.md):** "Got it" no longer lives at
the end of the expanded body — it moved to a toggleable circular icon in the action row, the
only "Got it" affordance now. The icon stays disabled until the card has been expanded at
least once this session, so "expanded AND" above still holds: the icon is a faster way to
confirm completion after a look, not a way to skip the look.

## Custom topics

Three free custom topics per user. Unlimited is a planned premium feature.

The limit is on `user_topic` rows and is **enforced server-side**. Note the interaction
with ADR-0004: if a user's custom topic canonicalizes onto an existing topic, it still
consumes one of their three slots. They are buying slots in their own topic list, not
new entries in the shared corpus.

## Open questions

- `title` character cap: pick N, and check it against the longest realistic render.
- Duplicate threshold for `content_embedding`: needs the same calibration treatment
  the topic thresholds in ADR-0004 originally used — note ADR-0004's own topic-matching
  thresholds are gone as of ADR-0025, so this is no longer "the same technique reused,"
  just a separately-needed calibration for a different check (near-duplicate card
  detection, not topic matching).
- `POOL_LOW` / `POOL_HIGH` values: only meaningful if ADR-0026's open question resolves
  in favor of keeping degraded-mode serving for a topic's initial one-shot generation
  window. Do not implement against these until that's decided.
- `min_cards` as a fraction of `target_cards`: needs a default. Somewhere around 50-60%
  is the intuition, but it should be checked against real rejection rates.
- Whether `position` on subtopics is ever used. Cards are standalone and unordered by
  design; `position` exists only as a curriculum-authoring hint and may prove dead weight.
