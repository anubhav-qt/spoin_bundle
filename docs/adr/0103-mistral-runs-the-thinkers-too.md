# ADR-0103: Mistral runs the thinking ladder too, and the in-flight semaphore is gone

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** project owner, implementing session
- **Amends:** [ADR-0090](0090-hybrid-gemini-mistral-generation.md) — reverses its
  routing table, which kept every thinking-ladder call on Gemini, and removes
  `mistral_max_in_flight`
- **Builds on:** [mistral-saga](../mistral-saga/README.md), [gemini-saga](../gemini-saga/README.md)

## Context

ADR-0090 split the ladders: prose to Mistral, verdicts to Gemini. It did so on a
specific, measured fact — **this account has no reasoning-capable Mistral model.**
Everything Small/Medium/Magistral returned 429 with
`x-ratelimit-limit-req-minute: 0`, a permanent zero allocation; `mistral-large` and
`labs-leanstral` were 403 tier-gated. Only `ministral-3b/8b/14b` and `codestral` could
be called at all. So the thinkers stayed on Gemini not because Gemini was better for
them, but because there was nowhere else for them to go.

That split inherited Gemini's whole apparatus for half the run: box leasing, the load
balancer, the rung ladder, the 429 classification, the reserve rungs
([ADR-0084](0084-per-box-in-memory-load-balancer.md),
[ADR-0074](0074-thinking-ladder-reserve-rungs.md)). It also inherited its ceiling — the
thinking pool's rungs are `rpd 20 / rpm 5`, which is where gate rate-limiting actually
bites.

Two things then changed.

**`ministral-14b-2512` is good enough to judge.** It is on the ladder this account can
call, and run experience found its verdicts acceptable for the two gate passes
(`correct_cards`, `verify_cards`) and the other thinking-ladder calls. ADR-0090's
premise was *no reasoning-capable model exists here*; the weaker claim that survives is
*no frontier reasoning model exists here*, and the gate does not need a frontier model.

**A real run produced no 429s at all with the semaphore removed** (owner, 2026-09-06).
`mistral_max_in_flight = 5` was ADR-0090's one unmeasured constant — the sweep's proven
ceiling, explicitly flagged as the number task 10 existed to check against real grounded
prompts rather than synthetic filler. Checked; it does not bind.

## Decision

**Route the thinking ladder to Mistral as well, on `ministral-14b-2512`, and remove the
client-side in-flight cap.**

`SPOIN_MISTRAL_AS_THINKER` gates it and defaults to **on**. `HybridContentGenerator`
holds one `MistralClient` per model — the generator's `ministral-8b-2512` and the
thinker's `ministral-14b-2512` — and falls through to `super()._invoke_with_retry`
otherwise.

### What still goes to Gemini

Exactly one thing: **a prompt carrying a non-text part.** `repair_card_structure` sends
a rendered PNG of a card, and image input is not on this Mistral tier. The `_has_image`
shape check runs before the ladder check for that reason, so a future multimodal call is
routed correctly without anyone remembering to update a list.

Everything else — both gate passes, topic matching, quiz grading, difficulty judging —
is Mistral now. Gemini's apparatus stays in the codebase and stays correct; it simply
schedules almost nothing.

### The semaphore is removed, not raised

Raising the cap would have kept a knob nobody can set from evidence. The measured fact
is the absence of a wall, and the honest encoding of "no wall was found" is no cap,
paired with the telemetry that would show one appearing.

`in_flight_at_send` is still recorded on every call in the per-run JSONL. That is the
whole safeguard: it is the number that shows the decision continuing to hold as batch
sizes grow, and the number that would show it failing.

**What still bounds concurrency is the connection pool**, `httpx.Limits(max_connections=128)`
per client. There is one client per model, so a hybrid run with a Mistral thinker has
**two**, and the real ceiling is their sum — 256, not 128. That is a consequence worth
stating plainly rather than a number anyone chose: nothing has been measured at that
load, and the sweep that justified removing the cap ran against one client.

## Consequences

**Easier.** The gate stops competing for the thinking pool's `rpd 20 / rpm 5`, which was
the scarcest resource in a run and the usual reason a tier stalled. One provider means
one failure mode to read in the logs, and a Mistral outage stays visible as a Mistral
outage — ADR-0090's no-cross-provider-fallback rule is unchanged and now covers the
whole run.

**Harder.** The blast radius of a Mistral outage is now the entire pipeline rather than
half of it. Gemini's machinery is exercised by almost nothing, so it will rot quietly —
the day this account gets a frontier Mistral model, or loses this one, whoever re-reads
`load_balancer.py` will be reading code that has not run in months.

**Given up.** The provider diversity ADR-0090 bought on purpose. It was worth having
while the thinkers had nowhere else to go; it is not worth keeping a second scheduling
apparatus warm for.

## Alternatives considered

**Keep verdicts on Gemini, remove only the semaphore.** The smaller change, and rejected
because it leaves the gate on the `rpd 20 / rpm 5` rungs that were the actual bottleneck.
The semaphore was never what limited a run.

**Raise `mistral_max_in_flight` to a bigger number.** Rejected as a constant nobody could
defend: the same objection ADR-0101 raised against inventing a grounding floor, and the
same answer — record the measurement, do not encode a guess.

**Use `ministral-8b` for the thinkers too, and keep one client.** Would halve the
connection-pool question and remove a model from the config. Rejected because the gate is
the one place where a weak judge is silently expensive — it re-rates difficulty and
verifies factual claims, and a bad verdict there ships as a good card
([ADR-0030](0030-two-pass-quality-gate.md)).

## Revisit when

- **429s appear in the JSONL.** `in_flight_at_send` at the time is the first thing to
  read; a cap comes back from that distribution, not from taste.
- **Batch sizes grow enough to approach 256 in flight.** The two-client ceiling has never
  been measured and should not be discovered in a production run.
- **A frontier reasoning model becomes callable on this account.** The gate is where it
  would earn its cost first, and ADR-0090's original split becomes worth re-reading.
- **The gate's accept rate moves.** `ministral-14b` judging instead of `gemini-3.8-flash`
  is a quality change, and the first run's accept/reject split against the corpus's
  history is what prices it.
