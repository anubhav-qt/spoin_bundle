# ascii-art review — design source

The source of truth for `/admin/[topic]/ascii-art`
([ADR-0104](../../../adr/0104-the-library-owns-the-drawing.md)). The page that
implements it is `apps/web/app/admin/[topic]/ascii-art/page.tsx`; when the two
disagree, this directory is what the next session should read first.

| File | What it is |
|---|---|
| `Main.dc.html` | The design. Plain readable HTML — palette tokens, layout, the card stack, both in-place editors, and the interaction logic. |
| `canvas.json` | Canvas layout and the annotations explaining the decisions. |

## Why there is no rendered file here

Seeding produces a ~2.5 MB `ascii-art-review.html` that is almost entirely the
canvas editor's own bundle, and it is gitignored. `Main.dc.html` carries the
whole design and reads fine on its own; the rendered file is a build artifact,
regenerated with the `design` skill's helper:

```
node <skill>/seed-canvas.mjs --template <skill>/payload.template.html \
  --out ascii-art-review.html --title "ASCII Art Review" \
  --artboard Main.dc.html --canvas canvas.json
```

## The decisions worth knowing

- **A stack, not a table.** ADR-0104 made the drawing structurally correct by
  construction, so exactly one question is left per scene — does this picture
  carry this card's idea. That is a judgement on a rendered image, made fastest
  one at a time with two exits.
- **No edit mode.** The scene and the caption are always editable and styled to
  be indistinguishable from how they render, so nothing swaps out from under the
  reviewer and the picture never disappears in order to be edited (owner,
  2026-09-07). An earlier draft had an edit/read toggle; it was wrong.
- **The 40-column readout flags, it never cuts.** The budget is enforced against
  the model, which cannot judge its own output. An operator looking at the
  rendered scene can, and a page that silently reflowed what they typed would be
  arguing with the person it exists to serve.
- **Left swipe files an `art` report** into the existing `/admin/repairs` queue
  (ADR-0076) rather than growing a second repair path, so a card keeps one
  repair history instead of two.
