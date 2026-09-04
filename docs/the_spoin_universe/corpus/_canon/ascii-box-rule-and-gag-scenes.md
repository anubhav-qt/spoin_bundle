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

## The ASCII Box Rule

Language models lack native spatial coordinate reasoning. When allowed to generate or edit ASCII art freely, models skew columns, misalign vertical borders, and produce illegible, sideways drawings. To guarantee aesthetic quality, ADR-0021, ADR-0068, and ADR-0079 establish the **ASCII Box Rule**:

1. **Art is an Immutable Rigid Box:** The ASCII drawing is treated as a fixed two-dimensional character block. The model must never edit lines inside the drawing, delete interior characters, or attempt to redraw parts of the figure.
2. **Nothing Inserted to the Left:** No characters, labels, prefixes, or dialogue may be placed to the left of the artwork. Inserting characters to the left shifts the entire drawing rightward, breaking horizontal column alignment.
3. **Captions and Annotations Restricted to Safe Zones:**
   - Text, titles, or stage directions (`*CONFUSED LOOK*`) must be placed strictly **above** the art block or **below** the art block.
   - Speech bubbles or dialogue labels appended to the right of the art block must strictly preserve the base drawing's line coordinates.
4. **The 40-Column Width Invariant:**
   - Every single line of the ASCII visual—including characters, leading whitespace, trailing dialogue, and borders—**must not exceed 40 monospace columns**.
   - Mobile smartphone viewports break and force awkward horizontal scrolling or line-wrapping if a preformatted block exceeds 40 characters.

## Server-Side Validation and Graceful Degradation

Because prompt instructions alone cannot guarantee 100% compliance across smaller generator models (such as `ministral-3b` and `ministral-8b`), the Spoin backend enforces the 40-column rule via a deterministic server-side validator:

- **Validation Pass:** Upon receiving a generated card draft carrying a `visual_slots` payload, the system splits the raw ASCII text into individual lines and measures the character length of each line.
- **The Degradation Rule:** If **any single line** in the ASCII block exceeds 40 characters, or if the block contains prohibited syntax (such as embedded backticks or malformed line endings), **the system automatically removes the card**.
- **The Card is not kept:** The text of the card (`title`, `canonical_title`, `summary`, `body`) is discarded and not published.

This ensures that failures degrade gracefully to **"no card"**, and then are regenerated again to get better visuals.
