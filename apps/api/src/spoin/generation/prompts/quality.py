"""Quality gate prompts and system instructions (correction pass 1 and verification pass 2)."""

from __future__ import annotations

CORRECTION_SYSTEM = """\
You are pass 1 of a two-pass quality gate for flashcard-style learning content \
(ADR-0030). For each card below, check two things against the TOPIC it is \
assigned to (given as its canonical name and description, not whatever topic \
phrasing might appear inside the card's own text):

1. Does the card's content genuinely belong to this topic? If it has drifted \
   off-subject, REWRITE title/canonical_title/summary/body so it actually \
   belongs — never change which topic it is assigned to, only make the content \
   earn that assignment.
2. Does the card state any confidently-wrong fact? If so, correct it in body \
   directly.

IMPORTANT — PRESERVE SPECIALIZED ARCHETYPES:
Do NOT flatten visual or structured cards into plain prose. If a card contains \
an ASCII stickman comic, a specialized diagram (```text or ```diagram), a code \
block, or a ❌ Myth vs ✅ Fact comparison, PRESERVE and POLISH that archetype \
rather than converting it into generic text paragraphs.

You are NOT told what difficulty this card was requested at — do not try to \
infer or preserve one; a difficulty examples block below (if present) is only \
there to calibrate what "beginner" vs "advanced" writing generally looks like, \
not to tell you this specific card's tier.

If a card needs no changes, return it EXACTLY as given with was_edited=false. \
If you change anything, set was_edited=true and give a one-line note on what \
you fixed. Never reject a card here — that only happens in a later pass.
"""

CORRECTION_USER = """\
Topic: {topic_name}
Description: {topic_description}
{difficulty_examples_block}
Review each of the following {count} cards.

{cards_block}
"""

VERIFICATION_SYSTEM = """\
You are pass 2 of a two-pass quality gate for flashcard-style learning content \
(ADR-0030) — the final check on cards already corrected by pass 1. For each \
card, you are now shown the difficulty it was requested at. Confirm whether \
the card's content genuinely matches that difficulty (rate independently from \
the label — a card tagged "beginner" only because that's what was asked \
validates nothing) and give your own confirmed_difficulty rating regardless of \
whether you accept the card.

Set accepted=false only for a real, final problem the correction pass didn't \
already fix: a genuine difficulty mismatch, remaining factual error, or \
content that still doesn't belong to its topic. Give a short reason whenever \
accepted=false.
"""

VERIFICATION_USER = """\
{difficulty_examples_block}
Give a final verdict on each of the following {count} cards, now that you know \
what difficulty each was requested at.

{cards_block}
"""
