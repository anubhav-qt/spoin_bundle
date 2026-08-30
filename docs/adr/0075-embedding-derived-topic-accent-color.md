# ADR-0075: The default topic accent hue is embedding-derived and materialized at subscribe time

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Anubhav
- **Amends:** [ADR-0034](0034-per-topic-accent-color.md) — the default hue is no
  longer a client-side positional computation; it is chosen server-side from a
  colour vocabulary by embedding similarity, deduplicated against the user's other
  topics, and written into `UserTopic.accent_hue` at subscription time.
  [ADR-0051](0051-topic-color-opt-out.md)'s `-1` opt-out and explicit `0-359`
  states are untouched.

## Context

ADR-0034 gave every topic a per-subscription accent hue. When `accent_hue` is
`null` the **client** computes the default itself (`lib/topicColor.ts`): the first
10 topics a user follows, by subscription order, get ten curated hues 36° apart;
past the 10th the default is `hash(topic_id) % 360`. Two things about that default:

- It carries **no meaning**. A topic about oceans is as likely to come out red as
  blue. The hue is a function of list position and a string hash, nothing else.
- Past 10 topics it is not even guaranteed **distinct** — two hashes can land a few
  degrees apart and two unrelated topics then read as the same colour, which is the
  exact failure ADR-0034's curation existed to avoid, reintroduced past the tenth
  slot.

The finish-line ask (plan §"Tier 2", B6) is a default whose *meaning* fits the
topic — an ocean topic leans blue, a biology topic leans green — while still
avoiding a colour another of that user's topics already occupies.

Meaning-from-similarity is not something the client can compute. It needs an
embedder (server-only, ADR-0003 hard rule 5), a colour vocabulary, and the set of
hues the user's other subscriptions already use. And the result must be **stable**:
a topic's colour cannot shift because the user later followed a different topic. So
the computation moves server-side and its output is persisted, which is a real
reversal of ADR-0034's "compute lazily on the client, never write a row just to
have a default" — argued below.

## Decision

### A colour vocabulary, shipped as static data, embedded at runtime

`apps/api/src/spoin/topics/accent_color_data/colors.json` holds ~200–300 named
colours, each `{"name": str, "hue": int}` with `hue` in `0–359`, spread to cover
the wheel. Names are evocative and domain-suggestive ("ocean", "moss", "rust",
"slate", "orchid", "amber", "storm"…), because the name is what gets embedded and
compared against the topic's embedding.

The vocabulary's **name strings are embedded at runtime** through
`spoin.embeddings.get_embedder()` and cached (`lru_cache`), exactly as
`content/ascii_library.py` embeds its ~2,500 titles. No precomputed vectors are
shipped: the embedder backend varies (`FastEmbedEmbedder` in production, the
`HashEmbedder` stand-in without the model), and a vector produced by one is
meaningless to the other. Embedding ~300 short strings once per process is
negligible and matches the ASCII library's existing cost profile.

### Assignment, at subscription time, deterministic arithmetic over a taste-grounded ranking

When a `UserTopic` row is created (`subscribe`, `complete_onboarding`,
`request_topic`, `request_topics_batch`), the service assigns `accent_hue`:

1. **Candidate ranking (taste).** Take the topic's `Topic.embedding` (reuse it —
   it already exists from ADR-0025 matching; embed the canonical name on the spot
   only if it is `null`). Rank the vocabulary by cosine similarity to it. This
   yields a best-first list of candidate hues.
2. **The "used" set (constraint).** Collect the effective hue of every *other*
   subscription this user has: an explicit `0–359` as-is; a `-1` skipped
   entirely; a `null` (legacy) row resolved through the ported positional default
   (`default_hue_positional`, the exact Python port of today's `defaultTopicHue`)
   so dedup is robust even across pre-ADR-0075 rows.
3. **Pick (constraint).** Walk the candidate list best-first and take the first
   hue whose minimum wrap-aware angular distance to every hue in the used set is
   ≥ `ACCENT_HUE_MIN_DISTANCE` (proposed **25°**). Persist it.
4. **Fallback (constraint).** If no candidate clears the distance filter — the
   user already has enough topics that the wheel is crowded — fall back to
   `default_hue_positional(topic_id, subscription_index)`, i.e. today's curated-10
   / hash-beyond behaviour, and persist *that* concrete value.

Steps 2–4 are pure arithmetic and independently checkable — the "generator trusted
for taste, never for constraints" rule from CLAUDE.md applied to colour: semantics
come from embeddings, distinctness is enforced by angle math, never asked for.

### Degradation when embeddings are unavailable

If `get_embedder()` returns the `HashEmbedder` stand-in (fastembed not installed —
the dev/test default), the whole assignment is **skipped** and `accent_hue` is
left `null`. The client's `defaultTopicHue` then renders the positional default
exactly as it does today. This is the "degrade to today's curated spread when
embeddings are unavailable" requirement, and it keeps the existing test suite —
which runs on `HashEmbedder` and asserts `accent_hue is None` on fresh
subscriptions — valid unchanged. `test_accent_color.py` pins both directions: a
subscription under `HashEmbedder` gets `accent_hue is None`; one under an injected
real-vector stub embedder gets a concrete hue at least `ACCENT_HUE_MIN_DISTANCE`
from every hue the user's other topics use.

### `null` semantics, and no backfill

`null` previously meant "no write is ever needed; the client computes the default
forever." It now means "**no server-assigned hue** — a pre-ADR-0075 subscription,
or one created without a real embedder." Both still render through the unchanged
client `defaultTopicHue`, so nothing about existing rows changes visually.

**No backfill.** Existing `UserTopic` rows in the live DB stay `null`. A bulk
`UPDATE` over live data is gated on the owner's explicit approval (CLAUDE.md), and
ADR-0051 already rejected a `UserTopic` backfill for the same reason. New
subscriptions get a materialized hue from ADR-0075 onward; old ones keep working.

### `set_color(hue=None)` re-runs the assignment

ADR-0034's `PATCH /topics/{id}/color` with `{hue: null}` meant "reset to the
client default." It now **re-runs the ADR-0075 assignment** (excluding the current
topic from the used set) and persists a fresh materialized hue — "reset" gives you
a good automatic colour again, not a hash. With no real embedder it writes `null`,
as before. `{hue: -1}` and `{hue: 0–359}` are unchanged.

### The client does not change

`lib/topicColor.ts` already renders a concrete `accent_hue` int. ADR-0075 only
means the server now sends one where it used to send `null`. `topicHue()`,
`explicitTopicHue()`, `NO_TOPIC_COLOR`, and `defaultTopicHue` (still the renderer
for any `null` that reaches the client) are all untouched. This is why the
decision is *materialize server-side*, not *add a computed read-only field*: it is
the lower-churn choice on the client and the only one that makes colours stable.

## Consequences

**Easier**

- A mixed feed's topic colours now carry a loose semantic association instead of
  being arbitrary, and past-10-topics colours are distance-filtered instead of
  raw-hash.
- The dedup logic reads plain integers off `UserTopic`; no client/server hue
  computation has to agree beyond the shared positional fallback.
- `set_color(null)` becomes a genuine "give me a good colour" action.

**Harder**

- ADR-0034's "never write a row just to have a default" is reversed for new rows.
  The justification is that this default is not a pure function of
  `(topic_id, index)` — it needs the embedder and the user's other hues — and it
  must not move when the user's topic set later changes, which a recompute-on-read
  field could not guarantee.
- `null` now has a mixed population (legacy rows + rows created under
  `HashEmbedder`). A reader cannot tell the two apart from the value alone. They
  render identically, so this is a code-comprehension cost, not a behavioural one;
  the field comment and this ADR carry the explanation.
- Colour quality is only as good as the vocabulary. A thin or badly-hued vocab
  gives less apt colours — but still *distinct* ones, since distinctness is the
  arithmetic in step 3, not a vocab property. Vocabulary tuning is a standing task
  (like ADR-0068's ASCII library), not a one-time job.
- The min-distance is best-effort, not a guarantee. A user with more than
  ~`360 / ACCENT_HUE_MIN_DISTANCE` (~14) topics will exhaust the wheel and fall
  back to the positional default — the same ceiling ADR-0034 hit at 10, moved out
  a little and softened.
- `subscribe()` and `complete_onboarding()` gain an `embedder` parameter, threaded
  from the router the way `request_topic` already receives one.

## Alternatives considered

**A runtime-derived, never-persisted hue on `TopicOut`.** Keeps ADR-0034's
"no write" principle. Rejected: a topic's colour would then change every time the
user's other-topic set changed (a follow, an unfollow, a recolour moves the
distance filter's inputs), and a colour that shifts under you is worse than an
arbitrary one that is stable. It also pays the vocabulary search on every topic
read instead of once at mint.

**A runtime LLM call to pick a colour name for the topic.** Rejected on CLAUDE.md
grounds: embeddings are free and never quota'd, colour-from-similarity is exactly
the kind of taste that similarity grounds well enough, and a metered call on the
subscription path is one more user-facing failure mode for no benefit.

**Ship precomputed vocabulary embeddings as static vectors.** Rejected: the
embedder backend differs between production and dev/test, so vectors baked from one
are noise to the other. Embed-at-runtime-and-cache is the established
`ascii_library.py` pattern and avoids the problem entirely.

**Backfill `UserTopic.accent_hue` for existing rows.** Rejected without asking:
CLAUDE.md gates a bulk `UPDATE` on live data behind explicit owner approval, and
ADR-0051 already rejected a `UserTopic` backfill for this feature. Legacy rows
render correctly through the unchanged client default, so there is nothing to fix.

**Keep the positional default (do nothing).** The status quo. Rejected because the
ask is specifically a colour whose meaning fits the topic; a list index and a
string hash deliver neither meaning nor, past ten topics, distinctness.

## Revisit when

- Topics visibly converge in colour in a real busy feed — widen the vocabulary's
  hue coverage, or raise `ACCENT_HUE_MIN_DISTANCE`.
- Recompute-on-read becomes cheap *and* desirable — e.g. a product decision that
  colours *should* rebalance as a user's topic set grows — at which point the
  persist-at-mint choice is worth reopening.
- A `Topic`-level shared colour is ever wanted (an editorially branded flagship
  topic) — same note as ADR-0034's and ADR-0051's "Revisit when": a `Topic` field
  layered on top, with `UserTopic.accent_hue` still winning when set.
