# Task 0013: Collapsed-state preview swaps instantly while the body around it animates

**Owner:** unassigned

## The problem

Expand/collapse itself is smooth now (`.card-reveal`'s `grid-template-rows` 0fr/1fr
transition, `Card.tsx`) -- fixed alongside the note-panel animation this session. But
the collapsed-state preview content sitting just above it is not part of that fix:

```tsx
{archetype === "default" ? (
  <p className="card-summary">{card.summary}</p>
) : !expanded ? (
  <ArchetypeTeaser archetype={archetype} body={card.body} />
) : null}
```

`card-summary`/`ArchetypeTeaser` mounts and unmounts via a plain conditional -- no
transition of any kind. On expand, it vanishes on the same frame `.card-reveal` starts
its 0.22s grow; on collapse, it pops back in the instant `.card-reveal` finishes
shrinking. The body animates, the teaser snaps -- visibly two different motions
happening in the same card at the same time.

## Why it matters

This is exactly the kind of "discrete motion" artifact the note-panel and
card-reveal fixes were about, on the piece of the card sitting right above them --
noticeable during the same interaction, once the body's smoother now.

## What to do

Give the teaser the same treatment `.card-reveal`/`.card-note` got: keep it mounted
and drive visibility off a `data-open`-style attribute with a real CSS transition
(the `grid-template-rows` 0fr/1fr trick used elsewhere in this file), instead of the
conditional JSX mount. Verify against the same failure mode that motivated the other
two fixes: Framer Motion's `layout` on `.node` needs something gradual to track, not
a single-frame flip, or the old "vanish and reappear from a different position" jump
comes back.

## Timebox

Small -- should be a same-shaped diff to the `.card-reveal` fix (`Card.tsx` +
`globals.css`), on the order of 30-60 minutes including a manual check of both
expand and collapse.
