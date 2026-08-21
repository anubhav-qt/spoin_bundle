"""Quiz lifecycle: sampling, attempt creation, grading, progression write-back.

Extracted from `api/routers/quiz.py`, which held all of it inline — 20 SQL
statements, a direct LLM call, the weighted scoring formula and the whole tier
progression state machine, spread across three handlers of which one was 148
lines. The progression rules in particular (promotion advances
`current_difficulty`, mastery latches `mastered_at`, placement attempts touch
neither) are domain rules that belong somewhere a worker or a future admin path
could also reach, not somewhere only an HTTP request can.

**On `HTTPException` in a service.** Kept deliberately, matching `NotesService`,
rather than introducing a domain-exception hierarchy plus a mapping layer. The
status codes here are part of the API contract the client already depends on
(403 tier-not-reached, 409 already-graded, 429 daily cap), and inventing
`QuizTierLockedError` only to translate it back into the same 403 one layer up
adds a file and a lookup table without changing behaviour. If a non-HTTP caller
ever needs these, that is the moment to introduce the hierarchy.

Serving-layer note: `submit_free_text` is the one path in this service that
calls an LLM, exactly as ADR-0009 intends. Nothing here is on the feed read
path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
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
from spoin.generation.base import ContentGenerator, FreeTextGradeQuery
from spoin.quiz.grading import combined_score, references_question


@dataclass(frozen=True)
class StartedQuiz:
    attempt_id: UUID
    difficulty: Difficulty
    kind: QuizKind
    mcq_questions: list[Question]
    free_text_question: Question


@dataclass(frozen=True)
class McqOutcome:
    question_id: UUID
    correct: bool
    correct_index: int
    explanation: str


@dataclass(frozen=True)
class McqGraded:
    results: list[McqOutcome]
    mcq_score: float


@dataclass(frozen=True)
class RemediationCard:
    card_id: UUID
    title: str
    subtopic_title: str


@dataclass(frozen=True)
class FreeTextGraded:
    question_id: UUID
    rubric_level: int
    free_text_correct: bool
    justification: str
    score: float
    passed: bool
    progressed: bool
    remediation: list[RemediationCard]


class QuizService:
    """One session, one settings object, one generator — passed in rather than
    fetched from module-level singletons, so a test can hand it a
    `FakeContentGenerator` without patching anything global."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        generator: ContentGenerator,
    ) -> None:
        self._session = session
        self._settings = settings
        self._generator = generator

    # -- sampling ------------------------------------------------------------

    async def _sample_questions(
        self,
        user_id: UUID,
        topic_id: UUID,
        difficulty: Difficulty,
        kind: QuestionKind,
        count: int,
    ) -> list[Question]:
        """Prefer questions this user hasn't seen; fall back to repeats if the
        bank is thin (task 0011's sampling decision) — never fail a quiz just
        because everything available has been asked before."""

        seen = select(UserQuestionSeen.question_id).where(UserQuestionSeen.user_id == user_id)
        rows = (
            await self._session.execute(
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

    async def _mark_seen(self, user_id: UUID, question_ids: list[UUID]) -> None:
        if not question_ids:
            return
        await self._session.execute(
            pg_insert(UserQuestionSeen)
            .values([{"user_id": user_id, "question_id": qid} for qid in question_ids])
            .on_conflict_do_nothing()
        )

    # -- start ---------------------------------------------------------------

    async def start(
        self,
        user_id: UUID,
        topic_id: UUID,
        difficulty: Difficulty,
        *,
        progress: UserTopicProgress,
        tier: Difficulty,
        unlocked: bool,
    ) -> StartedQuiz:
        """Gate, sample, and open an attempt.

        `progress`/`tier`/`unlocked` are passed in rather than recomputed:
        they come from `ensure_unlock_latched`, which lives in the topics
        module and also latches state as a side effect. Calling it from here
        would make quiz depend on topics for something the caller already had.
        """

        settings = self._settings
        kind = await self._resolve_kind(difficulty, progress, tier, unlocked=unlocked)

        mcq_questions = await self._sample_questions(
            user_id, topic_id, difficulty, QuestionKind.MCQ, settings.quiz_mcq_count
        )
        free_text_questions = await self._sample_questions(
            user_id, topic_id, difficulty, QuestionKind.FREE_TEXT, settings.quiz_free_text_count
        )
        if len(mcq_questions) < settings.quiz_mcq_count or not free_text_questions:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Not enough questions generated yet for this tier — check back soon",
            )
        free_text_question = free_text_questions[0]

        await self._mark_seen(user_id, [q.id for q in mcq_questions] + [free_text_question.id])

        attempt = QuizAttempt(
            user_id=user_id,
            topic_id=topic_id,
            difficulty=difficulty,
            kind=kind,
            started_at=datetime.now(UTC),
        )
        self._session.add(attempt)
        await self._session.flush()
        self._session.add_all(
            [
                QuizAttemptQuestion(attempt_id=attempt.id, question_id=q.id)
                for q in [*mcq_questions, free_text_question]
            ]
        )
        await self._session.commit()

        return StartedQuiz(
            attempt_id=attempt.id,
            difficulty=difficulty,
            kind=kind,
            mcq_questions=mcq_questions,
            free_text_question=free_text_question,
        )

    async def _resolve_kind(
        self,
        difficulty: Difficulty,
        progress: UserTopicProgress,
        tier: Difficulty,
        *,
        unlocked: bool,
    ) -> QuizKind:
        """Which of the three attempt kinds this request is, or a 403."""

        if difficulty.rank > tier.rank:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tier not reached yet")

        if difficulty.rank < tier.rank:
            # ADR-0027: below-current-tier practice. Unlocked at subscribe/entry
            # time (or by a later promotion past it) — `tier_unlocked` covers
            # both, since promotion never re-locks a tier already passed through.
            if not progress.tier_unlocked[difficulty.rank]:
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tier not unlocked yet")
            return QuizKind.PLACEMENT

        if difficulty is Difficulty.ADVANCED:
            if not unlocked:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, detail="Not enough advanced-tier coverage yet"
                )
            # content-model.md: mastered = tier_content_complete[advanced] AND
            # tier_quiz_passed[advanced]. Nothing else in the system writes
            # tier_content_complete yet (task 0010's gap) — this is the one
            # place advanced coverage actually gets checked, so latch it here,
            # the same pattern `ensure_unlock_latched` uses for tier_unlocked.
            if not progress.tier_content_complete[Difficulty.ADVANCED.rank]:
                complete = list(progress.tier_content_complete)
                complete[Difficulty.ADVANCED.rank] = True
                progress.tier_content_complete = complete
                await self._session.commit()
            return QuizKind.MASTERY

        if not unlocked:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tier not unlocked yet")
        return QuizKind.PROMOTION

    # -- attempts ------------------------------------------------------------

    async def load_attempt(self, user_id: UUID, attempt_id: UUID) -> QuizAttempt:
        attempt = await self._session.get(QuizAttempt, attempt_id)
        # 404, not 403, for someone else's attempt -- don't confirm it exists.
        if attempt is None or attempt.user_id != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown quiz attempt")
        return attempt

    async def submit_mcq(
        self, user_id: UUID, attempt_id: UUID, answers: dict[UUID, int]
    ) -> McqGraded:
        attempt = await self.load_attempt(user_id, attempt_id)
        if attempt.submitted_at is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="MCQ answers already submitted")

        rows = (
            await self._session.execute(
                select(QuizAttemptQuestion, Question)
                .join(Question, Question.id == QuizAttemptQuestion.question_id)
                .where(
                    QuizAttemptQuestion.attempt_id == attempt_id,
                    Question.kind == QuestionKind.MCQ,
                )
            )
        ).all()
        by_question_id = {aq.question_id: (aq, q) for aq, q in rows}

        if set(answers) != set(by_question_id):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Answers must cover exactly this attempt's MCQ questions",
            )

        results: list[McqOutcome] = []
        correct_count = 0
        for question_id, (attempt_question, question) in by_question_id.items():
            selected = answers[question_id]
            correct = selected == question.correct_index
            correct_count += int(correct)
            attempt_question.user_answer = str(selected)
            attempt_question.correct = correct
            results.append(
                McqOutcome(
                    question_id=question_id,
                    correct=correct,
                    correct_index=question.correct_index or 0,
                    explanation=question.explanation or "",
                )
            )

        attempt.submitted_at = datetime.now(UTC)
        await self._session.commit()

        return McqGraded(
            results=results,
            mcq_score=correct_count / len(by_question_id) if by_question_id else 0.0,
        )

    # -- free text -----------------------------------------------------------

    async def _assert_daily_grade_budget(self, user_id: UUID) -> None:
        """Per-user daily cap on LLM-graded submissions (overview.md: the one
        cost axis that scales with USER behaviour rather than corpus size — a
        different quota story from the generation quota governor)."""

        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        graded_today = await self._session.scalar(
            select(func.count())
            .select_from(QuizAttempt)
            .where(QuizAttempt.user_id == user_id, QuizAttempt.graded_at >= day_start)
        )
        if (graded_today or 0) >= self._settings.quiz_free_text_grades_per_user_per_day:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Daily quiz-grading limit reached, try again tomorrow",
            )

    async def submit_free_text(
        self, user_id: UUID, attempt_id: UUID, raw_answer: str
    ) -> FreeTextGraded:
        settings = self._settings
        attempt = await self.load_attempt(user_id, attempt_id)
        if attempt.submitted_at is None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Submit MCQ answers first")
        if attempt.graded_at is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Already graded")

        answer = raw_answer[: settings.quiz_free_text_answer_max_chars]
        await self._assert_daily_grade_budget(user_id)

        row = (
            await self._session.execute(
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

        rubric_level, justification = await self._grade(question, answer)
        free_text_correct = rubric_level >= settings.quiz_free_text_pass_level

        attempt_question.user_answer = answer
        attempt_question.correct = free_text_correct
        attempt_question.rubric_level = rubric_level
        attempt_question.justification = justification

        mcq_correct = (
            await self._session.execute(
                select(QuizAttemptQuestion.correct)
                .join(Question, Question.id == QuizAttemptQuestion.question_id)
                .where(
                    QuizAttemptQuestion.attempt_id == attempt_id,
                    Question.kind == QuestionKind.MCQ,
                )
            )
        ).scalars().all()
        mcq_fraction = (
            (sum(1 for c in mcq_correct if c) / len(mcq_correct)) if mcq_correct else 0.0
        )

        score = combined_score(
            mcq_fraction=mcq_fraction,
            rubric_level=rubric_level,
            mcq_weight=settings.quiz_mcq_weight,
            free_text_weight=settings.quiz_free_text_weight,
        )
        passed = score >= settings.quiz_pass_threshold

        attempt.score = score
        attempt.passed = passed
        attempt.graded_at = datetime.now(UTC)

        progressed = await self._apply_progression(user_id, attempt, passed=passed)
        remediation = [] if passed else await self._remediation_for(attempt_id)

        await self._session.commit()

        return FreeTextGraded(
            question_id=question.id,
            rubric_level=rubric_level,
            free_text_correct=free_text_correct,
            justification=justification,
            score=score,
            passed=passed,
            progressed=progressed,
            remediation=remediation,
        )

    async def _grade(self, question: Question, answer: str) -> tuple[int, str]:
        """The one LLM call in this service, plus ADR-0009's output check."""

        result = await self._generator.grade_free_text(
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
        if not result.items:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Grading failed, try again")
        graded = result.items[0]

        if references_question(
            graded.justification, question.stem, question.reference_answer or "", answer
        ):
            return graded.rubric_level, graded.justification

        return 0, (
            "[flagged: grader response did not clearly reference this question — "
            f"treated as level 0] {graded.justification}"
        )

    async def _apply_progression(
        self, user_id: UUID, attempt: QuizAttempt, *, passed: bool
    ) -> bool:
        """The tier state machine. Placement attempts never progress (ADR-0027)."""

        if not passed or attempt.kind == QuizKind.PLACEMENT:
            return False

        progress = await self._session.scalar(
            select(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id,
                UserTopicProgress.topic_id == attempt.topic_id,
            )
        )
        if progress is None:
            return False

        passed_arr = list(progress.tier_quiz_passed)
        passed_arr[attempt.difficulty.rank] = True
        progress.tier_quiz_passed = passed_arr

        if attempt.kind == QuizKind.PROMOTION:
            next_tier = attempt.difficulty.next_tier()
            if next_tier is not None:
                progress.current_difficulty = next_tier
        elif attempt.kind == QuizKind.MASTERY and progress.mastered_at is None:
            progress.mastered_at = datetime.now(UTC)

        return True

    async def _remediation_for(self, attempt_id: UUID) -> list[RemediationCard]:
        wrong_question_ids = (
            await self._session.execute(
                select(QuizAttemptQuestion.question_id).where(
                    QuizAttemptQuestion.attempt_id == attempt_id,
                    QuizAttemptQuestion.correct.is_(False),
                )
            )
        ).scalars().all()
        if not wrong_question_ids:
            return []

        rows = (
            await self._session.execute(
                select(Card.id, Card.title, Subtopic.title)
                .join(Question, Question.card_id == Card.id)
                .join(Subtopic, Subtopic.id == Card.subtopic_id)
                .where(Question.id.in_(wrong_question_ids))
            )
        ).all()

        seen_card_ids: set[UUID] = set()
        out: list[RemediationCard] = []
        for card_id, title, subtopic_title in rows:
            if card_id in seen_card_ids:
                continue
            seen_card_ids.add(card_id)
            out.append(
                RemediationCard(card_id=card_id, title=title, subtopic_title=subtopic_title)
            )
        return out
