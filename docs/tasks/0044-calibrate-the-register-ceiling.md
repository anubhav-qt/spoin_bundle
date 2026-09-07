# Task 0044 — Calibrate the register ceiling from a real run

- **Status:** Open
- **Blocks:** nothing; the prompt half of ADR-0104 ships without it
- **Related:** [ADR-0104](../adr/0104-the-library-owns-the-drawing.md), task
  [0042](0042-recalibrate-thresholds-against-real-vectors.md)

## Why this is a task and not a number in `config.py`

`Settings.register_max_grade` ships at `0.0`, which **disables** the check. That
is deliberate, and it is the one loose end in ADR-0104.

The register problem is real and measured. On 2026-09-07:

```
topic         tier            n   FK grade  sent len  syl/word  "you"/1k
Astronomy     beginner      162      12.8      18.7      1.81       0.5
Astronomy     intermediate  178      13.5      19.3      1.86       0.5
Astronomy     advanced      179      14.5      20.1      1.93       0.4
Rust          beginner       28      11.4      19.3      1.66      37.8
Rust          intermediate   27      13.3      18.7      1.86      12.5
Rust          advanced       31      15.4      20.8      1.98       4.4
```

Two defects. Astronomy reads at college level at **every** tier and never
addresses its reader — it inherited the academic register of the corpus it was
grounded in. And both topics climb steeply with tier, because `TIER_LANGUAGE`
told them to ("rigorous, sophisticated, compact domain language", "densely
packed"). ADR-0104 rewrote that prompt.

What it did **not** do is switch on a hard gate, because every threshold
available today is a guess against the wrong data:

| ceiling | rejects, of the CURRENT corpus |
|---|---|
| grade 10 | 97% |
| grade 11 | 91% |
| grade 12 | 80% |
| grade 13 | 67% |

Shipping any of those turns generation into ADR-0066's
reject-and-regenerate-forever loop with a real API bill attached. And the corpus
those percentages come from was written under the **old** prompt, so it predicts
nothing about the new one.

## The work

1. Generate a small batch under the ADR-0104 prompt — one subtopic per tier on
   both Astronomy and Rust is enough. Do **not** set `register_max_grade` yet.
2. Measure it with `spoin.content.readability` (`flesch_kincaid_grade`,
   `second_person_per_1k`) and reproduce the table above for the new cards.
3. Set the ceiling from where that distribution actually lands — comfortably
   above the new mean, so it catches the tail rather than the body.
4. **Consider not using grade at all.** Flesch-Kincaid folds two things
   together: sentence length, which is a pure register choice, and syllables per
   word, which is partly the subject's own vocabulary. The measurement above
   shows sentence length barely moved by tier (18.7 → 20.1) while syllables per
   word did the climbing (1.66 → 1.98 within Rust, same subject). So the tier
   escalation was a **vocabulary** choice, and an absolute grade threshold
   penalises astronomy for being about astronomy. Two better shapes to weigh:
   - a **per-topic** ceiling, calibrated per corpus;
   - gating on `second_person_per_1k` instead, which is subject-independent and
     was the starkest signal in the table (37.8 → 4.4 within one topic).

## Done when

`register_max_grade` (or whatever replaces it) is set from measured data, the
reasoning is in its config comment, and a follow-up run shows the rejection rate
is a small tail rather than the body of the distribution.

## The trap this task exists to avoid

`image_similarity_floor` was also set to `0.0` "for the initial calibration
run". The run happened. Nobody turned it back on. Every image card in the corpus
then accepted its top-1 match no matter how bad, which is half of why
[ADR-0105](../adr/0105-the-photograph-is-chosen-before-the-card.md) was needed.
A disabled threshold with a good reason is fine; a disabled threshold nobody is
tracking is a silent defect.
