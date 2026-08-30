"""Domain enums.

These are stored as native Postgres enums. Adding a value is a migration, which
is the point: the set of card states is not something that should be changeable
by a stray string literal.
"""

from __future__ import annotations

from enum import StrEnum


class Difficulty(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"

    @property
    def rank(self) -> int:
        return _DIFFICULTY_ORDER[self]

    def next_tier(self) -> Difficulty | None:
        order = list(Difficulty)
        index = order.index(self)
        return order[index + 1] if index + 1 < len(order) else None


_DIFFICULTY_ORDER: dict[Difficulty, int] = {
    Difficulty.BEGINNER: 0,
    Difficulty.INTERMEDIATE: 1,
    Difficulty.ADVANCED: 2,
}


class CardStatus(StrEnum):
    """A generated card is `draft` until the quality gate passes it. It never
    reaches the corpus otherwise (content-model.md)."""

    DRAFT = "draft"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    #: Was live, then pulled by an operator via the repair lane (ADR-0076) --
    #: distinct from REJECTED ("the gate threw this draft out") and SUPERSEDED
    #: ("a newer version in this family replaced it"). The feed's candidate
    #: query already filters `status == ACTIVE`, so this drops the card with no
    #: query change; the row and its engagement history stay for audit.
    RETIRED = "retired"


class CardReportReason(StrEnum):
    """Why a reader flagged a card as structurally broken (ADR-0076). An enum,
    not free text, so per-reason counts are a `GROUP BY` -- same argument as
    `RejectionStage`. The reader's prose goes in `CardReport.note`."""

    ART = "art"
    DIAGRAM = "diagram"
    CODE_BLOCK = "code_block"
    FORMATTING = "formatting"
    OTHER = "other"


class RepairMode(StrEnum):
    """What the operator asked for on a reported card (ADR-0076).

    FIX  -- structure-only repair informed by the rendered image and optional
            guidance; structural checks only, no meaning-lock (the operator's
            review is the gate).
    REMAKE -- regenerate the card from a required brief, through the full
            quality gate like any generated card.
    """

    FIX = "fix"
    REMAKE = "remake"


class RepairStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class CardSource(StrEnum):
    GENERATED = "generated"
    AUTHORED = "authored"


class RejectionStage(StrEnum):
    """Where in the quality gate a draft was thrown out (ADR-0030). Kept on the
    row rather than inferred from `reason` text, so rejection rates per stage
    are a `GROUP BY`, not string parsing."""

    STRUCTURAL = "structural"
    NEAR_DUPLICATE = "near_duplicate"
    VERIFICATION = "verification"


class SeenState(StrEnum):
    """Three states, not a boolean (ADR-0010).

    DEFERRED is what makes scrolling past cost nothing: the card comes back after
    the difficulty cycle completes, rather than being burned or repeated forever.
    """

    UNSEEN = "unseen"
    DEFERRED = "deferred"
    SEEN = "seen"


class EngagementKind(StrEnum):
    IMPRESSION = "impression"
    EXPAND = "expand"
    COLLAPSE = "collapse"
    DWELL = "dwell"
    SKIP = "skip"
    LIKE = "like"
    UNLIKE = "unlike"
    BOOKMARK = "bookmark"
    UNBOOKMARK = "unbookmark"
    NOTE = "note"
    SHARE = "share"
    ASK_AI = "ask_ai"

    # Two events, not one (ADR-0011). Equivalent for the progression gate;
    # weighted very differently for ranking. An explicit tap is a deliberate claim
    # of comprehension; dwell only means a tab was open. Collapsing them into one
    # boolean discards that permanently, and unlike most modelling mistakes it is
    # not recoverable from the event log — the distinction would never have been
    # written down.
    EXPLICIT_COMPLETE = "explicit_complete"
    DWELL_COMPLETE = "dwell_complete"


#: Both mark a card SEEN. Kept as a set so the progression gate can treat them as
#: equivalent without anyone being tempted to merge the underlying events.
COMPLETION_KINDS: frozenset[EngagementKind] = frozenset(
    {EngagementKind.EXPLICIT_COMPLETE, EngagementKind.DWELL_COMPLETE}
)


class QuestionKind(StrEnum):
    MCQ = "mcq"
    FREE_TEXT = "free_text"


class QuestionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    REJECTED = "rejected"


class QuizKind(StrEnum):
    """One mechanism, three uses (ADR-0009)."""

    PLACEMENT = "placement"
    PROMOTION = "promotion"
    MASTERY = "mastery"


class TopicEdgeKind(StrEnum):
    DEEP_DIVE = "deep_dive"


class GenerationBackend(StrEnum):
    """Recorded in `gen_meta` so quality can be compared across backends and a bad
    batch can be traced and retired (ADR-0008)."""

    FAKE = "fake"
    GEMINI = "gemini"
    LOCAL = "local"
    FIXTURE = "fixture"


class CardType(StrEnum):
    """Predetermined archetype / format for card generation."""

    PROSE = "prose"
    CODE = "code"
    DIAGRAM = "diagram"
    COMPARISON = "comparison"
    ASCII = "ascii"
