"""Quizzes: sampling, MCQ grading, free-text grading, progression write-back.

ADR-0009 (shape, grading, prompt-injection defence), amended by ADR-0027 (entry
tier is trusted; `placement`-kind attempts are unlimited below-current-tier
practice that never touches progression).

Two calls to submit an attempt, deliberately (ADR-0009: "MCQ results are
returned immediately while the written answer is still being evaluated"):
`submit-mcq` grades deterministically and returns instantly; `submit-free-text`
is the one call in this whole API that blocks on an LLM response, and it is
also where progression (`UserTopicProgress`) actually gets written, once both
halves of the score are known.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from spoin.api.deps import SessionDep, UserDep
from spoin.api.routers.topics import ensure_unlock_latched
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
from spoin.domain.enums import Difficulty, QuestionKind, QuestionStatus, QuizKind
from spoin.domain.models import (
    Card,
    Question,
    QuizAttempt,
    QuizAttemptQuestion,
    Subtopic,
    UserQuestionSeen,
    UserTopicProgress,
)
from spoin.generation import get_content_generator
from spoin.generation.base import FreeTextGradeQuery

router = APIRouter(tags=["quiz"])


# --------------------------------------------------------------------- sampling --


async def _sample_questions(
    session: SessionDep,
    user_id: UUID,
    topic_id: UUID,
    difficulty: Difficulty,
    kind: QuestionKind,
    count: int,
) -> list[Question]:
    """Prefer questions this user hasn't seen; fall back to repeats if the bank
    is thin (task 0011's sampling decision) — never fail a quiz just because
    everything available has been asked before."""

    seen = select(UserQuestionSeen.question_id).where(UserQuestionSeen.user_id == user_id)
    rows = (
        await session.execute(
            select(Question)
            .join(Subtopic, Subtopic.id == Question.subtopic_id)
            .where(
                Subtopic.topic_id == topic_id,
                Question.difficulty == difficulty,
                Question.kind == kind,
                Question.status == QuestionStatus.ACTIVE,
            )
            # Unseen first (False sorts before True), random within each group.
            .order_by(Question.id.in_(seen).asc(), func.random())
            .limit(count)
        )
    ).scalars().all()
    return list(rows)


async def _mark_seen(session: SessionDep, user_id: UUID, question_ids: list[UUID]) -> None:
    if not question_ids:
        return
    stmt = (
        pg_insert(UserQuestionSeen)
        .values([{"user_id": user_id, "question_id": qid} for qid in question_ids])
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)


# ----------------------------------------------------------------------- start --


@router.post(
    "/topics/{topic_id}/quiz/start",
    response_model=QuizStartOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_quiz(
    topic_id: UUID, payload: QuizStartIn, session: SessionDep, user_id: UserDep
) -> QuizStartOut:
    settings = get_settings()
    difficulty = payload.difficulty

    progress, tier, _coverage, unlocked, _mastered = await ensure_unlock_latched(
        session, user_id, topic_id
    )
    if progress is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not subscribed to this topic")

    if difficulty.rank > tier.rank:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tier not reached yet")

    if difficulty.rank < tier.rank:
        # ADR-0027: below-current-tier practice. Unlocked at subscribe/entry
        # time (or by a later promotion past it) — `tier_unlocked` covers both,
        # since promotion never re-locks a tier the user already passed through.
        if not progress.tier_unlocked[difficulty.rank]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tier not unlocked yet")
        kind = QuizKind.PLACEMENT
    elif difficulty is Difficulty.ADVANCED:
        if not unlocked:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="Not enough advanced-tier coverage yet"
            )
        # content-model.md: mastered = tier_content_complete[advanced] AND
        # tier_quiz_passed[advanced]. Nothing else in the system writes
        # tier_content_complete yet (task 0010's gap) — this is the one place
        # advanced coverage actually gets checked, so latch it here too, the
        # same pattern `ensure_unlock_latched` already uses for tier_unlocked.
        if not progress.tier_content_complete[Difficulty.ADVANCED.rank]:
            complete = list(progress.tier_content_complete)
            complete[Difficulty.ADVANCED.rank] = True
            progress.tier_content_complete = complete
            await session.commit()
        kind = QuizKind.MASTERY
    else:
        if not unlocked:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tier not unlocked yet")
        kind = QuizKind.PROMOTION

    mcq_questions = await _sample_questions(
        session, user_id, topic_id, difficulty, QuestionKind.MCQ, settings.quiz_mcq_count
    )
    free_text_questions = await _sample_questions(
        session,
        user_id,
        topic_id,
        difficulty,
        QuestionKind.FREE_TEXT,
        settings.quiz_free_text_count,
    )
    if len(mcq_questions) < settings.quiz_mcq_count or not free_text_questions:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Not enough questions generated yet for this tier — check back soon",
        )
    free_text_question = free_text_questions[0]

    await _mark_seen(
        session, user_id, [q.id for q in mcq_questions] + [free_text_question.id]
    )

    attempt = QuizAttempt(
        user_id=user_id,
        topic_id=topic_id,
        difficulty=difficulty,
        kind=kind,
        started_at=datetime.now(UTC),
    )
    session.add(attempt)
    await session.flush()
    session.add_all(
        [
            QuizAttemptQuestion(attempt_id=attempt.id, question_id=q.id)
            for q in [*mcq_questions, free_text_question]
        ]
    )
    await session.commit()

    return QuizStartOut(
        attempt_id=attempt.id,
        topic_id=topic_id,
        difficulty=difficulty,
        kind=kind.value,
        mcq=[
            QuizMcqQuestionOut(question_id=q.id, stem=q.stem, options=q.options or [])
            for q in mcq_questions
        ],
        free_text=QuizFreeTextQuestionOut(
            question_id=free_text_question.id, stem=free_text_question.stem
        ),
    )


# ------------------------------------------------------------------- submit mcq --


async def _load_attempt(session: SessionDep, user_id: UUID, attempt_id: UUID) -> QuizAttempt:
    attempt = await session.get(QuizAttempt, attempt_id)
    # 404, not 403, for someone else's attempt -- don't confirm it exists.
    if attempt is None or attempt.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown quiz attempt")
    return attempt


@router.post("/quiz/attempts/{attempt_id}/submit-mcq", response_model=QuizSubmitMcqOut)
async def submit_mcq(
    attempt_id: UUID, payload: QuizSubmitMcqIn, session: SessionDep, user_id: UserDep
) -> QuizSubmitMcqOut:
    attempt = await _load_attempt(session, user_id, attempt_id)
    if attempt.submitted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="MCQ answers already submitted")

    attempt_questions = (
        await session.execute(
            select(QuizAttemptQuestion, Question)
            .join(Question, Question.id == QuizAttemptQuestion.question_id)
            .where(QuizAttemptQuestion.attempt_id == attempt_id, Question.kind == QuestionKind.MCQ)
        )
    ).all()
    by_question_id = {aq.question_id: (aq, q) for aq, q in attempt_questions}

    answers_by_question_id = {
        answer.question_id: answer.selected_index for answer in payload.answers
    }
    if set(answers_by_question_id) != set(by_question_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Answers must cover exactly this attempt's MCQ questions",
        )

    results: list[McqResultOut] = []
    correct_count = 0
    for question_id, (attempt_question, question) in by_question_id.items():
        selected = answers_by_question_id[question_id]
        correct = selected == question.correct_index
        correct_count += int(correct)
        attempt_question.user_answer = str(selected)
        attempt_question.correct = correct
        results.append(
            McqResultOut(
                question_id=question_id,
                correct=correct,
                correct_index=question.correct_index or 0,
                explanation=question.explanation or "",
            )
        )

    attempt.submitted_at = datetime.now(UTC)
    await session.commit()

    return QuizSubmitMcqOut(
        attempt_id=attempt_id,
        results=results,
        mcq_score=correct_count / len(by_question_id) if by_question_id else 0.0,
    )


# ------------------------------------------------------------- submit free text --

#: Words of 4+ letters, used by `_references_question` below.
_TOKEN_RE = re.compile(r"[a-zA-Z]{4,}")


def _tokens(text: str) -> set[str]:
    return {match.lower() for match in _TOKEN_RE.findall(text)}


def _references_question(justification: str, *contexts: str) -> bool:
    """Independent, code-level check that the grader's justification is
    actually about THIS question (ADR-0009's prompt-injection defence: the
    system prompt tells the model to grade the answer as data, but this
    re-checks the model's own output rather than trusting it outright).

    A cheap heuristic, not a second LLM call: any shared 4+-letter word
    between the justification and the question's own stem/reference-answer/
    submitted-answer is enough. A justification sharing NO vocabulary with any
    of them is a strong signal something went wrong (an injected instruction
    got echoed back, or a degenerate/templated response), so it is treated as
    untrustworthy rather than graded at face value.
    """

    justification_tokens = _tokens(justification)
    if not justification_tokens:
        return False
    context_tokens: set[str] = set()
    for context in contexts:
        context_tokens |= _tokens(context)
    return bool(justification_tokens & context_tokens)


async def _remediation_cards(
    session: SessionDep, question_ids: list[UUID]
) -> list[RemediationCardOut]:
    if not question_ids:
        return []
    rows = (
        await session.execute(
            select(Card.id, Card.title, Subtopic.title)
            .join(Question, Question.card_id == Card.id)
            .join(Subtopic, Subtopic.id == Card.subtopic_id)
            .where(Question.id.in_(question_ids))
        )
    ).all()
    seen_card_ids: set[UUID] = set()
    out: list[RemediationCardOut] = []
    for card_id, title, subtopic_title in rows:
        if card_id in seen_card_ids:
            continue
        seen_card_ids.add(card_id)
        out.append(RemediationCardOut(card_id=card_id, title=title, subtopic_title=subtopic_title))
    return out


@router.post("/quiz/attempts/{attempt_id}/submit-free-text", response_model=QuizSubmitFreeTextOut)
async def submit_free_text(
    attempt_id: UUID, payload: QuizSubmitFreeTextIn, session: SessionDep, user_id: UserDep
) -> QuizSubmitFreeTextOut:
    settings = get_settings()
    attempt = await _load_attempt(session, user_id, attempt_id)
    if attempt.submitted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Submit MCQ answers first")
    if attempt.graded_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Already graded")

    answer = payload.answer[: settings.quiz_free_text_answer_max_chars]

    # Per-user daily cap on LLM-graded submissions (overview.md: this is the
    # one cost axis that scales with USER behavior, not corpus size -- a
    # different quota story from the generation quota governor).
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    graded_today = await session.scalar(
        select(func.count())
        .select_from(QuizAttempt)
        .where(QuizAttempt.user_id == user_id, QuizAttempt.graded_at >= day_start)
    )
    if (graded_today or 0) >= settings.quiz_free_text_grades_per_user_per_day:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily quiz-grading limit reached, try again tomorrow",
        )

    row = (
        await session.execute(
            select(QuizAttemptQuestion, Question)
            .join(Question, Question.id == QuizAttemptQuestion.question_id)
            .where(
                QuizAttemptQuestion.attempt_id == attempt_id,
                Question.kind == QuestionKind.FREE_TEXT,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="No free-text question on this attempt"
        )
    attempt_question, question = row

    grade_result = await get_content_generator().grade_free_text(
        [
            FreeTextGradeQuery(
                index=0,
                stem=question.stem,
                rubric=question.rubric or "",
                reference_answer=question.reference_answer or "",
                user_answer=answer,
            )
        ]
    )
    if not grade_result.items:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Grading failed, try again")
    graded = grade_result.items[0]

    justification = graded.justification
    rubric_level = graded.rubric_level
    if not _references_question(
        justification, question.stem, question.reference_answer or "", answer
    ):
        rubric_level = 0
        justification = (
            f"[flagged: grader response did not clearly reference this question — "
            f"treated as level 0] {justification}"
        )

    free_text_correct = rubric_level >= settings.quiz_free_text_pass_level

    attempt_question.user_answer = answer
    attempt_question.correct = free_text_correct
    attempt_question.rubric_level = rubric_level
    attempt_question.justification = justification

    mcq_rows = (
        await session.execute(
            select(QuizAttemptQuestion.correct)
            .join(Question, Question.id == QuizAttemptQuestion.question_id)
            .where(QuizAttemptQuestion.attempt_id == attempt_id, Question.kind == QuestionKind.MCQ)
        )
    ).scalars().all()
    mcq_fraction = (sum(1 for c in mcq_rows if c) / len(mcq_rows)) if mcq_rows else 0.0
    free_text_fraction = rubric_level / 3
    score = (
        settings.quiz_mcq_weight * mcq_fraction
        + settings.quiz_free_text_weight * free_text_fraction
    )
    # Rounded before comparing against the pass mark: e.g. 0.7 + 0.3 * (1 / 3)
    # evaluates to 0.7999999999999999 in binary floating point, which would
    # fail an exact >= 0.80 threshold that the user genuinely earned.
    score = round(score, 6)
    passed = score >= settings.quiz_pass_threshold

    attempt.score = score
    attempt.passed = passed
    attempt.graded_at = datetime.now(UTC)

    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == attempt.topic_id
        )
    )
    progressed = False
    if progress is not None and passed and attempt.kind != QuizKind.PLACEMENT:
        passed_arr = list(progress.tier_quiz_passed)
        passed_arr[attempt.difficulty.rank] = True
        progress.tier_quiz_passed = passed_arr
        if attempt.kind == QuizKind.PROMOTION:
            next_tier = attempt.difficulty.next_tier()
            if next_tier is not None:
                progress.current_difficulty = next_tier
        elif attempt.kind == QuizKind.MASTERY and progress.mastered_at is None:
            progress.mastered_at = datetime.now(UTC)
        progressed = True

    remediation: list[RemediationCardOut] = []
    if not passed:
        wrong_question_ids = [
            aq.question_id
            for aq in (
                await session.execute(
                    select(QuizAttemptQuestion).where(
                        QuizAttemptQuestion.attempt_id == attempt_id,
                        QuizAttemptQuestion.correct.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        ]
        remediation = await _remediation_cards(session, wrong_question_ids)

    await session.commit()

    return QuizSubmitFreeTextOut(
        attempt_id=attempt_id,
        free_text=QuizFreeTextResultOut(
            question_id=question.id,
            rubric_level=rubric_level,
            correct=free_text_correct,
            justification=justification,
        ),
        score=score,
        passed=passed,
        remediation=remediation,
        progressed=progressed,
    )
