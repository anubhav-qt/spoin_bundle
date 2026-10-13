# ADR-0109: ASCII art is art first, its text labels, checked in code

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** project owner
- **Amends:** [ADR-0099](0099-ascii-scenes-carry-their-own-explanation.md) (how much text a scene
  carries), [ADR-0079](0079-ascii-library-is-gags-only.md) (the curated library returns, as
  designer_toad's references)

## Context

The first harness run (Rust in easy language, task 0045) gave designer_toad 128 ascii cards. The
owner read them and found walls of text with a little art: tiny `(o_O)` figures beside long labels,
a line of dialogue, and a summary sentence under a `=====` rule that repeated the caption. Measured
over the 128: gags had a median of 21 words (p10 15, p90 26) and letters were half of every
character that wasn't a space; informative drawings 23 words, 47% letters. The curated library's
pieces, by real ASCII artists, are 3% letters at the median.

ADR-0099 asked for text on every scene because wordless art couldn't be read. The prompt then
asked for labels, dialogue and a caption, and the model wrote all three at length.

designer_toad's prompts had also reached 412k tokens: each render returns up to 10 phone
screenshots, and every one was sent again with every later model call.

## Decision

**The art carries the idea; text is labels of 1 to 3 words.** A gag may add one line of dialogue,
best a meme the reader knows or a sarcastic remark. No sentence explains the drawing inside it: the
caption under the art does that. An informative drawing shows the mechanism as a picture (plates for
a stack, people in line for a queue) and may carry a few more words. Both aim to be worth a
screenshot.

**Code checks it**, in `art.ts` (`ART_TEXT`), before a piece is rendered:

| Kind | Words (two letters or more) | Letters, of the characters that aren't spaces |
|---|---|---|
| gag | at most 12 | at most 30% |
| informative | at most 20 | at most 40% |

A run of one letter (`oo`, `wWw`) draws, so it isn't a word. The refusal says how many words and
what share of letters the piece has.

**The curated library is designer_toad's reference.** `search_art_library` finds pieces of the
owner's curated library (scraped from asciiart.eu, ADR-0068) by the words of their titles, and the
designer builds on a figure rather than copying it, adding the card's labels and line.

**Art drawn before this is drawn again.** `ART_STYLE` is 3; attaching art writes the style onto the
card's `gen_meta.artStyle`. Style 2 was these rules without the prompt's two worked examples: its
first pieces passed the caps as boxes of words with a small `(o_o)` beside them, so it is drawn
again too. `list_art_requests` lists the cards waiting for their first art first,
since they hold their tiers back, then every card, live ones too, whose art is an older style,
marked Redraw. It shows one batch of 10 at a time.

**A screenshot is shown to the model once**, in the call right after the tool call that took it
(`imagesShownOnce` in `run-chat.ts`). The transcript keeps every image.

## Consequences

**Easier.** The art reads at a glance and is the hook again. The designer's prompts stay small, so
a turn of many batches costs about the same per call.

**Harder.** A label of four or more words has to go, and a scene that needs explaining has to be
redrawn, not captioned in place. Live cards change art under readers who saw the old one. The
designer can't look back at an earlier screenshot; it renders again if it needs to.

**Committed to.** Raising `ART_STYLE` redraws every piece of a lower style, live ones included,
whenever the style changes again.

## Alternatives considered

**Prompt guidance alone.** Rejected: ADR-0099's guidance was prompt-only and produced the walls of
text. The owner's rule is to enforce in code what must be true.

**A per-label check (no run of more than three words).** Rejected for now: telling two labels on one
line apart from one long label needs guessing at spacing, and the word and letter caps already stop
sentences.

**Free art from other sites at run time.** Rejected: asciiart.eu's pieces stay their artists', and
the owner's curated library already holds the best of it, checked to 40 columns.

## Revisit when

The owner finds rendered art still text-heavy, or the refusals stall the designer (many pieces
refused twice for text).
