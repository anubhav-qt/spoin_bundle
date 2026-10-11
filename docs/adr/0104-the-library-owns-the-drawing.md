# ADR-0104: The library owns the drawing; the model only picks and captions it

- **Status:** Accepted (supersedes 0080's adaptation step; answers 0098's measurement; amends 0021, 0066, 0079, 0099)
- **Date:** 2026-09-07
- **Reversed in the harness (2026-10-12, task 0045):** designer_toad draws every ASCII art
  itself, renders the card and improves the art from the screenshot; the library is no longer
  a source ([harness-tools.md](../architecture/harness-tools.md)). The admin ASCII review
  page goes with it; the owner reports bad art from the feed like any other card.
- **Deciders:** owner, Claude

## Context

[ADR-0098](0098-measure-the-ascii-box-rule-before-enforcing-it.md) declined to
invent an enforcement mechanism against zero observations and asked for one
specific number first: **a byte diff between a card's shipped art and the
curated-library entry it came from.** That measurement has now been taken,
against all 31 library-sourced ASCII cards in `spoin_db_2` on 2026-09-07.

**Two of thirty-one survived intact.**

| src_id | library | shipped | lines kept | backslashes |
|---|---|---|---|---|
| `bd35b685f237aa77` | 14 lines | **1** | 0/14 | 23 → **0** |
| `0b98e0c9c1ca6496` | 21 lines | **1** | 0/21 | 17 → **0** |
| `5bd2cd04f0816f9e` | 22 lines | 20 | 3/22 | 24 → **1** |
| `ac6d200e334edba2` | 4 lines | **89** | 0/4 | 6 → 65 |
| `db404ec8608ac2da` | 16 lines | **69** | 0/16 | 7 → 24 |
| `15a9c553faa91bbb` | 12 lines | 12 | **0/12** | 18 → 16 |

Eleven of thirty-one lost backslashes outright — and ASCII art is drawn out of
`\` and `/`. Even `art_52_13`, a **23-character one-liner**, came back
corrupted: `<('-'<) ^('-')^ (>'-')>` shipped as `<(-'<) ^(-')^ (>'-')>`.

Three things that measurement settles:

1. **The box rule was never the problem.** Zero of 45 active ASCII cards exceed
   40 columns; the widest is exactly 40. The width check ADR-0098 was debating
   how to enforce was already passing. The art was in budget *and still
   unreadable*.

2. **This is not a model-quality problem, and a better model does not fix it.**
   The `\\` → `\` collapse is structural: the library's art contains literal
   double backslashes, and a model emitting them inside a JSON string field
   either escapes them or does not, with no way for the decoder to tell. The
   same class of bug corrupts LaTeX elsewhere in the corpus — `\frac` arrives as
   a formfeed plus `rac` in 36 cards (6.0%), because `\f` is a *valid* JSON
   escape and nothing raises. Whitespace- and backslash-exact content does not
   survive a JSON string field, whoever is writing it.

3. **The captions describe scenes that are not there.** A card whose art had its
   toaster deleted shipped the caption *"Monkey swapping toaster parts out of
   order"*. The model wrote the caption for what it intended to draw, not for
   what arrived.

Separately, 14 of 45 ASCII cards were **free-drawn** — no library match, model
draws its own. Those are the worst content in the corpus: a "wizard" that is
five rows of unaligned brackets under a caption describing a scene no reader can
see.

## Decision

**The model never emits ASCII art. It picks a library entry and writes text; the
server copies the drawing.**

- `AsciiFetchResult` **loses its `art` field** — a field the model cannot fill
  correctly is a field it must not be offered. It returns `src_id`, `label`,
  `alt` and a new `overlay_lines`.
- `overlay_lines` is the model's entire contribution to the picture: two to four
  short lines composed **below** the drawing, carrying the labels and the gag.
  They are the only thing measured against the column budget, and an over-long
  one is **wrapped, never truncated** — it carries the joke, and a scene that
  loses it is a picture with no point.
- `compose_scene(art, overlay_lines)` in `spoin.content.ascii_library` copies the
  library art byte for byte and appends the wrapped overlay.
- **The free-draw path is deleted.** An ascii brief with no library match is
  rewritten as a **prose** brief before the writer sees it. With 853 curated
  entries and top-10 retrieval, a genuine no-match means the concept has no
  scene worth drawing — a reason to write prose, not to draw badly.
- Register the matching deterministic repair for the same class of bug
  elsewhere: `spoin.content.normalize` restores JSON-eaten backslashes, rewrites
  fences the renderer cannot parse, and quotes mermaid labels that break its
  parser. It runs in `CardDraft`'s validator, so every producer of a draft —
  drafting, repair (ADR-0076), correction — passes through it.

This ADR also separates **difficulty from register**: see the sibling change in
`canon.py` and `sources.py`, where `TIER_LANGUAGE` used to instruct "rigorous,
sophisticated, compact domain language" that is "densely packed" at advanced.
The corpus obeyed — Flesch-Kincaid climbed 11.4 → 13.3 → 15.4 across Rust's
tiers while second-person address collapsed 37.8 → 12.5 → 4.4 per 1,000 words.
Difficulty is now what a card **covers**; the reading level is the same at every
tier.

Operator review of the composed scenes gets a page:
`/admin/[topic]/ascii-art`, a card stack with two exits — keep (writes the art,
including the operator's edit) or send to `/admin/repairs` as an `art` report,
which is a reason type ADR-0076 already handles.

## Consequences

**Easier.** Art fidelity becomes 100% by construction rather than 6% by luck:
copying bytes cannot skew a column, so the 40-column rule is now unfalsifiable
for the drawing and checkable for the overlay. The drafting model no longer
needs to be good at transcription, which is the one thing it was worst at —
`ministral-8b` is now sufficient for this call, and ADR-0066's redraw pass
(already unused) has nothing left to rescue. A scene can only be wrong because a
human made it wrong.

**Harder.** Labels can no longer sit *inside* the picture beside the thing they
name — they move below it, as composed lines. This is a real loss of expressive
range, accepted because 29 of 31 cards currently have no legible figure at all,
so the in-figure label was theoretical. ADR-0099's "a scene must say something"
survives in a weaker form: the text is present and readable, but adjacent rather
than embedded.

**Committed to.** The library is now load-bearing: a scene's quality is entirely
the curation's quality, and the only lever left is curating more and better
entries (task 0030). A topic whose concepts match nothing in 853 gags gets prose
cards, which is the correct outcome but a quieter one than shipping bad art.

## Alternatives considered

**A bigger or different model for the ASCII call.** The owner's first instinct,
and the measurement rules it out: the failure is transport, not capability. The
two cards that survived are the two simplest, and the corrupted one-liner shows
the ceiling is not intelligence. A stronger model would fail less often at
something it should not be asked to do at all.

**Add art by hand, later.** Viable and now *supported* — that is what
`/admin/[topic]/ascii-art` is — but it cannot be the primary mechanism at
corpus scale. It is the review layer on top of a pipeline that is already
correct, not a substitute for one.

**Drop ASCII art entirely.** On the table, and the measurement is bad enough to
justify it. Rejected because the failure is fully explained and cheaply fixed:
853 hand-verified drawings already exist and render perfectly; the only thing
between them and the reader was a model retyping them.

**A stricter gate on the returned art** (byte-compare against the library and
reject a mismatch). Rejects 29 of 31 cards and regenerates each one into the
same failure — ADR-0066's loop with a bill attached. A check that every attempt
fails is not a check, it is a signal the step should not exist.

**Keep the free-draw fallback but gate it harder.** No gate can detect "does
this look like anything", which is ADR-0021's original reason for choosing a
library. Nothing about that has changed.

## Revisit when

A model can round-trip a 15-line drawing through a JSON string field with byte
fidelity — measurable directly, with the same diff this ADR is built on, by
re-enabling the `art` field behind a flag for one run and comparing. Until that
number is at or near 31/31, this decision holds regardless of how good the
model's prose has become.

Also revisit if operator review shows the **overlay lines** are the weak half —
if scenes are being rejected for their captions rather than their drawings, the
composition step is where to spend effort next, not the retrieval.
