# Task 0026: Add worked good/bad examples to the card prompts, from manual review of v2 cards

**Owner:** unassigned
**Blocked on:** enough v2 cards existing to review, and a hand review of them on the frontend.

## The problem

[ADR-0059](../adr/0059-card-planning-pass-and-prompt-versioning.md) split card
generation into a focused planning prompt and focused per-type writer prompts, on
the theory that **a more single-goal-focused task produces a better result from the
model**. That split is the enabling half of the theory. This task is the other half.

Every one of those prompts currently *describes* what good output looks like in
prose. None of them *shows* it. "A card that dramatizes the concept rather than
decorating it", "an angle that separates this card from its siblings", "a hook,
not a truncation of body" — these are the right instructions and they are still
abstractions. A model given one worked example of each, and one worked
counter-example, has something concrete to match against.

The reason this is a separate task rather than part of ADR-0059: we do not yet
know *which* failures are the common ones. Writing examples now would mean
inventing plausible-sounding bad cards instead of using the ones the pipeline
actually produces, and the whole value of an example is that it is real.

## Why it matters

This is the step that tests the theory ADR-0059 is built on. If focused prompts
with concrete examples don't produce measurably better cards than the generic
prompt did, the extra planning call is not paying for itself and ADR-0059's
"revisit when" applies.

It is also the only mechanism we have for feeding back what hand review finds.
Manual review that ends in a shared opinion changes nothing; manual review that
ends in an example pasted into the prompt that produced the problem changes the
next run.

## What to do

1. **Review v2 cards by hand on the frontend.** They are identifiable:
   `gen_meta->>'prompt_version' = '2'` for v2, `IS NULL` for v1 (nothing was
   backfilled — see ADR-0059). Review the rejected ones too (`rejected_card`,
   stamped the same way), since a rejection with a reason is a labeled example
   already.
2. **Sort what you find by which prompt is responsible.** A card that covers the
   wrong idea or picks a form the material doesn't support is a `PLAN_SYSTEM`
   problem. A card whose concept was right but whose prose, hook, code block or
   ASCII scene is weak is a writer-prompt problem, and specifically one of
   `CARDS_{ASCII,CODE,DIAGRAM,COMPARISON,PROSE}_SYSTEM`. Getting this attribution
   right is most of the work — an example pasted into the wrong prompt teaches the
   wrong call.
3. **Write a small number of real good/bad pairs per prompt**, taken from actual
   output, lightly edited for length. A handful each; this is calibration, not
   training data — same principle as
   [task 0011](0011-difficulty-example-catalog.md)'s difficulty catalog, which is
   the sibling of this task and worth doing in the same sitting.
4. **Bump `CARD_PROMPT_VERSION`** (`generation/pipeline/state.py`) to 3 when the
   examples land, so v2 (focused prompts, no examples) and v3 (focused prompts,
   with examples) stay separable. That separation is the experiment.

## Watch out for

- **Examples are prompt content, and prompt content is taste, not constraint**
  (CLAUDE.md). Do not add a "keep this under N characters" line alongside them —
  anything that must be *true* gets a check in code, not a sentence in a prompt.
- **Don't anchor the model on one domain.** Spread the examples across unrelated
  subjects, or the model learns what "good" sounds like *in that subject*.
- **A bad example is a real risk.** Showing the model a counter-example can teach
  it the counter-example. Label them unambiguously, and prefer a bad example that
  differs from its good pair in exactly one dimension.

## Hand back

Worked examples wired into the planning and writer prompts, `CARD_PROMPT_VERSION`
bumped, and a short written note (in ADR-0059's follow-up or a new ADR) on what
the hand review actually found — the review's conclusions are the durable part,
the examples are just their encoding.
