"""Load a small hand-written question bank for local quiz testing.

`python -m spoin.seed_quiz`

The real question bank is generated from cards (ADR-0009's `card -> question`
pipeline, task 0012) and isn't wired up yet, so `start_quiz` 409s against
`seed.py`'s fixture corpus alone -- there are zero `Question` rows. This
script exists purely so the quiz UI has something to run against locally: it
writes MCQ + free-text questions for the kubernetes topic's beginner tier
(`fixtures/quiz_bank.json`), one per card plus a couple of free-text
questions, matching `quiz_mcq_count`/`quiz_free_text_count`
(`core/config.py`). Not a substitute for the generator -- see task 0012.

Idempotent, same as seed.py: matched by (subtopic, stem), safe to re-run.

Run after `seed.py` (assumes the kubernetes topic and its cards already exist).
"""

from __future__ import annotations

import asyncio
import json
from importlib import resources
from typing import Any

from sqlalchemy import select

from spoin.core.db import session_scope
from spoin.domain.enums import Difficulty, QuestionKind, QuestionStatus
from spoin.domain.models import Card, Question, Subtopic, Topic


def load_quiz_bank() -> dict[str, Any]:
    source = resources.files("spoin.fixtures").joinpath("quiz_bank.json")
    data: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    return data


async def seed_quiz() -> None:
    bank = load_quiz_bank()

    async with session_scope() as session:
        for topic_entry in bank["topics"]:
            topic = await session.scalar(select(Topic).where(Topic.slug == topic_entry["slug"]))
            if topic is None:
                raise RuntimeError(
                    f"topic {topic_entry['slug']!r} not found -- run `python -m spoin.seed` first"
                )

            for subtopic_entry in topic_entry["subtopics"]:
                subtopic = await session.scalar(
                    select(Subtopic).where(
                        Subtopic.topic_id == topic.id,
                        Subtopic.title == subtopic_entry["title"],
                        Subtopic.difficulty == Difficulty(subtopic_entry["difficulty"]),
                    )
                )
                if subtopic is None:
                    raise RuntimeError(
                        f"subtopic {subtopic_entry['title']!r} not found under "
                        f"{topic_entry['slug']!r} -- run `python -m spoin.seed` first"
                    )

                for question_entry in subtopic_entry["questions"]:
                    card = await session.scalar(
                        select(Card).where(
                            Card.subtopic_id == subtopic.id, Card.title == question_entry["card_title"]
                        )
                    )
                    if card is None:
                        raise RuntimeError(
                            f"card {question_entry['card_title']!r} not found under "
                            f"{subtopic_entry['title']!r}"
                        )

                    existing = await session.scalar(
                        select(Question).where(
                            Question.subtopic_id == subtopic.id, Question.stem == question_entry["stem"]
                        )
                    )
                    if existing is not None:
                        continue

                    kind = QuestionKind(question_entry["kind"])
                    session.add(
                        Question(
                            subtopic_id=subtopic.id,
                            card_id=card.id,
                            difficulty=subtopic.difficulty,
                            kind=kind,
                            stem=question_entry["stem"],
                            options=question_entry.get("options"),
                            correct_index=question_entry.get("correct_index"),
                            rubric=question_entry.get("rubric"),
                            reference_answer=question_entry.get("reference_answer"),
                            explanation=question_entry.get("explanation"),
                            status=QuestionStatus.ACTIVE,
                        )
                    )

        await session.flush()

    print("seeded quiz_bank.json")


def main() -> None:
    asyncio.run(seed_quiz())


if __name__ == "__main__":
    main()
