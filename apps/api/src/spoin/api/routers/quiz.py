"""Quizzes: HTTP surface only.

ADR-0009 (shape, grading, prompt-injection defence), amended by ADR-0027 (entry
tier is trusted; `placement`-kind attempts are unlimited below-current-tier
practice that never touches progression).

Two calls to submit an attempt, deliberately (ADR-0009: "MCQ results are
returned immediately while the written answer is still being evaluated"):
`submit-mcq` grades deterministically and returns instantly; `submit-free-text`
is the one call in this whole API that blocks on an LLM response, and it is
also where progression (`UserTopicProgress`) actually gets written, once both
halves of the score are known.

Everything below the transport layer lives in `spoin.quiz` — sampling, the
attempt lifecycle, scoring and the tier state machine in `quiz/service.py`, the
scoring arithmetic and injection guard in `quiz/grading.py`. These handlers
parse, delegate, and serialize.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import (
    McqResultOut,
    QuizFreeTextQuestionOut,
    QuizFreeTextResultOut,
    QuizMcqQuestionOut,
    QuizStartIn,
    QuizStartOut,
    QuizSubmitFreeTextIn,
    QuizSubmitFreeTextOut,
    QuizSubmitMcqIn,
    QuizSubmitMcqOut,
    RemediationCardOut,
)
from spoin.core.config import get_settings
from spoin.generation import get_content_generator
from spoin.quiz.service import QuizService
from spoin.topics.service import TopicsService

router = APIRouter(tags=["quiz"])


def _service(session: SessionDep) -> QuizService:
    return QuizService(session, get_settings(), get_content_generator())


@router.post(
    "/topics/{topic_id}/quiz/start",
    response_model=QuizStartOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_quiz(
    topic_id: UUID, payload: QuizStartIn, session: SessionDep, user_id: UserDep
) -> QuizStartOut:
    # Tier state is read and latched by the topics service, then handed to the
    # quiz service. Quiz depends on topics' *service*, never on its router.
    progress, tier, _coverage, unlocked, _mastered = await TopicsService(
        session, get_settings()
    ).ensure_unlock_latched(user_id, topic_id)
    if progress is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not subscribed to this topic")

    started = await _service(session).start(
        user_id,
        topic_id,
        payload.difficulty,
        progress=progress,
        tier=tier,
        unlocked=unlocked,
    )

    return QuizStartOut(
        attempt_id=started.attempt_id,
        topic_id=topic_id,
        difficulty=started.difficulty,
        kind=started.kind.value,
        mcq=[
            QuizMcqQuestionOut(question_id=q.id, stem=q.stem, options=q.options or [])
            for q in started.mcq_questions
        ],
        free_text=QuizFreeTextQuestionOut(
            question_id=started.free_text_question.id,
            stem=started.free_text_question.stem,
        ),
    )


@router.post("/quiz/attempts/{attempt_id}/submit-mcq", response_model=QuizSubmitMcqOut)
async def submit_mcq(
    attempt_id: UUID, payload: QuizSubmitMcqIn, session: SessionDep, user_id: UserDep
) -> QuizSubmitMcqOut:
    graded = await _service(session).submit_mcq(
        user_id,
        attempt_id,
        {answer.question_id: answer.selected_index for answer in payload.answers},
    )

    return QuizSubmitMcqOut(
        attempt_id=attempt_id,
        results=[
            McqResultOut(
                question_id=r.question_id,
                correct=r.correct,
                correct_index=r.correct_index,
                explanation=r.explanation,
            )
            for r in graded.results
        ],
        mcq_score=graded.mcq_score,
    )


@router.post("/quiz/attempts/{attempt_id}/submit-free-text", response_model=QuizSubmitFreeTextOut)
async def submit_free_text(
    attempt_id: UUID, payload: QuizSubmitFreeTextIn, session: SessionDep, user_id: UserDep
) -> QuizSubmitFreeTextOut:
    graded = await _service(session).submit_free_text(user_id, attempt_id, payload.answer)

    return QuizSubmitFreeTextOut(
        attempt_id=attempt_id,
        free_text=QuizFreeTextResultOut(
            question_id=graded.question_id,
            rubric_level=graded.rubric_level,
            correct=graded.free_text_correct,
            justification=graded.justification,
        ),
        score=graded.score,
        passed=graded.passed,
        remediation=[
            RemediationCardOut(
                card_id=r.card_id, title=r.title, subtopic_title=r.subtopic_title
            )
            for r in graded.remediation
        ],
        progressed=graded.progressed,
    )
