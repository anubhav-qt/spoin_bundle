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

from spoin.domain.enums import Difficulty


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

    title: str = Field(max_length=120, min_length=1)
    #: The literal, descriptive name — always present, never playful. Feeds every
    #: consumer except the feed face itself: quiz stems, remediation links,
    #: progress/coverage lists, search, and the already-covered title list this
    #: generator is shown on the next call to the same subtopic (ADR-0022). Getting
    #: this one wrong is silent, per the ADR: it's easy to feed the prompt only
    #: `title` and have it invent the same joke twice under a new punchline.
    canonical_title: str = Field(max_length=160, min_length=1)
    summary: str
    body: str
    #: What the model was ASKED for. The gate re-rates this independently, because
    #: a self-reported difficulty just echoes the request and validates nothing.
    difficulty: Difficulty
    #: Selected from the ASCII scene catalog, never drawn (ADR-0021). None until the
    #: catalog exists — `langchain_impl.py`'s prompt has nothing to select from yet,
    #: so this stays unset there too. Present now so the schema and CardDraft shape
    #: don't change again once the catalog lands (no regeneration needed to backfill).
    visual_id: str | None = None
    visual_slots: dict[str, str] | None = None


class SubtopicTierDraft(BaseModel):
    """One difficulty tier's treatment of a `SubtopicGroupDraft`."""

    difficulty: Difficulty
    description: str
    target_cards: int = Field(ge=5, le=25)


class SubtopicGroupDraft(BaseModel):
    """One curriculum-authored concept, and the model's own decision about which
    difficulty tiers it actually needs.

    This does NOT default to three tiers. Mechanically generating a beginner,
    intermediate, AND advanced entry for every concept forces the model to pad —
    some concepts only make sense at one or two tiers, and asking it to fill a grid
    regardless just produces near-duplicate cards with the difficulty label as the
    only real difference. `tiers` is 1-3 entries, whichever the model decides this
    concept genuinely needs; a taste decision (same trust level as `target_cards`),
    not one requiring independent verification the way a per-card difficulty tag does.
    """

    title: str
    tiers: list[SubtopicTierDraft] = Field(min_length=1, max_length=3)
    position: int = 0


class CurriculumDraft(BaseModel):
    """The output of the curriculum pass — one call per topic, all three tiers.

    A single call rather than three so the model can lay out a coherent
    progression instead of three disconnected lists.
    """

    #: At least one — a topic with zero subtopics would leave the pipeline's
    #: per-topic branch with nothing to fan out for card generation, which the
    #: graph topology assumes never happens (every topic branch dispatches >=1
    #: subtopic branch on the way to the shared persist step; see pipeline.py's
    #: `fan_out_subtopics` docstring for why that invariant matters).
    subtopics: list[SubtopicGroupDraft] = Field(min_length=1)
    #: Emitted when the topic is too broad for one curriculum (>~20 subtopics per
    #: tier). The broad topic is NOT deleted — it becomes a survey, and these are
    #: the deeper siblings it introduces. Rule 2 of ADR-0007 is generative, not
    #: destructive.
    deep_dive_topics: list[str] = Field(default_factory=list)
    is_survey: bool = False


class TopicMatchVerdict(BaseModel):
    """ADR-0004's mid-band call: "are these the same subject?" — but the answer
    isn't just yes/no. Even when `same_topic` is False, the judge can flag existing
    subtopics from the matched topic as relevant hints for the NEW topic's own
    curriculum pass to consider adapting (never copied wholesale — the curriculum
    pass, not this verdict, decides whether/how to use them)."""

    same_topic: bool
    #: Existing subtopic titles from the matched topic worth showing the curriculum
    #: pass as context, whether or not `same_topic` is True.
    relevant_subtopic_titles: list[str] = Field(default_factory=list)


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
    async def generate_curriculum(
        self,
        topic_name: str,
        description: str,
        related_subtopic_hints: list[str] | None = None,
        existing_subtopics: list[str] | None = None,
    ) -> CurriculumDraft:
        """One call per topic. The highest-stakes call in the system: every card in
        the topic inherits its quality, so it always runs on the strongest
        available model regardless of what generates the cards.

        `related_subtopic_hints` carries titles pulled from a DIFFERENT topic
        ADR-0004's mid-band judge found related-but-not-identical (see
        `judge_topic_match`) — loose inspiration, never reused verbatim, since
        those subtopics belong to a different topic's own identity.

        `existing_subtopics` carries titles (with description) already under
        THIS exact topic — from an older seed fixture, or a prior partial run.
        Same prevention pattern already used for card titles (see
        `generate_cards`'s `existing_titles`), one level up: if a subtopic this
        call wants to propose is already covered by one of these, it should
        reuse the EXISTING title VERBATIM in its output, so the pipeline's
        persistence step can match on it directly and reuse that row instead of
        forking a near-duplicate. Deciding whether something counts as "already
        covered" is the same kind of taste call as everything else in the
        curriculum pass — not one that needs independent verification.
        """

    @abstractmethod
    async def judge_topic_match(
        self,
        candidate_name: str,
        candidate_description: str,
        matched_topic_name: str,
        matched_subtopic_titles: list[str],
    ) -> TopicMatchVerdict:
        """ADR-0004's mid-band step: fires only when embedding similarity against
        an existing topic lands between the auto-merge and auto-new thresholds.
        Cached permanently in `topic_alias` once decided — this pair is never
        paid for again."""

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
