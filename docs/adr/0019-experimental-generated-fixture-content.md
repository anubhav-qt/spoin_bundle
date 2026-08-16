# ADR-0019: A second, honestly-tagged fixture for AI-generated content

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Anubhav

## Context

The real generation pipeline described in `overview.md` — Generation Planner, LLM
Workers, Quality Gate — does not exist yet. `generation/base.py` defines the
`ContentGenerator` interface; the only implementation is `fake.py`, a deterministic
placeholder. Two topics' worth of content ("System Design", "Claude Code") were
generated as a manual proof-of-concept: an Opus-model agent planned each topic's full
curriculum (subtopics across all three difficulty tiers, budgeted against ADR-0007's
~750-card ceiling, one hero per subtopic), and a Sonnet-model agent followed that plan
to write the cards, given the same context the planner had plus its plan.

This produced 216 real cards worth inspecting — proof of whether agent-generated
content actually reads the way the product wants. The question was whether to fold it
into `fixtures/corpus.json` so `make seed` picks it up for everyone.

`corpus.json`'s own header is explicit: "Every card here is hand-written, so the
fixture is stable, reviewable in a diff." That claim is not true of this content — it
is LLM-planned and LLM-written, not reviewed line-by-line by a human. `seed.py` also
unconditionally tags everything it loads with `gen_meta.backend = "fixture"`. Folding
this content in as-is would make that tag lie, which matters: `gen_meta.backend` is
the only record `content-model.md`'s quality gate section relies on to trace a bad
batch back to what produced it and compare quality across backends. Silently
relabeling unreviewed agent output as "fixture" (implying hand-written and reviewed)
corrupts that provenance the first time anyone reads it.

## Decision

A second fixture file, `fixtures/generated_corpus.json`, same shape as `corpus.json`,
with its own header stating plainly what it is and isn't. A second loader,
`seed_generated.py`, mirrors `seed.py`'s insertion logic exactly except for one line:
it tags every card `gen_meta.backend = "opus_sonnet_experiment"`, never `"fixture"`.

`docker compose`'s `seed` service runs both loaders in sequence
(`python -m slocho.seed && python -m slocho.seed_generated`), so `docker compose up` /
`make setup` still bring up a fully seeded stack in one command — the "convenient for
others" property is preserved — while keeping the two content provenances
distinguishable in the data itself, not just in a comment.

Both topics are marked `is_seeded: true` (same as fixture topics) and subscribed by
default, same as most `corpus.json` topics — treated as real, shared corpus content,
not a hidden or quarantined dataset. The only thing that differs is the truth recorded
in `gen_meta`.

## Consequences

**Easier**
- Anyone who clones the repo after this can inspect real agent-generated content
  immediately, without running the (expensive, non-deterministic) generation
  experiment themselves.
- `gen_meta.backend` stays a trustworthy field — a future real generation backend
  (Gemini, local) slots in the same way, distinguishable from both `fixture` and this
  experiment.

**Harder**
- Two fixture files and two loaders instead of one, which is a real increase in
  surface area for what was meant to be a minimal seeding story. Justified here
  because collapsing them would corrupt a field other parts of the system depend on
  being honest, not because more files are inherently better.
- This content bypassed the quality gate entirely (`generate.py`'s draft → quality
  gate → active pipeline does not exist yet) — it went straight to `status: active`
  the same way fixture cards do, on the strength of one Opus/Sonnet pass with no
  independent difficulty verification, dedup check, or factual-accuracy pass. It reads
  well on inspection, but "reads well" is not the same guarantee the real quality gate
  is supposed to provide once built.
- `is_hero`'s underlying weakness (ADR-0018's "not DB-enforced, only true by
  construction") now has a second, independent writer (`seed_generated.py`) alongside
  the fixture seeder, making that invariant marginally more likely to be violated by a
  future third writer that doesn't know both existing ones exist.

## Alternatives considered

**Fold it into `corpus.json` directly.** Rejected — see Context: it would make
`corpus.json`'s own "hand-written" claim false and `gen_meta.backend: "fixture"` a lie
for 216 cards.

**Keep it out of git entirely, DB-only.** Rejected — it directly contradicts the actual
ask (convenient seeding for a second developer) and throws away a proof-of-concept
worth keeping visible.

**Wait for the real generation pipeline and re-generate through it instead.** Correct
long-term answer, but that pipeline doesn't exist yet (see Context) — this ADR is
explicitly about what to do with output produced before it does.

## Revisit when

- The real `ContentGenerator` implementation (task: build `langchain_impl.py`) exists
  — at that point this experiment's cards should probably be regenerated through the
  real pipeline (quality gate included) rather than living as a permanently
  gate-bypassed exception, and `seed_generated.py` likely gets retired.
- `docs/tasks/0006`'s real hero-planning mechanism gets built — worth checking whether
  it needs to know about `seed_generated.py` as a second hero writer.
