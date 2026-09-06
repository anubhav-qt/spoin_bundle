---
title: The ASCII Box Rule and Curated Gag Scene Constraints
kind: spoin_canon
source: Spoin ADR-0021, ADR-0068, and ADR-0079
topic_tags:
  - spoin canon
  - ascii art
  - ascii box rule
  - gags only
  - formatting constraints
---

## Every ASCII Card is a Gag

ASCII art in Spoin serves a singular editorial function: **it is a humorous visual hook**. 

ADR-0068 initially explored dividing ASCII art into two categories: comedic gags and "informative technical illustrations" (such as drawings of hardware components or database files). ADR-0079 formally repealed the informative half:
- **Gags Only:** Every card carrying an ASCII slot must depict a comedic gag—a humorous character reaction, a witty pop-culture reference, an absurd physical metaphor, or a comical scene that punctuates the card's concept.
- **Informative Content Belongs in Mermaid or Prose:** An idea that requires neutral, objective structural representation is a `diagram` card (rendered cleanly via client-side Mermaid) or a structured Markdown `prose` card. Using an ASCII slot for an uninspired, static drawing of a server rack or a flowchart is strictly forbidden.

The scenes users screenshot and share are the witty ones. The ASCII slot exists to provide character, levity, and engagement at the perimeter of an otherwise rigorous technical curriculum.

## The ASCII Box Rule: The Art Is Immutable

Language models lack native spatial coordinate reasoning. When allowed to generate or edit ASCII art freely, models skew columns, misalign vertical borders, and produce illegible, sideways drawings. To guarantee aesthetic quality, ADR-0021, ADR-0068, and ADR-0079 establish the **ASCII Box Rule**. Its first half governs what may be done to a drawing at all:

1. **Art is an Immutable Rigid Box:** The ASCII drawing is treated as a fixed two-dimensional character block. The model must never edit lines inside the drawing, delete interior characters, or attempt to redraw parts of the figure.
2. **Nothing Inserted to the Left:** No characters, labels, prefixes, or dialogue may be placed to the left of the artwork. Inserting characters to the left shifts the entire drawing rightward, breaking horizontal column alignment.
3. **Captions and Annotations Restricted to Safe Zones:**
   - Text, titles, or stage directions (`*CONFUSED LOOK*`) must be placed strictly **above** the art block or **below** the art block.
   - Speech bubbles or dialogue labels appended to the right of the art block must strictly preserve the base drawing's line coordinates.
## The ASCII Box Rule: Width, Height and the Text a Scene Carries

The second half of the **ASCII Box Rule** (ADR-0021, ADR-0068, ADR-0079, ADR-0099) governs the shape of the scene rather than the handling of it: how wide a line may be, how tall a drawing may grow, and what words must ship with it. Numbering continues from the immutability rules above.

4. **The 40-Column Width Invariant:**
   - Every single line of the ASCII visual—including characters, leading whitespace, trailing dialogue, and borders—**must not exceed 40 monospace columns**.
   - Mobile smartphone viewports break and force awkward horizontal scrolling or line-wrapping if a preformatted block exceeds 40 characters.
5. **Height is Unbounded (ADR-0099):**
   - The budget is **per line, not per drawing**. Nothing measures how tall a scene is, and no validator has ever done so.
   - Lines added above or below the art are therefore **free**, and a scene may grow downward as far as its text needs.
   - So a label that will not fit beside a figure **gets its own line above or below it — it is never shortened away and never dropped**. Trimming text to save columns is the wrong repair; moving it down is the right one.
6. **No Emoji, Ever:**
   - An emoji is a single codepoint that renders **two monospace columns**, so a line measuring 38 characters draws as 44. The 40-column budget is silently broken and no validator counting characters can see it.
   - It also destroys alignment against the plain ASCII glyphs beside it, which is the column integrity the box rule exists to protect.
   - Use plain ASCII instead: `*` for a spark, `~` for water, `o` for a body, `#` for mass, `^` for a peak.

7. **Every Scene Must Carry Text (ADR-0099):**
   - The scene is the card's hook — the first thing a reader meets. Art with no words is unreadable to anyone who cannot decode the picture, which makes a wordless scene a failed hook rather than a minimal one.
   - Every scene ships with **labels naming its parts** (which figure is the king, which box is the heap, what the arrow does) **and at least one line of dialogue, stage direction, or caption** that lands the gag for that specific card.
   - Most curated art is far narrower than the budget — a typical line uses about 23 of the 40 columns — so short labels usually fit to the right of a figure as well.

## Server-Side Validation and Graceful Degradation

Because prompt instructions alone cannot guarantee 100% compliance across smaller generator models (such as `ministral-3b` and `ministral-8b`), the Spoin backend enforces the 40-column rule via a deterministic server-side validator:

- **Validation Pass:** Upon receiving a generated card draft carrying a `visual_slots` payload, the system splits the raw ASCII text into individual lines and measures the character length of each line.
- **The Degradation Rule:** If **any single line** in the ASCII block exceeds 40 characters, or if the block contains prohibited syntax (such as embedded backticks or malformed line endings), **the system automatically removes the card**.
- **The Card is not kept:** The text of the card (`title`, `canonical_title`, `summary`, `body`) is discarded and not published.

This ensures that failures degrade gracefully to **"no card"**, and then are regenerated again to get better visuals.

## The Caption Beneath the Scene

Every scene carries a one-sentence caption, stored as `visual_slots.alt` and printed under the drawing on the card.

**It is not screen-reader alt text and it is not a title.** It is written for a sighted reader who could not make sense of the drawing, and it must give them both halves: **what the drawing is showing, and what the joke is**. Naming the shapes is not enough — name the thing being depicted and the point it makes.

This was specified as "one plain sentence describing the scene for a screen reader" until 2026-09-05, which asked for the wrong artefact: alt text enumerates, a caption explains. See ADR-0099.
