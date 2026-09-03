# Generation Queue

> **Live DB:** `spoin_db_2`
> **Regime:** ADR-0082 key boxes (box 34, 2 topics concurrent) + ADR-0074 per-group
> claim. Redraft brake (`_LATER_PASS_MIN_ROUND_PROGRESS`, nodes.py): a resume pass
> hands a subtopic-tier off after 5 rounds that each close <10% of its remaining
> gap — the rest is deferred to a future backfill, not spun on. Gate calls
> (`correct_cards`/`verify_cards`) run pool-wide, not pinned to the card key.
>
> Reconciled against the DB 2026-09-03. Card/question counts are live rows, not
> targets — a topic with a curriculum but well under ~450–700 cards still has
> real work; targets vary by curriculum.

---

## Done — cards + questions complete

| Topic | subs | cards | questions |
|---|---|---|---|
| Rust (Programming Language) | 40 | 716 | 299 |
| Game Development | 46 | 690 | 322 |
| Bhagvad Geeta in Easy Language | 43 | 687 | 301 |
| Backend Engineering | 45 | 659 | 290 |

Bhagvad Geeta is 687/688 — the last card has failed the gate 5 rounds running and
is handed off; a later backfill pass retries it.

---

## Incomplete resumes — have a curriculum, well under target, 0 questions

Run these with `generate_topics`; they resume from their current card count and
the topic-wide question phase runs at the fan-in.

| Topic | subs | cards | note |
|---|---|---|---|
| **10M Air Pistol Shooting** | 34 | 227 | **generating now** (2026-09-03, box 1, paired with Generative AI) |
| **Physical Fitness** | 40 | 242 | next |
| **Carl Jung's Philosophy** | 42 | 162 | next |

```
docker compose exec -T api python -m spoin.generate_topics "Physical Fitness" "Carl Jung's Philosophy"
```

---

## Brand new — topic row exists, no curriculum, 0 cards

`generate_topics` mints the curriculum then does a full first pass (stops each
subtopic at `first_pass_completion_fraction` = 90%, then the topic is done for
the session and its box takes the next queued topic).

**Generating now:** Generative AI (2026-09-03, box 2)

**Queued (auto-created 2026-09-01 as related/sub-topics of the big requests,
never generated):**

- Game Engine Architecture
- Game Physics Engines
- Multiplayer Network Programming
- Shader Programming & Computer Graphics
- Advaita Vedanta
- Yoga Sutras of Patanjali
- Indian Philosophy & Epistemology
- The Mahabharata Epic Narrative
- Mythology and Comparative Religion
- Joseph Campbell and the Hero's Journey
- Alchemical Symbolism
- Existential Psychology
- Freudian Psychoanalysis
- Personality Typology and Psychometrics

---

## Explicit new-topic requests (from the prior queue, no topic row yet)

`generate_topics` will mint these from scratch. Keep the `::description`.

- `Philosophy::a road introduction of philosophy and various prominent thinkers and their philosophies.`
- `Financial Literacy & Investing Mechanics:: everything needed to know about financial independence and how can we invest in various places.`

---

## Superseded

The earlier version of this file listed "Generative AI / Philosophy / Financial
Literacy" as bare next-ups and carried stale "0 questions / 643 cards" states for
Bhagvad Geeta and Game Development. `docs/notes/topic-queue.md` is older still and
tracks the archived `spoin_db` — ignore it for `spoin_db_2` work.
