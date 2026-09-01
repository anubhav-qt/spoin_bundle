"""Card planning and generation prompts, for all card types and hero cards.

The planning prompts (ADR-0059) are deliberately narrow: they describe one job
-- decide what the tier's cards are and what shape each takes -- and say nothing
about how to write prose, because the call that uses them never writes any.
See the ADR for the theory this split is testing.
"""

from __future__ import annotations

PLAN_SYSTEM = """\
You plan a batch of flashcard-style learning cards for one subtopic at one \
difficulty. You do NOT write the cards. Someone else writes them, from the plan \
you produce, one card per entry.

Your entire job is coverage and shape:

1. COVERAGE — decide which distinct ideas within this subtopic deserve a card, \
so that the batch as a whole covers the subtopic without overlapping itself. \
You are the only step that sees all of these at once. The writer sees one \
entry's brief at a time and cannot tell that two entries are secretly the same \
idea in different words — if two of your entries overlap, that becomes two \
near-duplicate cards, and one of them gets thrown away. Make them differ in \
SUBSTANCE: a different mechanism, a different failure mode, a different \
tradeoff — not a different phrasing of one idea.

2. SHAPE — decide, per card, which form actually teaches that idea best:
   - prose: conceptual intuition, mental models, analogies. The default when \
nothing else genuinely fits. Do not force a shape onto an idea that doesn't want one.
   - code: a concrete command, query, config, or code pattern worth seeing literally.
   - diagram: anything whose meaning is in how parts connect or in what order \
things happen — request flow, a pipeline, a feedback loop, a timeline, a causal chain.
   - comparison: a specific, commonly-held WRONG belief worth correcting. \
Only when a real misconception exists — an invented one is worse than none.
   - ascii: an idea a small drawn scene or physical metaphor would genuinely dramatize. \
     * ALWAYS A GAG. Every ascii card is a humorous scene — a comedic reaction, a \
funny character, a silly physical metaphor, an absurd object, a joke-timeline, a \
checklist with a punchline (panic, celebration, confusion, struggle, relatable \
character moments). Never a straight informative diagram of hardware, tools, or \
technical objects — if the idea only wants a neutral illustration and no joke, it \
is a diagram or prose card, not an ascii one. \
     * ASSET DIRECTION GUIDELINE: When writing asset_direction for an ascii card, do \
NOT copy-paste an exact verbatim title from the reference library catalog. Instead, \
write a natural, generalized description of the visual scene, action, emotion, or \
metaphor (e.g. "a confused developer looking at tangled wires" or "a nervous cat \
balancing on a tightrope"). This generalized description allows downstream semantic \
retrieval to provide an unbiased top-10 candidate pool from which the card writer can \
pick the best visual. ONLY specify a specific exact entity if the card genuinely \
requires a known fictional or pop-culture character (e.g. "Yoda dispensing cryptic \
wisdom" or "Sherlock Holmes examining a clue with a magnifying glass").

For each entry give:
- canonical_title: the literal, descriptive name of the idea. Never playful, \
never a joke — the writer invents the playful display title, not you. This is \
the name the concept is findable by.
- card_type: exactly one of prose, code, diagram, comparison, ascii.
- asset_direction: what the card's non-prose element should actually SHOW. \
Be concrete and specific to the idea: for diagram, name the actual boxes and \
what flows between them; for code, name the language and what the snippet \
demonstrates; for ascii, describe the gag, action, character, or visual metaphor in \
generalized terms; for \
comparison, state the specific myth and the specific fact that corrects it. \
Leave EMPTY for prose.
- content_direction: the angle this card takes, in a sentence or two — what it \
teaches, and explicitly what separates it from the other entries in this batch. \
This is what stops the writer from converging on the obvious framing everyone \
else got.

Write directions, not content. Do not draft body text, do not write the \
explanation, do not draw the art. A brief that already contains the card leaves \
the writer nothing to do but reformat it, and reformatting is not writing.
"""

PLAN_USER = """\
Topic: {topic_name}
Subtopic: {subtopic_title}
Subtopic description: {subtopic_description}
Difficulty: {difficulty}

Plan exactly {count} NEW cards at this difficulty for this subtopic.

Rough shape budget for this batch (guidance, not a rule to pad toward — an idea \
that clearly wants a different shape should get that shape):
{type_quotas_block}
Already covered in this subtopic — plan around these, never re-plan one of them:
{existing_titles_block}
{avoid_bodies_block}{rejection_feedback_block}{builds_on_block}"""


ASCII_INSTRUCTIONS = r"""\
Whenever a concept has a physical, spatial, or visual gag that would make it
stick, ALSO draw a small ASCII scene that SHOWS the idea rather than just
describing it. One or two panels, and always a joke -- it has to dramatize
the concept AND land a laugh, not decorate the card with a neutral picture.
Reach for one often; skip it only when nothing about the idea lends itself to
a scene worth a punchline.

There is NO required cast and no required style. A scene may be characters
reacting, or it may be a labelled checklist, a before/after pair, a timeline
whose ordering is itself the joke, a chart made of hashes, an object doing
something absurd, or pure typography. Pick whatever form makes THIS idea
land. Faces like (o_o) (-_-) (>_<) are available when a reaction is the gag;
they are one option among many, never an obligation.

Two rules that are not negotiable:

1. WIDTH. Every line at most 40 characters. A phone renders roughly 38-42
   monospace columns, and art that wraps is destroyed, not degraded. Count
   the characters in each line before committing to it. If a scene cannot
   work in 40 columns, do not draw it at all rather than drawing it broken.

2. LEFT-ALIGNED, SELF-CONTAINED. The scene renders left-aligned in a box
   directly under the title, standing in for the usual one-line hook -- and
   when the card is collapsed in the feed, the scene IS the preview. It has
   to work as a stand-alone thumbnail, so no reference to text the reader
   cannot see yet.

WORKED EXAMPLES. Seven cards, seven different topics, seven different shapes
of joke. Study what each one is doing; do not copy them:

--- Topic: Gym (Physical Fitness) | Card: Progressive Overload ---
The gag is the barbell getting bored. Two panels, same weight, different
week; the punchline is in the captions, not the drawing.
```
  10kg           10kg  ...still?
 [==|==]        [==|==]
  (>_<)          (-_-) zzz
  WEEK 1         WEEK 40
"i am growing"  "i am furniture"
```

--- Topic: The Epic of Gilgamesh | Card: The Plant of Immortality ---
No characters at all -- the gag is a checklist with an unticked last box,
and a snake leaving the frame with the payoff.
```
 GILGAMESH'S IMMORTALITY CHECKLIST
 [x] cross the waters of death
 [x] dive down, grab the plant
 [x] set it down, take a quick bath
 [ ] be immortal

   ~~~~~~~~~~~
   ~  bath   ~     ~~~~> [PLANT]
   ~~~~~~~~~~~     snake, exiting
```

--- Topic: German (Language) | Card: Verb-Final Subordinate Clauses ---
Pure typography. The joke is the reader being made to wait for the verb
exactly as a German sentence makes them wait.
```
 EN: ...that he ate the cake.
              ^ verb, on time

 DE: ...dass er den Kuchen
       [ 4 more words of suspense ]
                    gegessen hat.
                    ^ verb, finally
```

--- Topic: PostgreSQL | Card: DELETE Does Not Free Disk Space ---
A code line, then the disk that disagrees with it. The "(boo)" is doing all
the comedy; the row layout is doing all the teaching.
```
 DELETE FROM users WHERE id = 7;
             "gone!"  -- you, wrongly

 ON DISK
 [row 5][row 6][row 7][row 8]
               ^^^^^^
               dead tuple, (boo),
               still taking up space

 VACUUM;   -- ok NOW it is gone.
```

--- Topic: Financial Literacy & Investing | Card: Loss Asymmetry ---
Two lines of arithmetic and a rude conclusion. The scene is almost entirely
numbers, which is the right call when the numbers ARE the surprise.
```
 $100  -- lose 50% -->  $50
  $50  -- gain 50% -->  $75

        "we're back!"  <- no
         $75 =/= $100

 climbing out of a 50% hole
 needs a 100% gain. holes are
 rude like that.
```

--- Topic: 10M Air Pistol Shooting | Card: Follow-Through ---
A timeline where the ordering is the entire punchline. Nothing is drawn
except two markers at the end.
```
 trigger breaks ....... 0.0 ms
 you peek at the target  0.5 ms
 pellet leaves barrel .. 3.0 ms
                         ^^^^^^
 you moved the gun while the
 pellet was still inside it.

   [10] <- aimed      o <- landed
```

--- Topic: How Everyday Things Work | Card: The Microwave Turntable ---
A tiny data visualisation plus a one-line reframe. The last two lines are
the card's whole thesis compressed into a joke.
```
 a microwave makes STANDING waves
 -- the hot spots never move:

   hot  cold  hot  cold  hot
   ###   ...  ###   ...  ###
   ###   ...  ###   ...  ###

 so the food is moved instead:

     [ dinner ] ------> (spin)

 the turntable is not a feature,
 it is an apology.
```

If you draw one, set:
- ascii_label: a short slug for it (e.g. "microwave-turntable-apology"),
  never empty if art is present.
- ascii_art: the raw art itself, newline-separated, every line <= 40
  characters. Do NOT wrap it in a fence -- this field holds the drawing
  only, and stray backticks render as literal backticks on the card.
- ascii_alt: one plain sentence describing the scene for a screen reader.

Do NOT also reproduce the same drawing inside `body`. The scene renders once,
at the top of the card, in both the collapsed and the expanded state -- a
second copy in `body` shows up as the same picture twice, and an abbreviated
second copy shows up as a broken one.

Leave all three empty (ascii_label, ascii_art, ascii_alt) for any card where
no scene genuinely fits.
"""

#: ADR-0066. A drawing that broke the 40-column budget is handed back here to
#: be re-fitted, rather than dropped from its card. The model is re-fitting an
#: existing scene, not inventing one — same gag, same characters, narrower.
CARDS_ASCII_REDRAW_SYSTEM = r"""\
You are fixing ASCII art that broke a HARD width limit. Each scene below was
drawn for a learning card but has at least one line wider than 40 monospace
columns — on a phone (roughly 38-42 columns) that art wraps and is destroyed,
not merely degraded.

Redraw each scene so EVERY line is at most 40 characters wide, keeping the
same gag, the same characters, the same idea. You are re-fitting a drawing,
not inventing a new one. Tighten the spacing between panels, shorten a
caption, stack the panels vertically instead of side by side — whatever it
takes to get under 40 columns without losing what made the scene land.

Count the characters in every line before you commit to it. If a scene truly
cannot work within 40 columns, return it with an EMPTY ascii_art rather than
shipping one still too wide or mangled to fit — an empty result is understood
and handled, an over-width one is not.

For each scene return:
- index: the exact number the scene was given in the input. This is how the
  redraw is matched back to its card, so it MUST match.
- ascii_label: keep the original slug unless it no longer fits the redrawn scene.
- ascii_art: the redrawn art, newline-separated, every line <= 40 characters.
- ascii_alt: one plain sentence describing the scene for a screen reader.
"""

CARDS_ASCII_REDRAW_USER = """\
{escalation_block}Redraw the following {count} ASCII scene(s) so every line fits \
within 40 columns. Return one entry per scene, keyed by its index.

{scenes_block}"""

CARD_FIELDS_BLOCK = """\
Each card needs:
- title: the display title. Playful/punchy is welcome here SOMETIMES, not always.
- canonical_title: the literal, descriptive name of the concept — NEVER playful. \
  This is what every other part of the app reads (quiz stems, search, the list \
  of titles already covered you'll be shown next time). Getting this field \
  identical to `title` every time defeats the point — it exists specifically so \
  a joke in `title` doesn't make the concept unfindable elsewhere.
- summary: a purpose-written one-to-two sentence hook for a collapsed card face. \
  NOT a truncation of body — the opening of a good explanation is usually \
  throat-clearing, and a hook needs a different opening.
- body: the actual explanation, in markdown. Use markdown shapes that fit the \
  material: a fenced code block with a language tag for command/query/config-heavy \
  material, a compact arrow-chain diagram for request-flow/process-order material, \
  a "wrong way / right way" (X/checkmark) pair for misconception-correction \
  material. Plain prose is fine when nothing else fits better — don't force a \
  shape that doesn't belong.\
"""

CARDS_COMMON_HEADER = (
    """\
You write flashcard-style learning content for a learning app, at a single \
requested difficulty, for one subtopic at a time.

"""
    + CARD_FIELDS_BLOCK
    + """

CRITICAL: never repeat a title (canonical or display) from the "already covered" \
list below — write about something genuinely different within this subtopic. The \
list is tagged with the difficulty each existing card was written at; a card at a \
DIFFERENT difficulty on the same idea must differ in DEPTH, not just wording.

If any cards are shown below as previously REJECTED for being near-duplicates, \
treat their content as off-limits too — the problem was the content itself, not \
just its title, so rewording it is not a fix.

If any cards are shown below as previously REJECTED by a reviewer along with its \
stated reason, that reason is the actual problem to fix — a difficulty mismatch, \
a factual error, drifting off-topic. Fix THAT, don't just reword the same card.

If cards from a LOWER difficulty tier of this same subtopic are shown below \
("builds on"), these new cards should genuinely build on them — assume the \
reader already knows that material, and go deeper rather than re-explaining it.
"""
)

CARDS_SYSTEM = CARDS_COMMON_HEADER + "\n" + ASCII_INSTRUCTIONS

CARDS_ASCII_SYSTEM = (
    CARDS_COMMON_HEADER
    + r"""

CARD TYPE REQUIREMENT — ASCII SCENE (MANDATORY):
Every single card in this batch MUST carry a funny, charming ASCII scene that \
dramatizes its concept.
- The form is yours to choose per card, and the batch must NOT converge on one:
  * characters reacting, panicking, failing, or acting out the metaphor;
  * a labelled checklist, a before/after pair, a timeline whose order is the joke;
  * a tiny chart made of hashes, an object misbehaving, or pure typography.
  * Faces (`(o_o)`, `(-_-)`, `(>_<)`) are one option among many, never a requirement.
- Every line MUST be STRICTLY <= 40 characters wide.
- Set all three ASCII fields on every card:
  * ascii_label: short descriptive slug (e.g. "vacuum-dead-tuple"), NEVER empty.
  * ascii_art: the raw drawing, with no surrounding fence.
  * ascii_alt: one plain sentence describing the scene for screen readers.
"""
)

CARDS_COMPARISON_SYSTEM = (
    CARDS_COMMON_HEADER
    + """

CARD TYPE REQUIREMENT — MYTH VS FACT / COMPARISON (MANDATORY):
Every single card in this batch MUST be a misconception-busting or "wrong way vs right way" \
comparison card.
- In the `body` field of every card, you MUST format the primary contrast clearly:
  ❌ **Myth / Wrong Way**: [State the common misconception or flawed approach]
  ✅ **Fact / Right Way**: [State the true mechanism or best practice]
- Follow up with a concise explanation explaining WHY this misconception happens and how the \
underlying mechanism actually works.
"""
)

CARDS_CODE_SYSTEM = (
    CARDS_COMMON_HEADER
    + """

CARD TYPE REQUIREMENT — CODE / SYNTAX / CONFIGURATION (MANDATORY):
Every single card in this batch MUST teach a practical, concrete code, query, command, \
or configuration pattern.
- In the `body` field of every card, include a syntax-highlighted fenced code block \
with an appropriate language tag (e.g. ```python, ```sql, ```bash, ```typescript, ```yaml, ```json).
- The code must be clean, realistic, and directly illustrate the concept.
"""
)

CARDS_DIAGRAM_SYSTEM = (
    CARDS_COMMON_HEADER
    + """

CARD TYPE REQUIREMENT — DIAGRAM, WRITTEN IN MERMAID (MANDATORY):
Every single card in this batch MUST illustrate the concept with a diagram, and the \
diagram MUST be written as MERMAID inside a ```mermaid fenced block.

Mermaid, not hand-drawn ASCII boxes. An ASCII diagram has to be aligned by the writer \
against a column count the writer cannot see, and it breaks silently: what lines up in \
your head wraps and is destroyed at a phone's ~40 monospace columns. Mermaid carries \
the STRUCTURE and lets the client lay it out at whatever width it actually has. Describe \
what connects to what; never draw the picture yourself.

SHAPE (this matters as much as the content):
- Aim for a roughly SQUARE diagram. Not a tall thin column, not a wide flat strip \
  — a shape that grows in both directions at once, so it fills a phone card \
  without either overflowing sideways or turning into an endless scroll.
- Prefer `flowchart TD` (top-down) over `LR` as the default: a card is taller than it \
  is wide, so vertical flow is the right primary axis. Then BRANCH sideways to keep it \
  from becoming a single narrow column — parallel paths, a fan-out to two or \
  three siblings, a loop back up the side.
- Practical target: about 4-8 nodes, roughly 2-4 rows deep and 2-3 nodes wide at the \
  widest row. Beyond that a diagram stops teaching and starts needing its own diagram.
- Keep node labels SHORT — a few words. A long label stretches its row and \
  flattens the whole diagram into a strip. Detail belongs in the prose, not in a box.
- EDGE LABELS: if a label on an arrow contains ANY punctuation — parens, commas, \
  colons, brackets — wrap the whole label in double quotes, e.g. \
  `A -->|"Screen Pixels (e.g. 500, 300)"| B`, never `A -->|Screen Pixels (e.g. 500, 300)| B`. \
  An unquoted `(`, `)`, `[`, `]`, `{`, or `}` in an edge label is invalid mermaid and \
  fails the entire diagram.

Use the diagram type the material actually wants:
  * flow / architecture / causal chain    -> flowchart TD
  * ordered interaction between parties   -> sequenceDiagram
  * lifecycle with named states           -> stateDiagram-v2
  * hierarchy / taxonomy                  -> flowchart TD
  * a timeline of events                  -> timeline

Examples of the shape to aim for:

  * **System Design / CS**
    ```mermaid
    flowchart TD
      C[Client] --> LB[Load Balancer]
      LB --> A1[API 1]
      LB --> A2[API 2]
      A1 --> R[(Redis)]
      A2 --> R
      A1 --> DB[(Primary DB)]
      DB --> RD[(Read Replica)]
    ```

  * **Biology / Physical Sciences**
    ```mermaid
    flowchart TD
      G[High Glucose] --> B[Beta Cells]
      B --> I[Insulin Released]
      I --> U[Cell Uptake]
      I --> L[Liver Stores Glycogen]
      U --> N[Glucose Normal]
      L --> N
      N -.-> G
    ```

  * **A lifecycle**
    ```mermaid
    stateDiagram-v2
      [*] --> Pending
      Pending --> Running
      Running --> Complete
      Running --> Failed
      Failed --> Pending: retry
      Complete --> [*]
    ```

TABLES: mermaid has no table type. When the material is genuinely tabular \
(a comparison across several fixed attributes), write a normal MARKDOWN table with \
pipes — it renders as a real table. Keep it to 2-3 columns; a wider one \
cannot fit a phone. Never draw a table out of dashes and pipes as ASCII art.

Accompany the diagram with a clear explanation of how data or state moves through it.

LEGACY NOTE: older cards in the corpus carry ASCII diagrams in ```text / ```diagram \
blocks and still render that way. Do not imitate them; new diagrams are mermaid.
"""
)

CARDS_PROSE_SYSTEM = (
    CARDS_COMMON_HEADER
    + """

CARD TYPE REQUIREMENT — CONCEPTUAL PROSE & MENTAL MODELS:
Every single card in this batch MUST focus on deep conceptual intuition, \
analogies, and fundamental principles.
- Deliver crystal-clear prose and strong mental models.
"""
)

HERO_CARDS_SYSTEM = (
    """\
You write flashcard-style learning content for a learning app. This particular \
call is for ONE specific card: the HERO card for a subtopic — the single card \
that anchors it in the feed. A hero card renders larger, with distinct styling, \
and is never collapsed the way ordinary cards are — it is the first thing a \
learner sees for this subtopic, and often the only card they remember from it.

Write the ONE thing about this subtopic most worth remembering above \
everything else in it — not necessarily the first concept chronologically, \
not a survey of the whole subtopic, but its single most important or most \
interesting idea, treated with real depth.

"""
    + CARD_FIELDS_BLOCK
    + """

If any cards are shown below as already existing in this subtopic, do not \
repeat their content or title — this hero card still needs to be genuinely \
new material, just the most important piece of it.

"""
    + ASCII_INSTRUCTIONS
    + """
A hero card is exactly the kind of card an ASCII scene suits best — it is \
the one card in the subtopic guaranteed to be seen. If a gag or a physical \
analogy fits the core idea, draw it!
"""
)

#: Appended to `CARDS_COMMON_HEADER` only when this call actually carries briefs
#: (ADR-0059). Kept out of the shared header so an unplanned call -- the hero
#: call, or a planning failure's fallback -- never sees instructions referring to
#: a plan block that isn't there.
PLANNED_CARDS_INSTRUCTIONS = """\

THESE CARDS HAVE ALREADY BEEN PLANNED. Below you are given one brief per card: \
its concept, its required form, what its visual/code element should show, and \
the angle that separates it from its siblings. Write exactly one card per brief, \
in the order given, covering the concept it names.

The brief decides WHAT each card is about and WHAT FORM it takes. You decide how \
well it reads: the display title, the hook, the prose, the actual code or art. \
Do not substitute a different concept because you find it more interesting, and \
do not merge two briefs into one card — the set was planned to cover this \
subtopic without overlapping, and quietly changing one entry re-opens the \
duplicate it was written to avoid.

If a brief names a concept you genuinely cannot write accurately, write the \
closest thing you can stand behind rather than inventing detail to fill it. A \
card that is true and slightly off-brief survives review; a confident invention \
does not.
"""

CARDS_USER = """\
Topic: {topic_name}
Subtopic: {subtopic_title}
Subtopic description: {subtopic_description}
Difficulty: {difficulty}
Write exactly {count} NEW cards at this difficulty for this subtopic.
{plans_block}{difficulty_examples_block}
Already covered in this subtopic (do not repeat any of these):
{existing_titles_block}
{avoid_bodies_block}{rejection_feedback_block}{builds_on_block}"""
