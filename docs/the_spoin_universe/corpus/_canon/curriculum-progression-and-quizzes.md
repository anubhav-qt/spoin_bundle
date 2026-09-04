---
title: Curriculum Decomposition, Quiz-Gated Progression, and Mastery
kind: spoin_canon
source: Spoin ADR-0007, ADR-0009, and content-model.md
topic_tags:
  - spoin canon
  - curriculum
  - progression
  - quizzes
  - mastery
  - subtopics
---

## Curriculum Structure: Topics, Subtopics, and Card Budgets

In Spoin, learning content does not float loose inside an unstructured topic. ADR-0007 establishes that each topic is decomposed **once** by an architectural curriculum pass into structured **subtopics** distributed across three difficulty tiers (`beginner`, `intermediate`, `advanced`). Generation calls strictly target specific subtopics.

The curriculum model is governed by completability constraints:
- **Topic Card Budget:** A complete topic is capped at approximately **750 total cards** across all three tiers (~250 cards per tier, corresponding to 5–10 study sessions of ~30 cards per session).
- **Subtopic Sizing:** A subtopic targets between **5 and 25 cards**. Coverage is measured against `min_cards` (the minimum threshold required for completeness), rather than aspirational `target_cards`.
- **Self-Correcting Decomposition Rules:**
  - If a subtopic requires $> 25$ cards to cover, it is too broad and must be decomposed into narrower subtopics.
  - If a tier requires $> 20$ subtopics, the subject is too vast for a single course. It transitions into a **Survey / Tour Topic** (e.g. "Mathematics" or "Backend Engineering"). The survey covers broad foundational concepts and emits `deep_dive` topic edges pointing to narrower specialized topics (e.g. Linear Algebra, Calculus, PostgreSQL).
- **Flat Topic Graph:** Topic edges are flat directed links (`topic_edge(from_id, to_id, kind='deep_dive')`), never deeply nested recursive trees. This seeds the topic catalog cleanly without unbounded nesting complexity.

## Quiz-Gated Progression and Latched Unlocks

Progression through a technical topic is earned through objective demonstration of comprehension. ADR-0009 and ADR-0027 establish the progression lifecycle:

1. **Self-Selected Entry Tier:** The user chooses their starting tier (`beginner`, `intermediate`, or `advanced`) upon subscribing to a topic. The entry tier is trusted; no gate blocks initial access. Quizzes at or below the entry tier remain open for unlimited practice retries without affecting progression.
2. **Coverage-Gated Unlock:** To unlock the promotion quiz for the next tier, the user must have read **at least 80% of cards in every subtopic** of their current tier.
3. **The Unlock is Latched:** Once a user reaches 80% card coverage across all subtopics in a tier, the quiz unlock status is **latched permanently** on `user_topic_progress`. It is never dynamically recomputed. If background generation subsequently adds 10 new cards to a subtopic, the user's earned quiz unlock is not revoked.
4. **Promotion:** Passing the tier quiz with a score of $\ge 80\%$ promotes the user to the next difficulty tier, updating their feed serving distribution.

## Quiz Structure: Mechanics and Question Derivation

Tier quizzes combine deterministic scoring with open-ended conceptual evaluation:
- **Question Composition:** Each quiz contains **9 Multiple-Choice Questions (MCQ)** and **1 Free-Text Question**.
- **Grading Weight:** MCQs are scored deterministically by the system; the free-text answer is graded by an LLM against an explicit, multi-point rubric. The final grade is weighted **70% MCQ / 30% Free-Text**, with an **80% passing threshold**.
- **Questions are Generated Directly from Cards:**
  - Every quiz question is derived from a specific, existing card and stores `question.card_id`. Questions are never written from the topic in the abstract.
  - This constraint guarantees that users are tested solely on facts explicitly taught within the corpus, eliminating hallucinated trivia.
  - When a user answers incorrectly, the quiz results screen links directly back to the specific card that teaches the missing concept, transforming failure into targeted remediation.
- **Discovery via Untested Cards:** Because users unlock quizzes at 80% coverage, a quiz may test a card the user did not encounter in the feed. The results screen explicitly identifies these questions, allowing the quiz to serve as an active discovery mechanism.

## Mastery State and Revisit Mode

When a user passes the advanced tier quiz, the topic achieves **Mastery**:
- `mastered = tier_content_complete[advanced] AND tier_quiz_passed[advanced]`
- **Mastery is Permanent:** Once achieved, mastery is permanently recorded on the user profile. The user may retake the mastery quiz for practice with fresh questions at any time, but a subsequent failing score never revokes earned mastery.
- **Revisit Mode:** Following mastery, the topic enters Revisit Mode. Seen cards are served periodically to reinforce retention, but the user interface honestly displays the completed state rather than disguising reviewed cards as unread content.
