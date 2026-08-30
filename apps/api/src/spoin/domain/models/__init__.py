"""Every model, re-exported.

Alembic autogenerate only sees what has been imported, so a model that is not
re-exported here silently never gets a migration. Add new models to `__all__`.
"""

from spoin.domain.models.card import (
    AskConversation,
    AskMessage,
    AskUsage,
    Card,
    CardRepair,
    CardReport,
    CardStats,
    RejectedCard,
)
from spoin.domain.models.engagement import (
    CardBookmark,
    CardLike,
    CardNote,
    EngagementEvent,
    FeedPlan,
    FeedSlate,
    UserCardState,
    UserSeenBitmap,
    UserSessionTopicSignal,
    UserSubtopicProgress,
    UserTopicAffinity,
    UserTopicCycle,
    UserTopicDifficultyProgress,
)
from spoin.domain.models.preferences import UserFont, UserPreference
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
    "AskConversation",
    "AskMessage",
    "AskUsage",
    "Card",
    "CardBookmark",
    "CardLike",
    "CardNote",
    "CardRepair",
    "CardReport",
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
    "UserFont",
    "UserPreference",
    "UserQuestionSeen",
    "UserSeenBitmap",
    "UserSessionTopicSignal",
    "UserSubtopicProgress",
    "UserTopic",
    "UserTopicAffinity",
    "UserTopicCycle",
    "UserTopicDifficultyProgress",
    "UserTopicProgress",
]
