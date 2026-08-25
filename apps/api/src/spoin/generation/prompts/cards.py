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
   - ascii: an idea a small, funny stick-figure scene would genuinely dramatize.

For each entry give:
- canonical_title: the literal, descriptive name of the idea. Never playful, \
never a joke — the writer invents the playful display title, not you. This is \
the name the concept is findable by.
- card_type: exactly one of prose, code, diagram, comparison, ascii.
- asset_direction: what the card's non-prose element should actually SHOW. \
Be concrete and specific to the idea: for diagram, name the actual boxes and \
what flows between them; for code, name the language and what the snippet \
demonstrates; for ascii, describe the gag and what makes it land; for \
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
Sometimes — not every card, only when a concept genuinely lends itself to it —
you may ALSO draw a small ASCII scene that shows the idea rather than just
describing it: a weird stickman gag, one or two panels, something silly but
informative — it should actually dramatize the concept, not just decorate the
card.

Canonical Examples of Stickman ASCII Scenes (under 40 columns wide):

Example 1 (System Design - Single Point of Failure):
```
[Panel 1]          [Panel 2]
  \o/   \o/          \o/   \o/
   |     |            |     |
   |-----|            |-----|
      |                  |   *BOOM*
   [SERVER]           [  X  ]
   "We good!"         "WHO TRIPPED WIRE?!"
```

Example 2 (Biology / Immunology - Antibodies tagging pathogens):
```
 [Antibody]         [Tagged Virus]
   \o/ *Y*             (o_o)
    |  -->            / | \ *Y*
   / \                 / \  "GET IT OFF ME"
 "Target acquired."
```

Example 3 (Economics - Inflation):
```
 1990:              2026:
  \o/ [$100]         \o/ [$100]
   |   --> [BURGER]   |   --> [CRUMB]
  / \                / \  "IS THIS AIR?!"
```

A card's ASCII scene, if it has one, renders right below the title, in place
of the usual one-line summary/hook — the FIRST thing about the card's actual
content, before body. When this card appears collapsed/previewed in the
feed, the scene itself IS the preview (instead of the usual text teaser), so
the art needs to work as a stand-alone thumbnail, not just as an
illustration inside a longer read.

If you draw one, set:
- ascii_label: a short slug for it (e.g. "single-point-failure"), never empty if art is present.
- ascii_art: the raw art itself, newline-separated. HARD LIMIT: every line at
  most 40 characters — a phone renders roughly 38-42 monospace columns, and
  art that wraps is destroyed, not degraded. Count characters before you
  commit to a line. If you cannot make the scene work in 40 columns, do not
  draw it at all rather than drawing it badly.
- ascii_alt: one plain sentence describing the stick figure scene for a screen reader.

Leave all three empty (ascii_label, ascii_art, ascii_alt) for any card where
no scene genuinely fits.
"""

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

CARD TYPE REQUIREMENT — STICKMAN ASCII COMIC SCENE (MANDATORY):
Every single card in this batch MUST include a funny, charming ASCII comic featuring \
STICKMAN characters (using stick figures is a MUST).
- The scene must be a 1 or 2 panel stick-figure gag/comic that dramatizes the concept:
  * Characters reacting, wrestling, panicking, failing, or dramatizing the metaphor.
  * Use facial expressions (`(o_o)`, `\o/`, `(-_-)`), speech quotes, and action labels.
  * Every line MUST be STRICTLY <= 40 characters wide!
- Set all three ASCII fields on every card:
  * ascii_label: short descriptive slug (e.g. "stickman-server-crash"), NEVER empty.
  * ascii_art: the raw ASCII drawing.
  * ascii_alt: one plain sentence describing the stick figure comic for screen readers.
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

CARD TYPE REQUIREMENT — DOMAIN-SPECIALIZED DIAGRAM (MANDATORY):
Every single card in this batch MUST illustrate the concept using a clear ASCII / text diagram \
tailored to the domain and topic.
- Format the diagram in a fenced block (```text or ```diagram) or clean ASCII arrow chains.
- Use domain-appropriate archetypes:
  * **System Design / CS**: Multi-tier architecture, request routing, caching layers, \
    primary/replica DBs, message queues, state machines.
    Example:
    ```text
    Client ──> [Load Balancer]
                  │
      ┌───────────┴───────────┐
      ▼                       ▼
    [API Service 1]       [API Service 2]
      │       ▲             │
      │       └─[Redis]─────┘
      ▼ (Write)
    [Primary DB] ──Replica──> [Read DB]
    ```
  * **Biology & Physical Sciences**: Pathways, feedback regulation, biochemical cycles.
    Example:
    ```text
    [High Glucose] ──> [Beta Cells: Insulin]
                              │
                        (Cell Uptake)
                              ▼
    [Liver Stores Glycogen] ──> [Normal Glucose]
    ```
  * **History & Humanities**: Timelines, causal chains, branching decisions.
  * **Economics & Business**: Market loops, supply/demand cycles, multi-stage funnels.
- Accompany the diagram with a clear explanation of how data or state moves through the system.
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
A hero card is exactly the kind of card an ASCII stickman scene suits best — it is \
the one card in the subtopic guaranteed to be seen. If a humorous stickman gag or physical \
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
