# `corpus/` — the curated source of truth

Authored by Antigravity under the owner's supervision, following
[`../procedure.md`](../procedure.md). Ingested into `the_spoin_universe` (ADR-0088)
and retrieved at generation time to ground both the card writer and the verifier
(ADR-0089).

Laid out by the hierarchy:

```
<category>/<sub_category>/<survey-or-topic>/<document>.md
```

The `sub_category` level is omitted entirely when a subject has none. The directory
is organisational convenience for humans — **the front matter is authoritative**, and
the ingester reads the fields, not the path. Keep them consistent anyway; a mismatch
is a review signal that something is misfiled.

## Active Corpus Content

### Spoin Canon (`_canon/`)
Product mechanics and authoring invariants (kind: `spoin_canon`):
- `ascii-box-rule-and-gag-scenes.md`: ASCII box invariant (width ≤ 40), gags only, and discard-for-regeneration failure policy.
- `card-anatomy-and-fields.md`: Card schema, field provenance, and system invariants.
- `card-archetypes-and-content-shapes.md`: Archetypes derived post-generation; Mermaid client rendering.
- `curriculum-progression-and-quizzes.md`: Topic budgeting, latched 80% progression, quiz generation from cards.
- `dual-titles-and-hook-discipline.md`: Display title vs. canonical title; silliness in hook layer, truth in body.

### Subject Matter (`computer-science/software-engineering/backend-engineering/`)
Initial survey suite (kind: `topic_source`, scope: `survey`):
- `api-paradigms-and-contracts.md`
- `asynchronous-messaging-and-event-streams.md`
- `caching-and-state-management.md`
- `data-persistence-and-transactions.md`
- `fault-tolerance-and-observability.md`
- `security-authentication-and-boundary-defense.md`
- `server-concurrency-and-io-runtimes.md`
- `tips-and-tricks.md` (field lessons, operational traps, production rules of thumb)
- `transport-and-application-protocols.md`
