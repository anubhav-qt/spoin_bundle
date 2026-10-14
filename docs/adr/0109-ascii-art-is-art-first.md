# ADR-0109: ASCII art is art first, its text labels, checked in code

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** project owner
- **Amends:** [ADR-0099](0099-ascii-scenes-carry-their-own-explanation.md) (how much text a scene
  carries)

## Context

The first harness run (Rust in easy language, task 0045) gave designer_toad 128 ascii cards. The
owner read them and found walls of text with a little art: tiny `(o_O)` figures beside long labels,
a line of dialogue, and a summary sentence under a `=====` rule that repeated the caption. Measured
over the 128: gags had a median of 21 words (p10 15, p90 26) and letters were half of every
character that wasn't a space; informative drawings 23 words, 47% letters. Art by ASCII artists at
asciiart.eu is 3% letters and 19% box characters at the median.

ADR-0099 asked for text on every scene because wordless art couldn't be read. The prompt then
asked for labels, dialogue and a caption, and the model wrote all three at length.

designer_toad's prompts had also reached 412k tokens: each render returns up to 10 phone
screenshots, and every one was sent again with every later model call.

The first redraws under the text caps were boxes again: `+====+` boxes of a word or two with a
small `(0_0)` beside them, their text swapped for rows of `#` to pass the letter cap. They were 56%
box characters at the median. designer_toad's chat held 225 messages of its own old art, and Flash
kept drawing like it whatever the instructions said.

Style 5, with high thinking and the artists' pieces as examples, drew 170 pieces overnight that
still read as diagrams. It had moved its outlines from `+--+` to `.~~.`, `/ \` and `( )`, which the
box cap didn't count, so words sat in round outlines (`( union U: 4 bytes )`); and 82 of the 170
ended in two or three rows of `~~~~~~~~`, a third of all their ink, which diluted the letter share
as the rows of `#` had.

## Decision

**The art carries the idea; text is labels of 1 to 3 words.** A gag may add one line of dialogue,
best a meme the reader knows, a famous character's signature line, or a sarcastic remark. No
sentence explains the drawing inside it: the caption under the art does that. An informative
drawing shows the mechanism as a picture (plates for a stack, people in line for a queue) and may
carry a few more words. Both aim to be worth a screenshot.

**Drawings, mostly of scenes and objects.** Animals, machines, buildings, vehicles, famous
characters, drawn big. A stick figure or a small face is at most part of a scene, never the whole
piece, and a batch draws different kinds of things.

**Code checks it**, in `art.ts` (`ART_LIMITS`), before a piece is rendered:

| Kind | Words (two letters or more) | Letters | Box lines (`+ \| = - # [ ]`) |
|---|---|---|---|
| gag | at most 12 | at most 30% | at most 40% |
| informative | at most 20 | at most 40% | at most 45% |

Letters and box lines are shares of the characters that aren't spaces. A run of one letter (`oo`,
`wWw`) draws, so it isn't a word. A row of `#` runs alone on its line, or alone between a box's
sides, stands in for text and is refused; `#` that shades a drawing (`(#####)`, `|####|`) isn't.
The box caps refuse every one of the first redraws and pass 98% of asciiart.eu's pieces and both
of the prompt's worked examples. A refusal says how much text or box the piece has.

**An outline is a box whatever draws it.** Every character that walls a word in counts as a box
line: a word is walled in when no path through spaces, letters and digits leads from it out of the
art (`outlineCells`). **Padding doesn't count**: a row of one character repeated eight times or
more is filler, and every filler row after the first is left out of the measure, so one ground or
water line still draws. With both, 83 of style 5's 170 pieces are refused; of the old library's
pieces, 2% more are refused than before (mostly words written on a drawn sign or shirt), and every
example in the prompt passes.

**References come from the web.** For a meme or a famous character, designer_toad finds it with
`web_search`, sees its picture with `look_at` (the page or picture in headless Chromium, one
screenshot), and draws it in ASCII itself, bent to the card. No ASCII art is copied in, and the
curated library of the old pipeline is not used: nothing in the harness comes from old code.

**A new style is tried before anything is redrawn.** `ART_STYLE` is 6; attaching art writes the
style onto the card's `gen_meta.artStyle`. Style 2 had the text caps without the prompt's worked
examples; style 3 had the examples but not the box check; style 4 passed the box check with words
inside round outlines (`.____.` over `(   )`), 40 pieces the owner had redrawn; style 5 added high
thinking and the artists' pieces, and padded with `~`; style 6 adds the outline and padding
checks. Four styles in a row redrew every piece before anyone saw what the new rules drew, so a
style newer than `APPROVED_ART_STYLE` draws 30 pieces of a topic (`ART_TRIAL`), first art or
redraws, and then `list_art_requests` lists nothing, saying the owner is looking at them. Once the
owner approves the 30, `APPROVED_ART_STYLE` is raised to the style, and every card whose art is an
older style is drawn again, live ones too. `list_art_requests` lists the cards waiting for their
first art first, since they hold their tiers back, then the redraws, marked Redraw, without their
old art. It shows one batch of 5 at a time, the owner's pick over 10: each piece gets more of the
model's attention, and each answer is shorter on a paid subscription.

**The request gives the idea, not the layout.** The writers' art requests often describe a
diagram (regions side by side, boxes with their label text, arrows, numbered stations), and in the
first comparison every model that drew one faithfully drew a diagram the owner rejected; the one
that told the same mechanism as a story with characters won. designer_toad takes the idea and finds
the scene, and the tier writer's request names a scene with real things, never a diagram. A gag's
line is a catchphrase people already say ("Who dis?", "Not so fast.") over one that restates the
idea, and a gag is one scene, two or three labels and the line.

**The art leads its card.** On a code subject most ascii cards carry a code block too, and the web
card let a body fence outrank `visual_slots.art`, a rule from the old pipeline, which drew one scene
into both: on 219 of the Rust run's 304 ascii cards the art was shown nowhere, and every render
designer_toad judged showed the code instead. A card's art now leads whenever it has art, and the
code stays in the body (`resolveHero` in `Card.tsx`).

**designer_toad draws on Claude Opus 5.5 at medium thinking**, through the owner's Claude Code
sign-in on the proxy; every other chat stays on Gemini. Gemini 3.8 Flash at high drew style 5 and
6. The owner then had the same cards drawn by Gemini, Claude Opus 5.5 and GPT 6.1 Sol, each with
designer_toad's prompt, checks and phone render, judging its own screenshots: round one was split
(Gemini's drawing and GPT's line on one gag, GPT's stamp, Claude's reactor), round two went to
Claude, and round three, Claude against GPT, went to Claude. Claude and GPT each took about two
minutes for five cards, Gemini about six (`drawsOnClaude` in `set-up.ts`).

**The prompt's examples** are two pieces drawn for it (a melting snowman, a stack of plates), the
best piece of the style-4 run (a ghost, its label moved from a badge on its body to under it for
style 6), the owner's picks from the first comparison of art models (Gemini's two cats named temp
with GPT's line "Who dis?", GPT's rejection stamp, Claude's reactor told as a story), and the pieces the owner chose from the old pipeline's
curated library as the craft to aim for: Joan G. Stark's mermaid, spider and Homer, Hayley Jane
Wakenshaw's cat in a box, Riitta Rasimus's whale, and a mushroom cloud and a devil in flames by
unknown artists. Any other library piece goes in only with the owner's leave.

**designer_toad's chat started over** for style 4 and again for style 5: a summary record through its last run, written by
the owner's leave, says it started over, so the model no longer sees its old art. The transcript
keeps every message.

**A screenshot is shown to the model once**, in the call right after the tool call that took it
(`imagesShownOnce` in `run-chat.ts`). The transcript keeps every image.

## Consequences

**Easier.** The art reads at a glance and is the hook again. The designer's prompts stay small, so
a turn of many batches costs about the same per call.

**Harder.** A label of four or more words has to go, a scene that needs explaining has to be
redrawn, not captioned in place, and a diagram has to become a picture. Live cards change art under
readers who saw the old one. The designer can't look back at an earlier screenshot; it renders or
looks again if it needs to.

**Committed to.** Raising `ART_STYLE` starts a trial of 30 pieces; approving it redraws every
piece of a lower style, live ones included. Approval is a code change (`APPROVED_ART_STYLE`), so
the worker is rebuilt to start the redraw.

## Alternatives considered

**Prompt guidance alone.** Rejected: ADR-0099's guidance was prompt-only and produced the walls of
text, and style 3's worked examples alone produced boxes. The owner's rule is to enforce in code
what must be true.

**A per-label check (no run of more than three words).** Rejected for now: telling two labels on one
line apart from one long label needs guessing at spacing, and the word and letter caps already stop
sentences.

**The old pipeline's curated library as references.** Tried for a few hours as
`search_art_library`, then removed: the owner's rule is that nothing in the harness comes from old
code, and the designer drew boxes with it all the same. Only pieces the owner picks go into the
prompt as examples.

**Copying ASCII art from other sites at run time.** Rejected: the pieces stay their artists', and
the point is art drawn for the card. A reference picture is looked at, not copied.

## Revisit when

The owner finds rendered art still text- or box-heavy, or the refusals stall the designer (many
pieces refused twice).
