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
    CardDraft,
    ContentGenerator,
    CurriculumDraft,
    DifficultyVerdict,
    QuestionDraft,
    SubtopicGroupDraft,
    SubtopicTierDraft,
    TopicMatchVerdict,
)


def _stable_index(*parts: str, modulo: int) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:4], "big") % modulo


class FakeContentGenerator(ContentGenerator):
    #: Deliberately failing one item per batch when asked. Partial failure is the
    #: normal case under ADR-0005, so the happy path should not be the only one
    #: that ever gets exercised.
    def __init__(self, *, fail_one_per_batch: bool = False) -> None:
        self._fail_one = fail_one_per_batch

    async def generate_curriculum(
        self,
        topic_name: str,
        description: str,
        related_subtopic_hints: list[str] | None = None,
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
        if related_subtopic_hints:
            # Deterministically fold hints in as their own group, so a test can
            # assert the pipeline actually threaded them through rather than the
            # generator silently ignoring them.
            groups.append(
                SubtopicGroupDraft(
                    title=f"{topic_name}: from related topic",
                    tiers=[
                        SubtopicTierDraft(
                            difficulty=Difficulty.BEGINNER,
                            description="Adapted from: " + "; ".join(related_subtopic_hints),
                            target_cards=5,
                        )
                    ],
                    position=len(groups),
                )
            )
        return CurriculumDraft(subtopics=groups)

    async def judge_topic_match(
        self,
        candidate_name: str,
        candidate_description: str,
        matched_topic_name: str,
        matched_subtopic_titles: list[str],
    ) -> TopicMatchVerdict:
        same_topic = _stable_index(candidate_name, matched_topic_name, modulo=2) == 0
        return TopicMatchVerdict(
            same_topic=same_topic,
            relevant_subtopic_titles=matched_subtopic_titles[:2],
        )

    async def generate_cards(
        self,
        *,
        topic_name: str,
        subtopic_title: str,
        subtopic_description: str,
        difficulty: Difficulty,
        count: int,
        existing_titles: list[str],
    ) -> BatchResult[CardDraft]:
        items = [
            CardDraft(
                title=f"{subtopic_title} — note {n + 1}"[:120],
                canonical_title=f"{subtopic_title}: note {n + 1}"[:160],
                summary=f"A placeholder hook for {subtopic_title} at {difficulty.value} level.",
                body=(
                    f"# {subtopic_title}\n\n"
                    f"Placeholder body {n + 1} for **{topic_name}** "
                    f"({difficulty.value}).\n\n{subtopic_description}\n"
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

    async def judge_difficulty(self, bodies: list[str]) -> BatchResult[DifficultyVerdict]:
        tiers = list(Difficulty)
        return BatchResult(
            items=[
                DifficultyVerdict(
                    index=index,
                    difficulty=tiers[_stable_index(body, modulo=len(tiers))],
                    factually_sound=True,
                )
                for index, body in enumerate(bodies)
            ]
        )

    async def generate_questions(
        self, cards: list[tuple[str, str]], difficulty: Difficulty
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
