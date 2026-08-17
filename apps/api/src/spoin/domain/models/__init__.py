"""Every model, re-exported.

Alembic autogenerate only sees what has been imported, so a model that is not
re-exported here silently never gets a migration. Add new models to `__all__`.
"""

from spoin.domain.models.card import Card, CardStats, RejectedCard
from spoin.domain.models.engagement import (
    CardBookmark,
    CardLike,
    CardNote,
    EngagementEvent,
    FeedPlan,
    FeedSlate,
    UserCardState,
    UserSeenBitmap,
    UserSubtopicProgress,
    UserTopicAffinity,
    UserTopicCycle,
)
from spoin.domain.models.quiz import (
    GenerationJob,
    Question,
    QuizAttempt,
    QuizAttemptQuestion,
    QuotaLedger,
    UserQuestionSeen,
    UserTopicProgress,
)
from spoin.domain.models.topic import (
    Subtopic,
    Topic,
    TopicAlias,
    TopicEdge,
    User,
    UserTopic,
)

__all__ = [
    "Card",
    "CardBookmark",
    "CardLike",
    "CardNote",
    "CardStats",
    "EngagementEvent",
    "FeedPlan",
    "FeedSlate",
    "GenerationJob",
    "Question",
    "QuizAttempt",
    "QuizAttemptQuestion",
    "QuotaLedger",
    "RejectedCard",
    "Subtopic",
    "Topic",
    "TopicAlias",
    "TopicEdge",
    "User",
    "UserCardState",
    "UserQuestionSeen",
    "UserSeenBitmap",
    "UserSubtopicProgress",
    "UserTopic",
    "UserTopicAffinity",
    "UserTopicCycle",
    "UserTopicProgress",
]
