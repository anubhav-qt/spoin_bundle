"""Wire contracts.

These Pydantic models ARE the API contract — FastAPI turns them into the OpenAPI
schema, and `packages/api-types` is generated from that. Changing a field here
changes the frontend's types, and CI fails the build on drift (ADR-0001). That is
the intended feedback loop, so treat a rename here as a breaking change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from spoin.domain.enums import Difficulty, EngagementKind


class TopicOut(BaseModel):
    id: UUID
    #: **Always** the user's own name for the topic, never `topic.canonical_name`.
    #: Shared entity, personal label (ADR-0004).
    display_name: str
    slug: str
    is_custom: bool
    current_difficulty: Difficulty
    #: 0-359 hue, or null to use the deterministic default (ADR-0034). Per
    #: subscription, same personal-label split as `display_name`.
    accent_hue: int | None = None


class TopicColorIn(BaseModel):
    #: null resets to the deterministic default.
    hue: int | None = Field(default=None, ge=0, le=359)


class TopicRequestIn(BaseModel):
    """A user typing a topic by name, not picking from Discover. ADR-0025's
    batched matching decides whether this canonicalizes onto an existing topic
    or mints a new one -- the caller never chooses which."""

    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    #: ADR-0027: trusted unconditionally, no quiz gates it. Defaults to
    #: beginner, same as every other subscribe path.
    entry_difficulty: Difficulty = Difficulty.BEGINNER


class TopicRequestOut(BaseModel):
    topic: TopicOut
    #: "subscribed" -- the name matched an existing topic (or one already
    #: minted by an earlier request); cards may already exist, no job was
    #: enqueued. "generating" -- a brand-new Topic was minted and a
    #: GenerationJob enqueued; the client must show a "building this topic"
    #: state rather than expecting cards immediately (ADR-0003: generation is
    #: minutes-to-hours on free tier, never synchronous).
    status: Literal["subscribed", "generating"]


class CardOut(BaseModel):
    id: UUID
    topic_id: UUID
    subtopic_id: UUID
    #: The curriculum slot's title. Sent because the feed groups cards under
    #: station headers and the client must not have to fetch the curriculum
    #: separately to label them — that would be a second round trip on the one
    #: path with a <100ms budget.
    subtopic_title: str
    difficulty: Difficulty
    title: str
    #: The collapsed-state hook. If absent the client renders `body` with a CSS
    #: line-clamp — truncation is the safety net, not the design.
    summary: str
    body: str
    #: Content shapes present in `body` — "code", "diagram", "comparison", any
    #: subset, `[]` for plain prose. Derived server-side from `body` itself
    #: (ADR-0017), a rendering hint for which collapsed-preview shape to use.
    archetype: list[str]
    #: At most one true per subtopic (ADR-0017). The client renders this one
    #: never-collapsed with anchor styling — it does not decide for itself
    #: which card that is.
    is_hero: bool
    created_at: datetime


class FeedOut(BaseModel):
    cards: list[CardOut]
    next_position: int
    #: The pool could not satisfy the difficulty mix, so this page is short by
    #: design. We serve degraded rather than wrong.
    degraded: bool
    #: True end of feed. The client shows "more coming soon" — never an indefinite
    #: spinner, because on free tier a fill can take hours rather than seconds.
    exhausted: bool


class EngagementEventIn(BaseModel):
    #: Client-generated, and required. This is the idempotency key: retries must
    #: collide rather than inflate impression counts.
    id: UUID
    card_id: UUID
    kind: EngagementKind
    dwell_ms: int | None = Field(default=None, ge=0)
    #: Accepted for ordering within a batch only. `occurred_at` is server-assigned
    #: and this value is never treated as truth.
    client_occurred_at: datetime | None = None
    session_id: UUID | None = None


class EngagementBatchIn(BaseModel):
    """Clients buffer and flush every few seconds, on card change, and on page
    hide. One request per scroll tick would melt a free-tier API.

    `expand` is the exception and should be sent promptly rather than buffered: a
    dropped impression is acceptable, a dropped expansion stalls progression.
    """

    events: list[EngagementEventIn] = Field(max_length=200)


class EngagementAck(BaseModel):
    accepted: int
    duplicates: int
    rejected: int


class ProgressOut(BaseModel):
    topic_id: UUID
    current_difficulty: Difficulty
    #: Fraction of cards seen in the thinnest subtopic of the current tier — the
    #: 80% gate is per subtopic, so the weakest one governs.
    coverage: float
    #: Latched. Once true it is never recomputed, so background generation cannot
    #: silently revoke it.
    quiz_unlocked: bool
    tier_quiz_passed: list[bool]
    mastered: bool


class TopicDiscoverOut(BaseModel):
    topic_id: UUID
    #: `canonical_name`, not a personal label — ADR-0004's split only applies once a
    #: `UserTopic` row exists, and a topic surfaced here by definition has none yet.
    display_name: str
    subscriber_count: int


class TopicStatsOut(BaseModel):
    topic_id: UUID
    current_difficulty: Difficulty
    coverage: float
    quiz_unlocked: bool
    mastered: bool
    tier_quiz_passed: list[bool]
    #: Current counts, not raw event totals — see ADR-0015 for why likes/saves and
    #: notes/shares are sourced differently.
    likes: int
    saves: int
    notes: int
    shares: int


# ------------------------------------------------------------------------ quiz --
# ADR-0009 (quiz shape, grading), amended by ADR-0027 (entry tier / `placement`'s
# meaning). See api/routers/quiz.py for the actual flow these wire up.


class QuizStartIn(BaseModel):
    difficulty: Difficulty


class QuizMcqQuestionOut(BaseModel):
    question_id: UUID
    stem: str
    #: Never `correct_index` — that would let the client grade itself.
    options: list[str]


class QuizFreeTextQuestionOut(BaseModel):
    question_id: UUID
    stem: str


class QuizStartOut(BaseModel):
    attempt_id: UUID
    topic_id: UUID
    difficulty: Difficulty
    #: "placement" is ADR-0027's repurposed meaning: a below-current-tier
    #: practice attempt that never changes progression. "promotion"/"mastery"
    #: are unchanged from ADR-0009.
    kind: Literal["placement", "promotion", "mastery"]
    mcq: list[QuizMcqQuestionOut]
    free_text: QuizFreeTextQuestionOut


class McqAnswerIn(BaseModel):
    question_id: UUID
    selected_index: int = Field(ge=0)


class QuizSubmitMcqIn(BaseModel):
    answers: list[McqAnswerIn]


class McqResultOut(BaseModel):
    question_id: UUID
    correct: bool
    correct_index: int
    explanation: str


class QuizSubmitMcqOut(BaseModel):
    """Immediate, deterministic (ADR-0009) — the free-text answer is a separate
    call (`QuizSubmitFreeTextIn`) precisely so this one never waits on an LLM."""

    attempt_id: UUID
    results: list[McqResultOut]
    #: Fraction correct, 0-1. Final `score` isn't known until the free-text
    #: call also lands (70/30 weighting).
    mcq_score: float


class QuizSubmitFreeTextIn(BaseModel):
    answer: str


class QuizFreeTextResultOut(BaseModel):
    question_id: UUID
    #: 0-3 (content-model.md's rubric).
    rubric_level: int
    correct: bool
    justification: str


class RemediationCardOut(BaseModel):
    """A card behind a question the user got wrong — content-model.md's
    "discovery tool" framing: a failed attempt points at exactly what to
    review, not just a score."""

    card_id: UUID
    title: str
    subtopic_title: str


class QuizSubmitFreeTextOut(BaseModel):
    attempt_id: UUID
    free_text: QuizFreeTextResultOut
    #: Weighted 70% MCQ / 30% free text (ADR-0009).
    score: float
    passed: bool
    #: Empty unless `passed` is False.
    remediation: list[RemediationCardOut]
    #: True if this attempt actually advanced `current_difficulty` or conferred
    #: mastery — always False for a `placement`-kind (practice) attempt, and
    #: for any attempt that didn't pass.
    progressed: bool


# ------------------------------------------------------------------------ auth --


class RegisterIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class LoginIn(BaseModel):
    email: str
    password: str


class GoogleAuthIn(BaseModel):
    id_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: UUID
    #: None for a guest — see `User.is_guest` (domain/models/topic.py).
    email: str | None
    display_name: str
    is_guest: bool
    onboarding_complete: bool


class OnboardingCompleteIn(BaseModel):
    #: Topics chosen during onboarding (from /topics/discover), subscribed to
    #: server-side. IDs, not slugs -- matches what discover already returns,
    #: no extra lookup needed on either side.
    topic_ids: list[UUID] = Field(default_factory=list, max_length=10)
    entry_difficulty: Difficulty = Difficulty.BEGINNER

