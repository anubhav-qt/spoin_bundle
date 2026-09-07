"""How a call is told to use retrieved source material (ADR-0089).

`generation/grounding.py` decides *what* passages a call gets; this decides what the
model is told to do with them. Separate from `canon.py` because canon is a derived
artifact of the corpus with a drift guard over it, and these are ordinary prompt
instructions — putting them in that file would make the guard's subject ambiguous.

Every fragment here is written for a **subtopic-level** context: the block is retrieved
once per subtopic group and shared by the drafter, the corrector and the verifier
(rag-design-space §3.7). That is what makes the "silence is not falsehood" rule below
load-bearing rather than pedantic.
"""

from __future__ import annotations

#: For the calls that WRITE (`plan_cards`, `generate_cards`, `generate_questions`).
WRITER_SOURCES = """\

SOURCE MATERIAL:
When source material is provided below, write from it. It is curated, it is what \
this app claims its content is grounded in, and it is more reliable than your own \
recall — where the two disagree, the source wins.

Do not pad a card with everything a source says: the source is dense reference \
material and a card is one idea. Take the idea the card needs and leave the rest.

Do not restrict yourself to only what the sources cover, either. They are retrieved \
for the subtopic as a whole, not for your specific card, so they will be silent on \
things that are perfectly true — write those normally. What they must never be is \
CONTRADICTED.

When no source material appears below, write as you otherwise would.
"""

#: For the calls that JUDGE (`correct_cards`, `verify_cards`).
#:
#: The second paragraph is the one that matters. The verifier sees passages retrieved
#: for the SUBTOPIC, not for the card in front of it (per-claim retrieval is
#: rag-design-space §3.10 and is deferred), so "the sources do not mention this" is the
#: normal case for a true statement. A gate that treats absence as a rejection reason
#: turns every subtopic into a rejection cascade the moment retrieval is wired on --
#: and it would look like a content-quality collapse in the report, not like a prompt
#: bug. See CLAUDE.md on the gate's failure modes reading as content problems.
JUDGE_SOURCES = """\

SOURCE MATERIAL:
When source material is provided below, check the card's factual claims against it. \
A claim the sources CONTRADICT is a real error: correct it (pass 1) or reject the \
card (pass 2), and prefer what the sources say over what you remember.

A claim the sources simply do not mention is NOT an error. These passages were \
retrieved for the subtopic as a whole, not for this card, so they are silent on most \
true things. Never correct or reject a card for going beyond them — only for \
disagreeing with them.

When no source material appears below, judge as you otherwise would.
"""

#: Task 0038 Phase 3's other half. The corpus is deliberately dense and precise at
#: every tier — an owner decision, on the grounds that one corpus grounds all three
#: tiers, that precision never written down cannot be recovered, and that the verifier
#: retrieves the same chunks the writer did. Which leaves the register to the prompt:
#: without this, a grounded beginner card inherits the source's voice and reads like
#: reference material.
#:
#: This is CLAUDE.md's trusted-for-taste-never-for-constraints split, drawn exactly:
#: precision is a constraint and lives in the corpus, tone is taste and lives here.
#:
#: ADR-0104 rewrote this block. It used to tie REGISTER to tier -- advanced asked
#: for "rigorous, sophisticated, compact domain language" that is "densely packed"
#: -- and the corpus obeyed: Flesch-Kincaid climbed 11.4 -> 13.3 -> 15.4 across
#: Rust's tiers while second-person address collapsed 37.8 -> 12.5 -> 4.4 per 1k
#: words. That is the model doing what it was told. Difficulty and reading level
#: are now two axes and only the first one moves with the tier.
#:
#: The instruction alone is not the fix -- the previous version also said "do not
#: inherit the source's register" and Astronomy inherited it anyway at every tier
#: (0.5 second-person per 1k, flat). `spoin.content.readability` is the check that
#: makes this stick, per CLAUDE.md's "a rule stated only in a doc is a wish".
TIER_LANGUAGE = """\

READING LEVEL & DIFFICULTY CALIBRATION (MANDATORY):

The source material in our corpus is written at reference density for every tier, \
for accuracy rather than for a reader. Do not inherit its voice.

**THE READING LEVEL IS THE SAME AT ALL THREE TIERS. Only the SUBJECT changes.**

This is the rule most likely to be got wrong, so it is stated first and \
absolutely: the tier tells you WHICH IDEA to teach. It never tells you to write \
harder prose. There is no tier at which dense, formal or "sophisticated" \
language is the assignment. An advanced card about the neutron-star equation of \
state and a beginner card about why stars twinkle are written in the same plain, \
direct, welcoming voice, by the same person, for the same curious reader.

THE VOICE, AT EVERY TIER:
   - Plain, conversational English. Short active sentences, one clear idea each. \
Past roughly 25 words, split it in two.
   - **Talk to the reader. Say "you".** "You would expect the core to cool \
first" beats "one would expect initial core cooling". A card that never says \
"you" has stopped teaching and started cataloguing.
   - Every technical term is earned: name it, then say what it means in ordinary \
words, once, however advanced the card. An expert loses nothing to a clear \
definition; a reader without it is simply stopped.
   - Concrete nouns and active verbs. "The star sheds its outer layers", not \
"envelope ejection occurs". "Astronomers measure", not "measurements are obtained".
   - Say quantities the way a person says them: "about 8 times the Sun's mass", \
not raw notation. Use a formula only when the formula is the thing being taught, \
and then say in words what it means.
   - Open with something concrete — a puzzle, a consequence, a correction. Never \
open with a definition or a throat-clearing summary of the field.

WHAT THE TIER ACTUALLY SELECTS — the idea, and nothing else:

1. BEGINNER: foundational concepts, intuitive mental models, observable \
phenomena, and the everyday analogies that make them stick. Assume no prior \
background in the subject.

2. INTERMEDIATE: the mechanism underneath — cause and effect, what balances what, \
how the quantity is actually measured. Explain *how* and *why*, not just *what*.

3. ADVANCED: edge cases, limits, second-order effects, competing explanations, \
open questions, and where the simple story stops being true. Assume the reader \
has met the foundations — but still WRITE them plainly, and still define the \
terms you use.

An advanced card earns its tier by the difficulty of the IDEA it lands, never by \
the difficulty of the sentences it lands it in. If an advanced card could be made \
clearer without losing an ounce of its content, it is not yet finished.

Pitch the language, never the facts. Simplifying wording is the job; simplifying a claim \
until it is no longer true is not, and a beginner card is held to exactly the same standard \
of correctness as an advanced one.
"""
