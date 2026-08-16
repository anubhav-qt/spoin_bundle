"""Wire contracts.

These Pydantic models ARE the API contract — FastAPI turns them into the OpenAPI
schema, and `packages/api-types` is generated from that. Changing a field here
changes the frontend's types, and CI fails the build on drift (ADR-0001). That is
the intended feedback loop, so treat a rename here as a breaking change.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from slocho.domain.enums import Difficulty, EngagementKind


class TopicOut(BaseModel):
    id: UUID
    #: **Always** the user's own name for the topic, never `topic.canonical_name`.
    #: Shared entity, personal label (ADR-0004).
    display_name: str
    slug: str
    is_custom: bool
    current_difficulty: Difficulty


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
