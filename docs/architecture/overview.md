# Spoin — Architecture Overview

> Read this first. It is the mental model everything else assumes.
> If you only read one document before touching the codebase, read this one.

> **On the name:** the product is **Spoin**; the codebase is still `spoin` until the
> single-sweep rename in [ADR-0020](../adr/0020-rename-to-spoin.md) / task
> [0007](../tasks/0007-rename-to-spoin.md) runs. Nothing in this document changes with it.

## What Spoin is

A swipeable feed of AI-generated knowledge flash cards. Users pick topics, receive
bite-sized cards calibrated to their difficulty level, and can go deeper on any card
via inline AI chat or personal notes.

Web first. A React Native app comes later and shares this exact backend.

## The one sentence that determines the whole design

> **The feed read path must never touch an LLM.**

A swipe is a ~50ms interaction. An LLM call is 2–10 seconds. These cannot coexist on
one code path. Therefore Spoin is not "an app that calls an LLM" — it is:

- a **content factory** (slow, async, batched, expensive), feeding
- a **content warehouse** (Postgres), read by
- a **serving layer** (fast, cheap, no LLM anywhere in it).

The AI lives in the *write* path. Never the read path.

## The second consequence: cards are shared, not personal

Generation costs money and is rate-limited. So we do **not** generate
"Anubhav's card about Kubernetes." We generate "a card about Kubernetes at
difficulty 3", store it once, and serve it to everyone who qualifies.

**Personalization is selection and ranking over a shared corpus — not generation.**

This is the same shape as a real recommender system, and it is the single most
important thing to internalise before reading any other doc.

## Subsystem map

```
                    ┌─────────────────────────────────────┐
   WRITE PATH       │  Topic Registry → Generation Planner │   slow, async,
   (offline)        │         ↓                            │   batched, quota-bound
                    │  Job Queue → LLM Workers → Quality   │
                    │              ↓            Gate       │
                    │         Embeddings → Dedup           │
                    └──────────────┬──────────────────────┘
                                   ↓
                        ┌──────────────────────┐
                        │   Content Corpus     │   Postgres + pgvector
                        │  cards, topics,      │
                        │  embeddings          │
                        └──────────┬───────────┘
                                   ↓
   READ PATH        ┌──────────────────────────────────────┐
   (online)         │ Candidate Gen → Seen Filter → Rank   │   < 100ms,
                    │              → Page                  │   no LLM
                    └──────────────┬───────────────────────┘
                                   ↓
                              Web client
                                   ↓
                    ┌──────────────────────────────────────┐
   FEEDBACK         │  Engagement Events → aggregation →   │
   LOOP             │  taste vector + difficulty calibration│
                    └──────────────────────────────────────┘

   SIDE PATH:  Card Chat — synchronous, streaming, per-user, rate-limited.
               Deliberately separate from the feed: different latency budget,
               different cost profile, different failure mode.
```

Each subsystem has a **different performance and cost profile**. That — not tidiness —
is why they are separated. You cannot tune them together.

## Subsystem responsibilities

| Subsystem | Owns | Latency budget | Cost profile |
|---|---|---|---|
| Topic Registry | Canonical topics, aliases, per-user display names | ms | free |
| Generation Planner | Deciding *what* to generate next, and in what priority | batch | free |
| Job Queue | Durability, retries, parallelism | batch | free |
| LLM Workers | Producing card content | seconds–minutes | **scarce (quota)** |
| Quality Gate | Rejecting bad/duplicate cards, and validating visual slots/reuse caps deterministically | seconds | cheap |
| Feed Serving | Candidate generation, seen-filtering, ranking, pagination | **< 100ms** | cheap |
| Engagement | Ingesting swipe/read/save events, aggregating into taste signals | ms write | cheap |
| Quiz Bank | Questions generated from cards; sampling, seen-tracking | batch gen / ms read | cheap |
| Quiz Grading | MCQ deterministic; free-text via LLM against a rubric | seconds | **scales with attempts** |
| Card Chat | Synchronous per-user LLM conversation | streaming | **scarce (quota)** |

## Hard rules

These are not style preferences. Breaking any of them breaks the architecture.

1. **No LLM call in a request that serves the feed.** Ever.
2. **Business logic lives in the API, never in the web app.** The React Native app will
   consume the same API with no privileged access. If the web client can do something
   the mobile client can't, that's a bug.
3. **Nothing outside `ContentGenerator` imports LangChain.** See [ADR-0002](../adr/0002-langchain-behind-an-interface.md).
4. **Every LLM call goes through the quota governor.** See [ADR-0003](../adr/0003-free-tier-first.md).
5. **Embeddings run locally, never against a paid/quota'd API.** Quota is reserved for
   card generation, which is the only thing that genuinely needs a frontier model.
6. **No free-tier accommodation may require a rewrite to undo.** Everything that changes
   when we start paying must be config, not code.
7. **Every LLM interface takes a collection, never a single item.** The free tier meters
   requests, not tokens: batch everything, never economize on output size.
   See [ADR-0005](../adr/0005-batch-llm-calls.md).
8. **The generator is trusted for taste, never for constraints.** Anything that must be
   *true* is enforced or independently verified outside the model; anything that merely
   needs to be *good* is the model's job. This is why the quality gate re-rates difficulty
   rather than trusting the self-report, why `archetype` is derived
   ([ADR-0017](../adr/0017-card-archetypes.md)), and why ASCII scene reuse and slot
   lengths are checked server-side ([ADR-0021](../adr/0021-ascii-scene-library.md)).
   A constraint stated only in a prompt is a wish.

## Where to go next

- [ADR index](../adr/) — every significant decision and *why*
- [content-model.md](content-model.md) — what a card actually is
- [ADR-0021](../adr/0021-ascii-scene-library.md) / [ADR-0022](../adr/0022-dual-titles.md) —
  how cards get a personality (ASCII scenes, playful titles) without the write path losing
  the literal, machine-readable version of what a card teaches
- [generation-pipeline.md](generation-pipeline.md) — how the corpus gets filled
- `docs/architecture/feed-algorithm.md` — candidate → filter → rank *(not yet written)*
