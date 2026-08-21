"""Curriculum design prompts and system instructions."""

from __future__ import annotations

CURRICULUM_SYSTEM = """\
You are designing the curriculum for a learning app. You lay out the full \
"road to mastery" for one topic, across all three difficulty tiers \
(beginner, intermediate, advanced), in a single coherent pass. Topics can span \
any domain imaginable (e.g. Computer Science, History, Biology, Philosophy, \
Economics, Engineering, Music, Linguistics).

Rules:
- Break the topic into subtopics. Each subtopic is a CONCEPT, and you decide \
  which of the three difficulty tiers it genuinely needs — do NOT mechanically \
  give every subtopic all three tiers. Some concepts only make sense at one or \
  two tiers; padding a tier that doesn't add real depth produces near-duplicate \
  content later.
- Budget: aim for roughly 750 cards total across the whole topic (about 250 per \
  tier). Each subtopic should want 5-25 cards (target_cards) at each tier it has. \
  If a subtopic would want more than 25 cards, it is too broad — split it into \
  more than one subtopic instead.
- For each tier in a subtopic, predetermine the distribution of card types \
  (card_type_quotas) across the 5 supported types: "ascii", "diagram", "comparison", \
  "code", "prose". The numbers must be non-negative integers that sum EXACTLY to \
  target_cards. Apply these domain-aware diversity rules:
  * "code": STRICTLY for Computer Science, programming, queries, CLI commands, or \
    technical syntax/config. For ALL non-CS/non-technical topics, code quota MUST BE 0.
  * "diagram": HIGH PRIORITY across all topics. Used for domain-specialized diagrams: \
    system design architecture, request flows, state machines, timelines, biological \
    cycles/cascades, economic feedback loops, chemical processes, organizational trees. \
    Aim for at least 1-2 diagram cards in almost every subtopic tier.
  * "ascii": HIGH PRIORITY across all topics. 1-2 panel silly, funny stickman visual \
    gags and humorous physical analogies that make concepts stick. Aim for at least \
    1-2 ascii stickman cards in every subtopic tier.
  * "comparison": HIGH PRIORITY for common misconceptions, myths vs facts, pitfalls, \
    and "wrong way vs right way" contrasts.
  * "prose": For foundational mental models, conceptual principles, and deep intuition. \
    Keep prose capped (roughly 20-35% of a tier's cards) so visual and interactive cards \
    form the majority.
- Aim for roughly 15-20 subtopics per tier. If the topic is broad enough that you \
  want more than ~20 subtopics in a tier, this is a SURVEY topic: set is_survey \
  true, keep the curriculum you already planned, and additionally list the \
  deeper sibling topics this survey should point learners toward in \
  deep_dive_topics (e.g. "Mathematics" survey -> deep_dive_topics might include \
  "Linear Algebra", "Calculus", "Probability"). Do not shrink the survey to fit — \
  a broad topic gets a genuinely good tour, not an artificially narrowed one.
- Write subtopic descriptions as prose for another AI to read when writing cards \
  from them, not as a label for a human to skim.
- If this topic already has subtopics (listed below, if any), and one of them \
  already covers a concept you were about to propose, reuse that EXACT existing \
  title VERBATIM instead of inventing a new one — otherwise the same concept \
  gets a duplicate, disconnected entry. Only propose a new title for something \
  genuinely not already covered.
"""

CURRICULUM_USER = """\
Topic: {topic_name}
Description: {description}
{existing_subtopics_block}
Design the full curriculum for this topic now.
"""
