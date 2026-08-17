# ADR-0004: Shared canonical topics with per-user display names

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav
- **Amended by:** [ADR-0025](0025-batched-llm-topic-matching.md) -- the "Matching is
  banded, not a single threshold" section below is superseded (no more auto-merge/
  auto-new thresholds; every topic gets an LLM opinion, batched). The canonical-topic /
  alias / shared-entity model in the rest of this ADR is unaffected. The body below is
  left as originally written; read ADR-0025 alongside it.

## Context

Users can add custom topics beyond the predetermined list. Taken naively, this breaks
the economics the whole architecture rests on.

Spoin's cost model works because **cards are shared**: one card about Kubernetes
serves every user interested in Kubernetes. But if 1,000 users each add 3 unique
custom topics, we get 3,000 topics with one reader each -- and generation cost silently
converts from _shared_ to _per-user_, which is precisely what the architecture exists
to prevent. Under a hard free-tier quota (ADR-0003), that is fatal, not merely expensive.

The saving observation: most "custom" topics are not novel. `k8s`, `kubernetes`, and
`container orchestration` are one topic wearing three names.

## Decision

### Canonical topics, personal labels

```
topic         canonical entity -- owns the corpus and the embedding
topic_alias   raw strings mapping to a canonical topic ("k8s" → kubernetes)
user_topic    (user_id, topic_id, display_name) -- what THIS user calls it
```

Content is generated once per `topic`. The UI always renders
`user_topic.display_name`. One user sees "k8s", another sees "Kubernetes", both read
the same cards. **The user experiences a topic they named themselves; the system
stores one shared entity.**

This pattern -- _shared entity, personal label_ -- will recur. Name it when you see it.

### Matching is banded, not a single threshold

Cosine similarity has **no absolute meaning**; it is model-specific. On typical modern
embedding models, unrelated short strings sit near ~0.7 baseline while true synonyms
land around 0.85–0.92. A single hard-coded gate at 0.95 would merge almost nothing and
we would get the long-tail explosion regardless.

Thresholds are therefore **calibrated, not guessed**: a labeled set of ~50 pairs
(half should-merge, half should-not, including adversarial ones), run through our
actual embedding model, thresholds placed where the two distributions separate.
**Recalibrated whenever the embedding model changes.**

### Two-stage matching: cheap recall, expensive precision

The cost of a wrong merge is far higher than a wrong split. A false split costs some
duplicate generation. A false merge means a user asks for Java and receives JavaScript --
which reads as _broken_ -- and it is baked into the alias table.

Embeddings are weakest exactly where users are most likely to trip them:
`Java`/`JavaScript`, `React`/`React Native`, `C`/`C#`/`C++`, and `Go`/`Golang`
(which _should_ merge) versus `Go`/`Rust` (which should not).

```
similarity > high band  → auto-merge
similarity in mid band  → LLM judge: "are these the same subject?" → decide
similarity < low band   → create new canonical topic
```

The LLM judge fires on a minority of custom topics, costs one small call, and its
verdict is **cached permanently in `topic_alias`** -- that pair is never paid for again.

_(Cheap filter narrows the field, expensive verifier makes the call. This same pattern
reappears in the feed ranker.)_

### Merges are reversible

The mapping lives in `topic_alias` as data. We never rewrite a user's topic row in
place. When we discover a bad merge -- and we will -- the fix is repointing an alias,
not archaeology on user records.

## Consequences

**Easier**

- The shared-corpus economics survive custom topics, which makes custom topics a
  feature rather than a bankruptcy vector.
- Users get the feeling of a personal, self-named topic set at no extra generation cost.
- pgvector is already required for this, so no new infrastructure.

**Harder**

- Threshold calibration is real work (about an afternoon) and must be redone on every
  embedding model change. Skipping it produces a system that looks tuned but is a
  superstition.
- The LLM judge is another quota consumer, though a small and permanently-cached one.
- Display-name divergence has edge cases: a user naming a topic something idiosyncratic
  may find the card content's vocabulary doesn't match their label. Acceptable.

**Committed to**

- Custom topics are rationed per user and enter the queue at lower priority than
  canonical topics (ADR-0003 §6).

## Alternatives considered

**No custom topics -- fixed list only.** Solves the economics completely and costs the
product a real differentiator. Rejected.

**Single similarity threshold.** Simpler. Rejected because it has no defensible value,
and because it fails on precisely the near-miss pairs users actually type.

**Pure LLM matching, no embeddings.** More accurate, but one LLM call per custom topic
per user against a hard quota ceiling. Rejected on cost -- the embedding pre-filter
removes ~90% of those calls.

## Revisit when

- Measured false-merge rate causes user complaints → widen the mid band so the LLM
  judge handles more cases.
- The canonical topic count grows faster than users → matching is too strict; recalibrate.
- A brute-force similarity scan over all topics gets slow → add a pgvector ANN index
  (HNSW). Not needed at low topic counts; do not build it early.
