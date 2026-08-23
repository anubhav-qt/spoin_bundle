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
    #: 0-359 hue, -1 to opt out of topic color entirely (ADR-0051, follow
    #: the palette's plain --accent), or null to use the deterministic
    #: default (ADR-0034). Per subscription, same personal-label split as
    #: `display_name`.
    accent_hue: int | None = None


class TopicColorIn(BaseModel):
    #: -1 opts out of topic color (ADR-0051); null resets to the
    #: deterministic default (ADR-0034).
    hue: int | None = Field(default=None, ge=-1, le=359)


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
    #: ASCII scene reference (ADR-0021) or, on the free-form generation
    #: testing branch, a model-given label for art the generator drew itself
    #: (see `CardDraft.is_hero`'s sibling docstring in generation/base.py).
    #: Null for the great majority of cards — art is the exception, not the
    #: rule. The client renders this at the TOP of the card, before title and
    #: everything else, and as the entire collapsed/preview face when present
    #: (in place of the usual text teaser).
    visual_id: str | None = None
    #: {"art": <raw ascii>, "alt": <one-sentence alt text>}, or null together
    #: with `visual_id`. Never markdown, never inside `body` — a dedicated
    #: monospace box the renderer owns (ADR-0021).
    visual_slots: dict[str, str] | None = None
    created_at: datetime
    #: This user's private `CardNote.body`, or null if they never wrote one.
    #: Populated by a second query keyed on the feed page's card_ids — never
    #: joined into ranking, per `CardNote`'s "never fed to ranking" contract.
    note: str | None = None


class FeedOut(BaseModel):
    cards: list[CardOut]
    next_position: int
    #: The pool could not satisfy the difficulty mix, so this page is short by
    #: design. We serve degraded rather than wrong.
    degraded: bool
    #: True end of feed. The client shows "more coming soon" — never an indefinite
    #: spinner, because on free tier a fill can take hours rather than seconds.
    exhausted: bool
    #: This page includes a repeat pass: everything at some difficulty has been
    #: shown once, so it is being served again in a fresh order. Announced once
    #: rather than silently looping — an unexplained repeat reads as a bug.
    recycling: bool = False


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
    #: Always false from `/topics/discover` (it excludes followed topics by
    #: definition). `/topics/all` (ADR-0038) reuses this same shape and sets it
    #: per-topic, so the modal can grey out "Follow" instead of offering a
    #: second subscribe on a topic the reader already follows.
    followed: bool = False


class CustomTopicStatusOut(BaseModel):
    topic_id: UUID
    display_name: str
    slug: str
    #: The topic's most recent GenerationJob status: "pending" | "running" |
    #: "completed" | "failed". Null when the requested name matched an
    #: existing, already-generated topic and no job was ever enqueued for it
    #: (`request_topic`'s "subscribed" outcome) -- there is nothing to poll.
    generation_status: str | None
    requested_at: datetime


class GenerationSubtopicProgressOut(BaseModel):
    subtopic_id: UUID
    #: The curriculum concept's title -- shared by every difficulty tier of
    #: the same subtopic group (see `SubtopicPlan.title` in pipeline.py).
    group_title: str
    difficulty: Difficulty
    cards_target: int
    cards_done: int
    #: Null until the cards phase has committed for this tier -- exactly how
    #: many cards ended up needing a question isn't known until then (see
    #: pipeline.py's `_process_gate_item`).
    questions_target: int | None
    questions_done: int


class GenerationProgressOut(BaseModel):
    #: The GenerationJob's own status. "pending" -- queued, not yet claimed by
    #: a worker pass. "running" -- `subtopics` fills in live as it proceeds.
    #: "completed"/"failed" -- terminal; poll no further.
    status: Literal["pending", "running", "completed", "failed"]
    #: "curriculum" -- the curriculum call hasn't returned yet, no subtopics to
    #: show. "cards" -- subtopics known, cards/questions still filling in
    #: (which of the two is per-subtopic, from cards_done vs cards_target and
    #: questions_done vs questions_target). "done" -- every subtopic finished.
    #: Null only while `status` is still "pending".
    stage: Literal["curriculum", "cards", "done"] | None
    topic_name: str | None
    subtopics: list[GenerationSubtopicProgressOut]
    #: Set only when `status == "failed"` -- `GenerationJob.last_error`.
    error: str | None
    #: True once the topic has crossed ADR-0053's live-coverage threshold --
    #: the same moment it starts appearing in Topics/Discover for users who
    #: didn't request it. Lets the requester's own progress view show a
    #: distinct "now live in the feed" milestone, separate from `status ==
    #: "completed"` (which can still be a while off).
    topic_live: bool


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


class SubtopicProgressOut(BaseModel):
    subtopic_id: UUID
    title: str
    difficulty: Difficulty
    #: Active cards in this subtopic. 0 means nothing has generated yet — the
    #: client should render "not generated yet", not 0% coverage.
    total_cards: int
    seen_cards: int
    #: `seen_cards / total_cards`, or 0.0 when `total_cards` is 0.
    coverage: float
    #: Same 80% bar as the tier-level gate, applied per subtopic.
    covered: bool


class TopicCurriculumOut(BaseModel):
    topic_id: UUID
    subtopics: list[SubtopicProgressOut]


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
    age: int | None = None
    gender: str | None = None
    avatar_icon: str | None = None
    has_avatar_image: bool = False
    #: Rides along on the existing user payload rather than behind a separate
    #: /preferences route: AuthProvider already fetches this object on every
    #: navigation, so Settings can render its current value with no request of
    #: its own, and PATCH /profile/me stays the single write path.
    daily_card_goal: int = 10


class OnboardingTopicChoice(BaseModel):
    #: From /topics/discover -- an ID, not a slug, matches what discover
    #: already returns, no extra lookup needed on either side.
    topic_id: UUID
    #: Per-topic now (was one global difficulty for every topic chosen) --
    #: each topic in onboarding gets its own starting difficulty, same as a
    #: topic picked up later via Discover or a custom request already could.
    entry_difficulty: Difficulty = Difficulty.BEGINNER


class OnboardingCompleteIn(BaseModel):
    #: Topics chosen during onboarding, each with its own entry difficulty.
    topics: list[OnboardingTopicChoice] = Field(default_factory=list, max_length=10)


# ------------------------------------------------------------------------ notes --
# CardNote (domain/models/engagement.py): per-user, per-card, private, never fed
# to ranking. See docs/tasks/0004-notes-in-one-place.md.


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class NoteOut(BaseModel):
    card_id: UUID
    body: str
    updated_at: datetime


class NoteWithCardOut(BaseModel):
    """One row of the "all my notes" view -- enough card context to be useful
    without opening the card individually (task 0004's ask)."""

    note: NoteOut
    card: CardOut
    #: This user's own name for the card's topic (ADR-0004) -- same split as
    #: `TopicOut.display_name`, sourced from `UserTopic` rather than `Topic`.
    topic_name: str


class LikedCardOut(BaseModel):
    """One row of the "liked" collection -- the card the user hearted, enough
    context to render it inline (same join strategy as `NoteWithCardOut`), and
    when they liked it so the client can sort by recency without a round-trip."""

    card: CardOut
    #: This user's own name for the card's topic (ADR-0004).
    topic_name: str
    #: Server timestamp from `card_like.created_at` -- the authoritative sort key
    #: for "recently liked" ordering. Client clocks are wrong; we never trust them.
    liked_at: datetime


class SavedCardOut(BaseModel):
    """One row of the "saved" collection -- the card the user bookmarked, enough
    context to render as a compact library tile without a follow-up request.

    Mirrors `LikedCardOut` exactly, sourced from `card_bookmark` rather than
    `card_like`. Kept as a separate schema so the two surfaces can diverge
    independently if needed (e.g. bookmark-specific metadata in the future)."""

    card: CardOut
    #: This user's own name for the card's topic (ADR-0004).
    topic_name: str
    #: Server timestamp from `card_bookmark.created_at`. Sort key for "recently
    #: saved" ordering -- client clocks are never trusted (ADR-0011).
    saved_at: datetime


# ----------------------------------------------------------------------- profile --


class UserProfileUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    age: int | None = Field(default=None, ge=1, le=120)
    gender: str | None = Field(default=None, max_length=32)
    avatar_icon: str | None = Field(default=None, max_length=32)
    #: Bounded server-side, not just in the picker: the UI offers a fixed set
    #: of steps but the endpoint is the actual authority on what is storable.
    daily_card_goal: int | None = Field(default=None, ge=1, le=200)


class DailyActivityOut(BaseModel):
    date: str  # YYYY-MM-DD
    cards_read: int


class ProfileStatsOut(BaseModel):
    current_streak: int
    longest_streak: int
    total_cards_read: int
    total_topics: int
    monthly_activity: list[DailyActivityOut]


# -- Data export (Settings -> Data & Privacy) ---------------------------------
#
# Everything below is the user's OWN content, read straight from their rows.
# Nothing derived, nothing about other users, and no card bodies from the
# shared corpus -- a card belongs to the corpus, the user's relationship to it
# (that they liked it, saved it, wrote on it) is what is theirs to take.


class ExportedCardRefOut(BaseModel):
    card_id: UUID
    title: str
    topic: str
    difficulty: Difficulty
    at: datetime


class ExportedNoteOut(BaseModel):
    card_id: UUID
    card_title: str
    topic: str
    body: str
    updated_at: datetime


class ExportedTopicOut(BaseModel):
    topic_id: UUID
    name: str
    is_custom: bool
    current_difficulty: Difficulty | None
    followed_at: datetime


class ProfileExportOut(BaseModel):
    #: ISO-8601, set by the server at export time.
    exported_at: datetime
    schema_version: int
    profile: UserOut
    topics: list[ExportedTopicOut]
    notes: list[ExportedNoteOut]
    liked_cards: list[ExportedCardRefOut]
    saved_cards: list[ExportedCardRefOut]
    daily_activity: list[DailyActivityOut]
