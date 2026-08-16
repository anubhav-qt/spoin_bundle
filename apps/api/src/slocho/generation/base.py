"""`ContentGenerator` — our interface, in our own types.

ADR-0002: LangChain lives behind this and nowhere else. Nothing outside
`langchain_impl.py` may import it, enforced by a ruff banned-api rule in CI rather
than by convention. LangChain types never cross this boundary.

ADR-0005: **every method takes a collection.** The free tier meters requests, not
tokens, so a single-item call is a batch of one — never a separate code path.
There is no `generate_card` to retrofit later, deliberately.

LangChain is a composition library, not an orchestrator: no scheduler, no durable
state, no retry across restart. Parallelism and durability come from the job queue.
Requests to "make generation faster" are answered by worker concurrency, never by
changing chain code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from slocho.domain.enums import Difficulty


class CardDraft(BaseModel):
    """One generated card, before the quality gate sees it.

    Note what is absent: `status`, `version`, `family_id`. Those are system-owned
    and never set by a generator. Also absent, deliberately: `archetype`. It is
    NOT requested here — content/archetype.py derives it from `body` itself once
    the card is persisted (ADR-0017), the same reasoning as leaving `status` out:
    a self-reported archetype tag would just echo whatever the prompt asked for.

    What the prompt SHOULD do instead: actually use the markdown shapes the
    classifier looks for, where the subtopic calls for it — a fenced code block
    with a language tag for command/query/config-heavy material, a compact
    arrow-chain diagram for request-flow/process-order material, a ❌/✅ pair for
    misconception-correction material. This is a content-quality instruction for
    whichever prompt template implements `generate_cards`, not a schema change —
    same spirit as `summary` being a purpose-written hook rather than a
    truncation: better use of the body the model already writes, not a new field.
    """

    title: str = Field(max_length=120)
    summary: str
    body: str
    #: What the model was ASKED for. The gate re-rates this independently, because
    #: a self-reported difficulty just echoes the request and validates nothing.
    difficulty: Difficulty


class SubtopicDraft(BaseModel):
    title: str
    description: str
    difficulty: Difficulty
    target_cards: int = Field(ge=5, le=25)
    position: int = 0


class CurriculumDraft(BaseModel):
    """The output of the curriculum pass — one call per topic, all three tiers.

    A single call rather than three so the model can lay out a coherent
    progression instead of three disconnected lists.
    """

    subtopics: list[SubtopicDraft]
    #: Emitted when the topic is too broad for one curriculum (>~20 subtopics per
    #: tier). The broad topic is NOT deleted — it becomes a survey, and these are
    #: the deeper siblings it introduces. Rule 2 of ADR-0007 is generative, not
    #: destructive.
    deep_dive_topics: list[str] = Field(default_factory=list)
    is_survey: bool = False


class DifficultyVerdict(BaseModel):
    """One batch-judge rating. See `judge_difficulty` for why it is independent."""

    index: int
    difficulty: Difficulty
    factually_sound: bool
    note: str = ""


class QuestionDraft(BaseModel):
    card_index: int
    stem: str
    options: list[str] | None = None
    correct_index: int | None = None
    rubric: str | None = None
    reference_answer: str | None = None
    explanation: str = ""


class BatchResult[T](BaseModel):
    """Partial failure is the NORMAL case, not an exception (ADR-0005).

    If 3 of 10 items in a batch are malformed, the other 7 must still land — a
    batch that fails atomically wastes a scarce request. So every batch call
    returns what succeeded alongside what did not, and callers are expected to
    handle both.
    """

    items: list[T] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.items)


class ContentGenerator(ABC):
    """The only interface the rest of the codebase knows about."""

    @abstractmethod
    async def generate_curriculum(self, topic_name: str, description: str) -> CurriculumDraft:
        """One call per topic. The highest-stakes call in the system: every card in
        the topic inherits its quality, so it always runs on the strongest
        available model regardless of what generates the cards."""

    @abstractmethod
    async def generate_cards(
        self,
        *,
        topic_name: str,
        subtopic_title: str,
        subtopic_description: str,
        difficulty: Difficulty,
        count: int,
        existing_titles: list[str],
    ) -> BatchResult[CardDraft]:
        """`existing_titles` is every card already in this subtopic **across all
        difficulties, tagged with their level**. Cross-difficulty inclusion is
        deliberate: a beginner and an advanced card on the same subtopic must
        differ in depth, not merely in wording.

        Calls to one subtopic are sequential so each prompt sees what the last
        produced; different subtopics run concurrently.
        """

    @abstractmethod
    async def judge_difficulty(self, bodies: list[str]) -> BatchResult[DifficultyVerdict]:
        """Rate cards **without** being told what level was requested.

        This is the subtlety that makes or breaks the gate. Ask for a beginner card
        and you get one tagged `beginner` because that is what was asked — the tag
        echoes the request and validates nothing. Only an independent rating can
        disagree, and disagreement is the entire point.

        ~20 cards per request, so one call validates twenty cards and the gate is
        affordable on everything rather than on a sample.
        """

    @abstractmethod
    async def generate_questions(
        self, cards: list[tuple[str, str]], difficulty: Difficulty
    ) -> BatchResult[QuestionDraft]:
        """Questions come FROM cards, so the quiz structurally cannot test material
        the corpus never taught. `cards` is (title, body)."""
