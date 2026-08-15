# Architecture Decision Records

An ADR captures **one significant decision and the reasoning behind it**, at the moment
it was made. The value is not the decision — it's the *why*, which is otherwise lost
within weeks.

## Why we bother

Two people, one codebase. Six months from now neither of us will remember why we
picked `procrastinate` over Celery, and we will waste an afternoon re-litigating it.
An ADR is how you disagree with a past decision *productively* — you read the original
reasoning, check whether its assumptions still hold, and supersede it if they don't.

## When to write one

Write an ADR when a decision is **expensive to reverse** or **non-obvious to a newcomer**:

- Choosing between technologies (Postgres vs. a vector DB)
- Establishing a boundary (nothing imports LangChain directly)
- Accepting a tradeoff deliberately (batch worker instead of a persistent pool)

Do **not** write one for reversible, local choices (function naming, file layout within
a module). Those belong in code review.

## Format

Copy `TEMPLATE.md`. Number sequentially. Never renumber.

## Lifecycle

An ADR is immutable once **Accepted**. If a decision changes, write a *new* ADR that
supersedes the old one, and add a `Superseded by ADR-NNNN` line to the original.
Do not edit history — the record of a decision we later reversed is often more
useful than the decision itself.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-python-fastapi-over-node.md) | Python + FastAPI over Node/NestJS | Accepted |
| [0002](0002-langchain-behind-an-interface.md) | LangChain, confined behind `ContentGenerator` | Accepted |
| [0003](0003-free-tier-first.md) | Free-tier-first infrastructure with a paid upgrade path | Accepted |
| [0004](0004-topic-canonicalization.md) | Shared canonical topics with per-user display names | Accepted |
| [0005](0005-batch-llm-calls.md) | Batch every LLM call; never economize on tokens | Accepted |
| [0006](0006-demand-driven-pool-fill.md) | Demand-driven pool fill with degraded serving and hysteresis | Accepted (amended by 0007) |
| [0007](0007-curriculum-driven-generation.md) | Curriculum-driven generation with a bounded, completable corpus | Accepted |
| [0008](0008-local-gpu-generation.md) | Local GPU generation for seed content, cloud verification | Accepted |
| [0009](0009-quiz-gated-progression.md) | Quiz-gated difficulty progression | Accepted |
| [0010](0010-feed-serving.md) | Feed serving: stratified selection, linear ranking, slate pagination | Accepted |
| [0011](0011-engagement.md) | Engagement: append-only events, mutable state, derived aggregates | Accepted |
