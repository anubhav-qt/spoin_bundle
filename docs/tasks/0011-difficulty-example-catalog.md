# Task 0011: Author the difficulty example catalog

**Owner:** unassigned

## The problem

[ADR-0030](../adr/0030-two-pass-quality-gate.md) has both the card writer (`generate_cards`)
and the quality-gate judge (`correct_cards`/`verify_cards`) accept a
`difficulty_examples: dict[Difficulty, list[str]]` argument — a few example card bodies per
tier, shown together so beginner/intermediate/advanced have a concrete, contrastive anchor
instead of just a label. `content/difficulty_examples.py`'s `get_difficulty_examples()` is
wired into every call site that needs it, but returns an empty list per difficulty. No actual
examples exist yet.

This only matters for **standalone** subtopic-tiers (no sibling tiers in the same
`subtopic_group_id`) — a **linked** subtopic already gets real, concept-specific calibration
for free from `builds_on` (its own actual lower-tier cards), so this catalog is skipped there
by design. Standalone tiers are the common case, since curricula are never forced to give a
concept all three difficulty tiers.

## Why it matters

Without this, "beginner" and "advanced" are just words in the prompt. Both the writer and the
judge are calibrating against nothing concrete for any subtopic without tier siblings — which,
per the note above, is most of them. Difficulty conformance (ADR-0030's pass 2) is only as
good as what the model is comparing against.

## What to do

Hand-author a small set of example card bodies per difficulty (beginner/intermediate/advanced)
— topic-agnostic, illustrating depth and framing rather than any specific subject, the same
"curated, not generated" principle ADR-0021 uses for the ASCII scene catalog. Wire them into
`get_difficulty_examples()`.

Needs:

- A handful of examples per tier (3-5 is probably enough — this is a calibration anchor, not
  training data).
- Genuinely topic-agnostic phrasing, or a small spread across a few unrelated subjects, so the
  model doesn't anchor on a specific domain's vocabulary as "what beginner sounds like."
- A clear, consistent notion of what separates the tiers (breadth vs. depth, vocabulary,
  assumed background) — write this down alongside the examples, not just the examples
  themselves, so a future edit has a rationale to check against.

## Hand back

`content/difficulty_examples.py`'s `get_difficulty_examples()` returning real examples per
`Difficulty`, plus a short note (in the module docstring or an ADR) on what distinguishes the
tiers in the examples chosen.

## Timebox

Not started. Rough guess: an hour or two — this is authoring, not engineering; the plumbing
already exists (ADR-0030).
