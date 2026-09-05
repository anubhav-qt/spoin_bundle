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
TIER_LANGUAGE = """\

READING LEVEL:
The source material is written at reference density for every difficulty tier. Pitch \
the LANGUAGE at the requested tier — a beginner card explains a term the moment it \
uses one, prefers a short sentence, and reaches for a concrete example; an advanced \
card can assume the vocabulary and spend its words on the substance instead.

Pitch the language, never the facts. Simplifying wording is the job; simplifying a \
claim until it is no longer true is not, and a beginner card is held to exactly the \
same standard of correctness as an advanced one.
"""
