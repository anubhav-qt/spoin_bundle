"""Card generation prompts and system instructions for all card types and hero cards."""

from __future__ import annotations

ASCII_INSTRUCTIONS = """\
Sometimes — not every card, only when a concept genuinely lends itself to it —
you may ALSO draw a small ASCII scene that shows the idea rather than just
describing it: a weird stickman gag, one or two panels, something silly but
informative — it should actually dramatize the concept, not just decorate the
card. Canonical example (weight classes in wrestling): panel one shows two
stick figures facing off, panel two shows the heavy one sitting on the light
one, who says "shouldn't have done this". That is the bar for charm —
recognizable, funny, and it actually shows the concept rather than being
decoration.

A card's ASCII scene, if it has one, renders right below the title, in place
of the usual one-line summary/hook — the FIRST thing about the card's actual
content, before body. When this card appears collapsed/previewed in the
feed, the scene itself IS the preview (instead of the usual text teaser), so
the art needs to work as a stand-alone thumbnail, not just as an
illustration inside a longer read.

If you draw one, set:
- ascii_label: a short slug for it (e.g. "sit-on-guy"), never empty if art is present.
- ascii_art: the raw art itself, newline-separated. HARD LIMIT: every line at
  most 40 characters — a phone renders roughly 38-42 monospace columns, and
  art that wraps is destroyed, not degraded. Count characters before you
  commit to a line. If you cannot make the scene work in 40 columns, do not
  draw it at all rather than drawing it badly.
- ascii_alt: one plain sentence describing the scene, for a screen reader.

Leave all three empty (ascii_label, ascii_art, ascii_alt) for any card where
no scene genuinely fits — a joke format on every card is not a joke format,
it is a layout. Most cards should have none.
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

CARDS_COMMON_HEADER = """\
You write flashcard-style learning content for a learning app, at a single \
requested difficulty, for one subtopic at a time.

""" + CARD_FIELDS_BLOCK + """

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

CARDS_SYSTEM = CARDS_COMMON_HEADER + "\n" + ASCII_INSTRUCTIONS

CARDS_ASCII_SYSTEM = CARDS_COMMON_HEADER + """

CARD TYPE REQUIREMENT — ASCII ART SCENE WITH STICKMAN (MANDATORY):
Every single card in this batch MUST include a charming, funny ASCII scene featuring \
STICKMAN characters (using stickman is a MUST, not optional).
- The scene must be a 1 or 2 panel stick-figure comic/gag that dramatizes or illustrates \
the concept with humor and insight (e.g. stick figures interacting, wrestling, arguing, \
trying the wrong thing, captioning the core idea).
- Every card in this batch MUST set all three ASCII fields:
  * ascii_label: a short slug for the scene (e.g. "stickman-race"), NEVER empty.
  * ascii_art: the raw ASCII drawing. HARD LIMIT: every line must be at most 40 characters wide!
  * ascii_alt: one plain sentence describing the stick figure scene for screen readers.
- Do NOT omit the ASCII art on any card in this batch.
"""

CARDS_COMPARISON_SYSTEM = CARDS_COMMON_HEADER + """

CARD TYPE REQUIREMENT — MYTH VS FACT / COMPARISON (MANDATORY):
Every single card in this batch MUST be a misconception-busting or "wrong way vs right way" \
comparison card.
- In the `body` field of every card, you MUST include a comparison pair starting with:
  ❌ **Myth / Wrong Way**: [State the common misunderstanding or flawed approach]
  ✅ **Fact / Right Way**: [State the true behavior or best practice]
- Followed by a concise, clear explanation explaining WHY people make this mistake \
and how the underlying mechanism actually works.
"""

CARDS_CODE_SYSTEM = CARDS_COMMON_HEADER + """

CARD TYPE REQUIREMENT — CODE / COMMAND / CONFIGURATION (MANDATORY):
Every single card in this batch MUST teach a practical, concrete code, command, \
query, or configuration example.
- In the `body` field of every card, you MUST include a syntax-highlighted fenced code block \
with a language tag (e.g. ```python, ```bash, ```sql, ```typescript, ```yaml, ```dockerfile).
- The code block must be clean, realistic, and directly illustrate the concept being explained.
"""

CARDS_DIAGRAM_SYSTEM = CARDS_COMMON_HEADER + """

CARD TYPE REQUIREMENT — DIAGRAM / PROCESS FLOW (MANDATORY):
Every single card in this batch MUST illustrate an architecture, request lifecycle, \
data flow, or state transition diagram.
- In the `body` field of every card, you MUST include a fenced diagram block (```diagram \
or ```text) or an ASCII arrow chain using box-drawing characters (`+---+`, `| |`, `┌─┐`) \
or arrows (`-->`, `──>`).
- The diagram must clearly show steps, components, or state changes.
"""

CARDS_PROSE_SYSTEM = CARDS_COMMON_HEADER + """

CARD TYPE REQUIREMENT — CONCEPTUAL PROSE & MENTAL MODELS:
Every single card in this batch MUST focus on deep conceptual understanding, \
intuition, physical analogies, and fundamental principles.
- Focus on crystal-clear prose and strong mental models without forcing \
artificial code blocks or diagrams.
"""

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
the one card in the subtopic guaranteed to be seen, and art here earns its \
keep more than almost anywhere else. Still entirely optional, still only \
when a scene genuinely fits — a forced or mediocre scene is worse than none.
"""
)

CARDS_USER = """\
Topic: {topic_name}
Subtopic: {subtopic_title}
Subtopic description: {subtopic_description}
Difficulty: {difficulty}
Write exactly {count} NEW cards at this difficulty for this subtopic.
{difficulty_examples_block}
Already covered in this subtopic (do not repeat any of these):
{existing_titles_block}
{avoid_bodies_block}{rejection_feedback_block}{builds_on_block}"""
