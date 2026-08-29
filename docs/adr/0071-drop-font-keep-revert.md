# ADR-0071: Drop the font picker's Keep/Revert step — click and it's saved

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Anubhav
- **Amends:** [ADR-0037](0037-site-wide-font-picker.md) (retires its live-preview/Keep-Revert decision)

## Context

[ADR-0037](0037-site-wide-font-picker.md) gave `FontPicker` a live-preview step the
palette picker never had: selecting a face applies it immediately but does **not**
persist; a "Keep this font?" Keep/Revert prompt sits in the picker until resolved. The
reasoning was that "font legibility is harder to judge from a swatch than colour is", so a
reader should trial a face against real content before committing.

ADR-0037's own "Harder" section flagged the risk — *"worth watching for whether it reads
as an inconsistency against `ThemePicker`'s plain 'click and it's saved' behavior, since
the two pickers now behave differently by design"* — and its "Revisit when" names the
exit: *"If the Keep/Revert pattern proves confusing next to `ThemePicker`'s plain
apply-and-save behavior, consider bringing both pickers to the same interaction model."*

The F4/F5 rework ([finish-line plan](../handoff/v1-finish-line-plan.md),
[ADR-0070](0070-server-side-appearance-preferences.md)) restyles both pickers into the
*same* dropdown — identical 38px swatch grid, identical fixed-height scroll, identical
hover-reveal delete on saved entries. At that point two different commit models in two
visually identical controls is exactly the inconsistency ADR-0037 said to watch for, now
made unmissable by putting them side by side.

## Decision

**Selecting a font persists it immediately, the same as selecting a theme.** No pending
state, no "Keep this font?" prompt, no Revert. `FontPicker` gets the same handler shape
as `ThemePicker`: apply live, write through (to the server per ADR-0070, with the
`localStorage` cache updated in the same tick).

The trial-before-commit value ADR-0037 wanted does not disappear — it moves to where it
costs nothing: the picker is a live dropdown the reader can click through face by face,
seeing each applied to the page instantly, and clicking a different one is a single
action away. "Try it" is "click it"; "undo" is "click the previous one". The explicit
Keep/Revert only added a second required action to every change.

Reverting a selection the user regrets is a plain re-select, exactly as with the palette.
Nothing about a font choice is destructive or hard to reverse, which is the property that
made the confirmation step optional in the first place.

## Consequences

**Easier**

- One interaction model across both appearance pickers. A reader learns "click applies
  and saves" once.
- `FontPicker` loses its bespoke pending-selection state (`pendingFrom`, `keep`,
  `revert`, the confirmation row) — less component state, and it matches `ThemePicker`
  closely enough to share the dropdown chrome cleanly.

**Harder**

- A reader who clicks a face, dislikes it, and navigates away has persisted a choice they
  did not consciously confirm. Mitigated: the next face is one click away, the change is
  never destructive, and the default is always one click away too.
- This reverses an accepted ADR, so the trial-UX rationale in ADR-0037 is now only of
  historical interest — a reader of that ADR has to follow the pointer here.

**Committed to**

- `FontPicker` and `ThemePicker` share the click-to-save model. If one changes, both
  change — they are not allowed to diverge again without an ADR saying why.

## Alternatives considered

**Keep Keep/Revert, and give `ThemePicker` one too** (converge upward instead of
downward). Rejected: it adds a required second action to every palette change to fix a
consistency problem, when the palette has shipped without one since ADR-0012 and nobody
asked for it. The confirmation was speculative for fonts and would be doubly so for
colours.

**Keep the two pickers divergent.** Rejected — ADR-0037 already called this out as a
latent inconsistency, and the F4/F5 rework makes the two controls visually identical, so
"different by design" stops being legible to the user as anything but a bug.

## Revisit when

- Readers are provably losing font choices they didn't mean to make (support reports, not
  a hunch) — then a lightweight undo (a toast, like the collection views' 5-second undo,
  ADR-0052) is the answer, not a return to a blocking Keep/Revert.
