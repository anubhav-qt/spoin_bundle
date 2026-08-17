"""Deterministic in-memory `ContentGenerator`.

This is the default everywhere except production. Tests and local development
never call a real model, never burn quota, and run in milliseconds — which is what
makes the "clone to running app in under 10 minutes" promise hold on a machine
with no API key.

Deterministic on purpose: same inputs, same output, so a test that depends on
generated text is not flaky.
"""

from __future__ import annotations

import hashlib

from spoin.domain.enums import Difficulty
from spoin.generation.base import (
    BatchResult,
    CardCorrectionQuery,
    CardCorrectionResult,
    CardDraft,
    CardVerificationQuery,
    CardVerificationResult,
    ContentGenerator,
    CurriculumDraft,
    FreeTextGradeQuery,
    FreeTextGradeResult,
    QuestionDraft,
    SubtopicGroupDraft,
    SubtopicTierDraft,
    TopicMatchQuery,
    TopicMatchResult,
)


def _stable_index(*parts: str, modulo: int) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:4], "big") % modulo


#: Distinct filler angles so fake card bodies in the same subtopic/difficulty
#: don't collide under the deterministic HashEmbedder used in tests (it's a
#: crude bag-of-words -- see embeddings/__init__.py -- so near-identical
#: placeholder text WOULD trip the near-duplicate gate on real generated
#: content, not just on genuinely-repetitive ones). Real generated prose
#: doesn't need this; this is purely a test-fixture concern.
_FAKE_ANGLES = [
    "how it behaves under load",
    "why it is designed this way",
    "a common mistake beginners make with it",
    "how to reason about its edge cases",
    "the tradeoff it makes against simpler alternatives",
    "how to explain it to someone new",
    "the mental model that makes it click",
    "how it composes with related concepts",
    "when not to reach for it",
    "a worked example most people skip",
]


class FakeContentGenerator(ContentGenerator):
    #: Deliberately failing one item per batch when asked. Partial failure is the
    #: normal case under ADR-0005, so the happy path should not be the only one
    #: that ever gets exercised.
    def __init__(
        self, *, fail_one_per_batch: bool = False, reject_one_per_verify_batch: bool = False
    ) -> None:
        self._fail_one = fail_one_per_batch
        #: Deliberately rejecting one item per `verify_cards` batch when asked
        #: -- ADR-0030's pass 2 CAN reject, and the happy path (accept
        #: everything) shouldn't be the only path a test ever exercises.
        self._reject_one = reject_one_per_verify_batch

    async def generate_curriculum(
        self,
        topic_name: str,
        description: str,
        existing_subtopics: list[str] | None = None,
    ) -> CurriculumDraft:
        groups = [
            SubtopicGroupDraft(
                title=f"{topic_name}: part {n + 1}",
                tiers=[
                    SubtopicTierDraft(
                        difficulty=difficulty,
                        description=f"Placeholder curriculum slot {n + 1} for {topic_name}.",
                        target_cards=10,
                    )
                    for difficulty in Difficulty
                ],
                position=n,
            )
            for n in range(3)
        ]
        if existing_subtopics:
            # Deterministically "decide" the first already-existing subtopic is
            # the same as its own first group, reusing the EXACT title verbatim —
            # simulates the real prevention behavior (generate_curriculum's
            # docstring) so a test can assert the pipeline's persistence step
            # actually reuses that row instead of forking a duplicate.
            reused_title = existing_subtopics[0].split(" :: ", 1)[0]
            groups[0].title = reused_title
        return CurriculumDraft(subtopics=groups)

    async def match_topics(self, queries: list[TopicMatchQuery]) -> BatchResult[TopicMatchResult]:
        # Deterministic stand-in for an LLM opinion: the highest-similarity
        # candidate "matches" above a fixed cutoff. This is the FAKE's own
        # simulated judgment, not a system threshold — ADR-0025 removed those.
        items = []
        for query in queries:
            best = max(query.candidates, key=lambda c: c.similarity, default=None)
            matched = best.topic_id if best is not None and best.similarity >= 0.9 else None
            items.append(
                TopicMatchResult(request_index=query.request_index, matched_topic_id=matched)
            )
        return BatchResult(items=items)

    async def generate_cards(
        self,
        *,
        topic_name: str,
        subtopic_title: str,
        subtopic_description: str,
        difficulty: Difficulty,
        count: int,
        existing_titles: list[str],
        builds_on: list[str],
        difficulty_examples: dict[Difficulty, list[str]],
        avoid_bodies: list[str],
        rejection_feedback: list[tuple[str, str]],
    ) -> BatchResult[CardDraft]:
        builds_on_note = f" Builds on {len(builds_on)} lower-tier card(s)." if builds_on else ""
        items = [
            CardDraft(
                title=f"{subtopic_title} — note {n + 1}"[:120],
                canonical_title=f"{subtopic_title}: note {n + 1}"[:160],
                summary=f"A placeholder hook for {subtopic_title} at {difficulty.value} level.",
                body=(
                    f"# {subtopic_title}\n\n"
                    f"Card {n + 1} on **{topic_name}** ({difficulty.value}): "
                    f"{_FAKE_ANGLES[n % len(_FAKE_ANGLES)]}.{builds_on_note}\n"
                ),
                difficulty=difficulty,
            )
            for n in range(count)
        ]
        failures = []
        if self._fail_one and items:
            items.pop()
            failures.append("simulated malformed item")
        return BatchResult(items=items, failures=failures)

    async def correct_cards(
        self,
        queries: list[CardCorrectionQuery],
        *,
        difficulty_examples: dict[Difficulty, list[str]],
    ) -> BatchResult[CardCorrectionResult]:
        # Deterministic pass-through: the fake never finds anything to fix.
        # Correction-behavior itself is exercised by tests that construct their
        # own generator subclass or stub, not by this default.
        return BatchResult(
            items=[
                CardCorrectionResult(
                    index=query.index,
                    title=query.title,
                    canonical_title=query.canonical_title,
                    summary=query.summary,
                    body=query.body,
                    was_edited=False,
                )
                for query in queries
            ]
        )

    async def verify_cards(
        self,
        queries: list[CardVerificationQuery],
        *,
        difficulty_examples: dict[Difficulty, list[str]],
    ) -> BatchResult[CardVerificationResult]:
        items = [
            CardVerificationResult(
                index=query.index,
                accepted=True,
                confirmed_difficulty=query.requested_difficulty,
            )
            for query in queries
        ]
        if self._reject_one and items:
            first = items[0]
            items[0] = CardVerificationResult(
                index=first.index,
                accepted=False,
                confirmed_difficulty=first.confirmed_difficulty,
                reason="simulated verification rejection",
            )
        return BatchResult(items=items)

    async def generate_questions(
        self,
        cards: list[tuple[str, str]],
        difficulty: Difficulty,
        *,
        existing_stems: list[str],
        is_backfill: bool,
    ) -> BatchResult[QuestionDraft]:
        items: list[QuestionDraft] = []
        for index, (title, _body) in enumerate(cards):
            if index == len(cards) - 1:
                # 9 MCQ + 1 free text (ADR-0009).
                items.append(
                    QuestionDraft(
                        card_index=index,
                        stem=f"In your own words, explain {title}.",
                        rubric="0 none / 1 surface / 2 solid / 3 deep",
                        reference_answer=f"A correct account of {title}.",
                    )
                )
            else:
                items.append(
                    QuestionDraft(
                        card_index=index,
                        stem=f"Which statement about {title} is correct?",
                        options=[f"Option {n}" for n in range(4)],
                        correct_index=_stable_index(title, modulo=4),
                        explanation=f"See the card '{title}'.",
                    )
                )
        return BatchResult(items=items)

    async def grade_free_text(
        self, items: list[FreeTextGradeQuery]
    ) -> BatchResult[FreeTextGradeResult]:
        # Deterministic stand-in for judgment: length of the (stripped) answer
        # is a stable, inspectable proxy for "did they write something real,"
        # which is all a fake grader needs to be useful in tests — an empty or
        # near-empty answer always grades 0, never a coincidence of hashing.
        results = []
        for item in items:
            answer = item.user_answer.strip()
            if not answer:
                level = 0
            else:
                level = 1 + _stable_index(item.stem, answer, modulo=3)
            results.append(
                FreeTextGradeResult(
                    index=item.index,
                    rubric_level=level,
                    justification=(
                        f"Placeholder grade referencing '{item.stem[:40]}': "
                        f"answer length {len(answer)} chars."
                    ),
                )
            )
        return BatchResult(items=results)
