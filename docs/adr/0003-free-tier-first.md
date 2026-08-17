# ADR-0003: Free-tier-first infrastructure, with a config-only upgrade path

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav

## Context

Spoin is a self-funded two-person project shipping to real users. The rule set by
the team: **pay nothing until there is traction, then pay.** This is not a permanent
austerity constraint — it is a deferral. That distinction drives the entire decision.

The binding constraint is **not** CPU, storage, or bandwidth. It is **LLM generation
quota**, which free tiers meter in requests-per-day. A previous attempt at this product
died on exactly this: a pool-fill worker sized for more daily headroom than the free
tier actually provides, so the content pool could never fill.

## Decision

### 1. Managed free tiers, not a self-hosted free VM

An always-free VM (e.g. Oracle Cloud) offers more raw capability, but under
_free-until-traction_ the decisive property is **how cheaply we scale up**. On managed
tiers, scaling is a billing toggle and the connection string does not change.
Self-hosting would mean performing a data migration during our highest-stress week.

### 2. No accommodation may require a rewrite to undo

**This is the load-bearing rule of this ADR.** Everything that changes when we start
paying must be configuration:

| Free (now)                         | Paid (traction)          | Change type                 |
| ---------------------------------- | ------------------------ | --------------------------- |
| Neon free tier                     | Neon paid                | billing toggle              |
| Batch worker via cron              | Persistent worker pool   | env var + process type      |
| Gemini free key, low quota ceiling | Paid key, raised ceiling | config value                |
| Postgres as cache                  | Add Redis                | additive; nothing rewritten |

### 3. Generation runs as a scheduled batch job, not a persistent worker

At free-tier quota (order of tens of generations/day) a persistent worker pool has
nothing to do 99% of the time — and free hosting tiers sleep idle services anyway.
So generation runs on a **GitHub Actions cron** (~every 15 min): claim pending jobs,
spend that slice of quota, exit.

This also paces the daily quota across the day instead of exhausting it by 9am.
The same job functions run as a persistent loop later — different entrypoint, same code.

### 4. No Redis in v1

Redis's three jobs here were queue, cache, and rate limiting. With a batch worker
there is no poller to serve; at our scale Postgres handles caching and rate limiting
fine; and `procrastinate` puts the queue in Postgres with proper locking and retries.
Managed Redis free tiers also meter _per command_, so a polling queue burns quota while
idle. Redis returns as a pure addition when cache pressure is measured — not before.

### 5. Embeddings run locally

`fastembed` / BGE-small in-process: CPU-only, unlimited, free forever, and entirely
adequate for topic canonicalization. **100% of scarce LLM quota is reserved for card
generation**, the only task that genuinely needs a frontier model. If embeddings and
generation shared a quota pool, canonicalization would throttle exactly when signups spike.

### 6. A quota governor is a real component

Every LLM call passes through it. It tracks spend against a daily ceiling, enforces
a hard stop, and degrades gracefully rather than erroring. It is not a `try/except`.

Generation work is **prioritised**, not FIFO: refilling a starved popular topic
outranks a single user's niche custom topic. When quota is exhausted, low-priority
work waits for tomorrow rather than everyone starving equally.

### 7. Corpus-first launch

We cannot generate on demand at signup. The weeks before launch are spent running
generation at the daily free cap to build a seed corpus, so a new user's first session
hits a warm shelf.

## Consequences

**Easier**

- £0/month to run. Scaling up is a billing change, not a project.
- The quota governor and priority queue are things we would need at scale anyway —
  the constraint forces us to build them early, correctly.

**Harder**

- Cold starts. Free web services sleep after ~15 min idle. Mitigated by putting the
  web app on Cloudflare Pages (edge, never sleeps) and keeping the API warm with a
  cron ping. Render's ~750 free hours/month covers roughly one always-on service, so
  that budget goes to the API.
- Custom topics must be rationed (N per user, lower queue priority). ADR-0004's
  canonicalization is what makes this survivable rather than punitive.
- Generation latency is minutes-to-hours, not seconds. The UI must have an honest
  "preparing your topics" state.

**Committed to**

- Free tier limits are verified against current provider documentation before use.
  Provider pricing moves; assumptions in this ADR have a shelf life.
- Cloudflare Pages over Vercel for the web app: **Vercel's Hobby tier prohibits
  commercial use**, and we intend to monetize.

## Alternatives considered

**Self-hosted on an always-free VM (Oracle Cloud).** More capable — no sleeping, ample
RAM, free Redis. Lost because scaling up means a migration at the worst possible time,
and because it makes two developers responsible for backups, TLS, patching, and
monitoring instead of building the product.

**Paying a small amount from day one (~$20/mo).** Would remove cold starts and quota
pressure immediately. Rejected by the team as premature before traction — and note
that the quota governor and priority queue are worth building regardless.

## Revisit when

- **Traction arrives** — sustained daily active users, or generation quota is the
  measured reason users see a stale feed. Then execute the table in §2.
- Any provider changes free tier terms in a way that breaks an assumption above.
- Cold starts show up in user-reported latency complaints.
