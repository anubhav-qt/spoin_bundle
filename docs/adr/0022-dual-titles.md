# ADR-0022: Every card carries a display title and a canonical title

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Anubhav, Mayank

## Context

A playful title is one of the cheapest ways to stop a scroll — "Big Boy Sits Down" pulls
attention in a way "Weight Classes in Combat Sports" does not. But `title` is not only
read by humans. It is currently load-bearing in three machine paths:

- **Generation prevention.** [ADR-0007](0007-curriculum-driven-generation.md) supplies the
  list of titles already covered in a subtopic to the generation prompt, specifically so
  the model doesn't re-cover ground. This is the *cost* half of the prevention/detection
  split — it is what keeps us from paying to generate duplicates that the gate then throws
  away.
- **Remediation.** [ADR-0009](0009-quiz-gated-progression.md) links every wrong answer back
  to the card that teaches it. That link is shown to a user who just got something wrong.
- **Progress and discovery.** The per-topic progress surfaces of
  [ADR-0015](0015-topic-progress-and-discovery.md) list what a user has and hasn't covered.

Make `title` playful and all three degrade at once, quietly. The generator can no longer
tell what's been covered from a list of puns, so the prevention layer stops preventing.
"Go read *Big Boy Sits Down*" is a bad answer to "what did I get wrong?". And forty jokes
in a coverage list is unscannable — the reader cannot find the one subtopic they care
about.

The failure mode that matters most is the first one, because it is **silent**: nothing
errors, generation just gets more expensive and more duplicative, and the gate absorbs it.

## Decision

A card carries two titles.

```
card
  title             str   display. Playful some of the time; what the feed shows.
  canonical_title   str   literal and descriptive. Always present.
```

Both are produced in the same structured-output call — one extra field, no extra request
([ADR-0005](0005-batch-llm-calls.md)), the same reasoning that justifies `summary` being a
purpose-written hook rather than a truncation.

### Which title each consumer reads

| Consumer | Title |
|---|---|
| Feed card face, hero cards, share images | `title` |
| Generation prompt's "already covered" list | **both** (see below) |
| Quiz stems, remediation links, wrong-answer results | `canonical_title` |
| Progress lists, coverage surfaces, search | `canonical_title` |
| Chat / "Ask AI" card context | **both** |

**Both titles go into the generation prompt's already-covered list.** The canonical title
is what lets the model tell that a subject is taken; the display title is what stops it
inventing the same joke twice. Passing only canonical would leave the puns free to
collide, which is a duplicate a reader notices even when the underlying content differs.

`canonical_title` is the **default** for anything not listed here. When adding a surface,
the question is not "which title fits?" but "is there a specific reason a human wants the
playful one here?" — and the answer is only ever yes on the feed face.

### Playfulness is a config knob, not a code path

Not every card gets a joke title; a wall of puns is as monotonous as a wall of prose. The
target proportion lives in **config, not code**, for the same reason the difficulty-mix
percentages do (content-model.md, "Feed mix by user level"): it will be tuned against
engagement data and tuning must not require a deploy. Where a card gets no playful title,
`title` is simply the canonical one — never null, so no renderer needs a fallback.

### What does not change

`content_embedding` stays derived from `body`. Neither title feeds dedup, so the
near-duplicate gate is entirely unaffected by this ADR — worth stating explicitly so that
nobody later "improves" dedup by folding the display title into the embedding and
quietly makes puns look like distinct content.

## Consequences

**Easier**
- The feed gets the hook without any machine path losing the literal name of the concept.
- Adding a surface is unambiguous: canonical unless there's a reason.
- The prevention layer gets *stronger* than today — it can now catch repeated jokes as
  well as repeated subjects.

**Harder**
- Two fields to keep coherent. A display title that doesn't actually correspond to its
  canonical title is a new failure mode, and it is one the quality gate does not check for
  today. It should be added to the batch judge's pass rather than assumed away.
- Every already-covered list sent to the generator roughly doubles in size, spending
  prompt budget on the same subtopic count.
- A user who searches for what they read on the card face searches the playful title,
  which is the one surface we deliberately don't index. Search should match against both
  and display canonical.
- Two titles to translate if the product is ever localized, one of which is a pun.

## Alternatives considered

**One `title` field, playful, with machines parsing intent from it.** Rejected — this is
the do-nothing option and it is the one that silently degrades ADR-0007's cost control.
Nothing errors; generation just quietly gets worse.

**One `title` field, literal, with playfulness pushed into `summary`.** Genuinely
tempting, and the cheapest option — no schema change at all. Rejected because the title is
the largest type on the card and the first thing read; putting the hook one line below the
biggest words on screen wastes the position that actually stops a scroll.

**Derive the canonical title from the playful one after the fact.** Rejected: it is an
inference where a direct statement is free. The model already knows what the card is
about at generation time — asking it later to reverse-engineer that from a pun is strictly
worse and costs a request.

**Store playfulness as a boolean flag alongside a single title.** Rejected — it records
*that* a title is a joke without recovering what the joke is about, so every machine path
is still stuck.

## Revisit when

- Engagement data shows playful titles are not outperforming literal ones on the feed
  face. Then the whole apparatus is unnecessary and `title` collapses back to one field.
- The batch judge starts flagging display/canonical mismatches often enough to suggest the
  model can't reliably do both in one call.
