"""The real `ContentGenerator` — Gemini, via LangChain.

ADR-0002/0024: **the only module in the codebase allowed to import `langchain*`**,
enforced by `tests/test_architecture.py` (an AST-level check, not just a ruff rule)
and the `flake8-tidy-imports` banned-api config in `pyproject.toml`. Nothing here
leaks past `ContentGenerator`'s own types — callers never see a `langchain_core`
or `langchain_google_genai` object.

**Not live-tested.** This was written without a real Gemini API key available —
correctness of the LangChain/pydantic plumbing (structured output, per-item
validation, key rotation) is covered by mocked unit tests
(`tests/test_langchain_impl.py`), but actual PROMPT quality (does the model write
good cards) has not been verified against the real API and should be treated as a
first draft to iterate on once a key exists.

## Wire schemas vs. domain schemas

For every BATCH-returning method (`generate_cards`, `judge_difficulty`,
`generate_questions`), the LangChain call target is a
"wire" schema — a loose Pydantic model with the same shape as the domain type
(`CardDraft`, etc.) but no strict field constraints (no `min_length`, no enum
parsing). That's deliberate: `with_structured_output` validates the ENTIRE
response as one unit at the LangChain/tool-call layer, so if the strict domain
type were the direct target, one malformed item would fail the whole batch atomically
— exactly what ADR-0005 says never to do. Instead: the wire schema always parses
(nothing in it can fail), and THEN each item is validated into its strict domain
type by hand, with per-item failures collected into `BatchResult.failures` and
good items still landing in `BatchResult.items`.

The two single-result methods (`generate_curriculum`, `judge_topic_match`) skip
this — there's no meaningful "partial curriculum," so a hard failure there is
allowed to raise and fail the whole topic branch, matching ADR-0007's framing of
the curriculum pass as the highest-stakes single point of failure.
"""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field, ValidationError

from spoin.core.config import Settings
from spoin.domain.enums import Difficulty
from spoin.generation.base import (
    BatchResult,
    CardDraft,
    ContentGenerator,
    CurriculumDraft,
    DifficultyVerdict,
    QuestionDraft,
    TopicMatchVerdict,
)
from spoin.generation.quota import QuotaGovernor

# ------------------------------------------------------------- wire schemas --


class _WireCard(BaseModel):
    title: str = ""
    canonical_title: str = ""
    summary: str = ""
    body: str = ""


class _WireCardBatch(BaseModel):
    cards: list[_WireCard] = Field(default_factory=list)


class _WireQuestion(BaseModel):
    card_index: int = -1
    kind: str = "mcq"
    stem: str = ""
    options: list[str] | None = None
    correct_index: int | None = None
    rubric: str | None = None
    reference_answer: str | None = None
    explanation: str = ""


class _WireQuestionBatch(BaseModel):
    questions: list[_WireQuestion] = Field(default_factory=list)


class _WireDifficultyVerdict(BaseModel):
    index: int = -1
    difficulty: str = ""
    factually_sound: bool = True
    note: str = ""


class _WireDifficultyBatch(BaseModel):
    verdicts: list[_WireDifficultyVerdict] = Field(default_factory=list)


# ------------------------------------------------------------------ prompts --

_CURRICULUM_SYSTEM = """\
You are designing the curriculum for a learning app. You lay out the full \
"road to mastery" for one topic, across all three difficulty tiers \
(beginner, intermediate, advanced), in a single coherent pass.

Rules:
- Break the topic into subtopics. Each subtopic is a CONCEPT, and you decide \
  which of the three difficulty tiers it genuinely needs — do NOT mechanically \
  give every subtopic all three tiers. Some concepts only make sense at one or \
  two tiers; padding a tier that doesn't add real depth produces near-duplicate \
  content later.
- Budget: aim for roughly 750 cards total across the whole topic (about 250 per \
  tier). Each subtopic should want 5-25 cards (target_cards) at each tier it has. \
  If a subtopic would want more than 25 cards, it is too broad — split it into \
  more than one subtopic instead.
- Aim for roughly 15-20 subtopics per tier. If the topic is broad enough that you \
  want more than ~20 subtopics in a tier, this is a SURVEY topic: set is_survey \
  true, keep the curriculum you already planned, and additionally list the \
  deeper sibling topics this survey should point learners toward in \
  deep_dive_topics (e.g. "Mathematics" survey -> deep_dive_topics might include \
  "Linear Algebra", "Calculus", "Probability"). Do not shrink the survey to fit — \
  a broad topic gets a genuinely good tour, not an artificially narrowed one.
- Write subtopic descriptions as prose for another AI to read when writing cards \
  from them, not as a label for a human to skim.
- If this topic already has subtopics (listed below, if any), and one of them \
  already covers a concept you were about to propose, reuse that EXACT existing \
  title VERBATIM instead of inventing a new one — otherwise the same concept \
  gets a duplicate, disconnected entry. Only propose a new title for something \
  genuinely not already covered.
"""

_CURRICULUM_USER = """\
Topic: {topic_name}
Description: {description}
{hints_block}{existing_subtopics_block}
Design the full curriculum for this topic now.
"""

_CARDS_SYSTEM = """\
You write flashcard-style learning content for a learning app, at a single \
requested difficulty, for one subtopic at a time.

Each card needs:
- title: the display title. Playful/punchy is welcome here SOMETIMES, not always.
- canonical_title: the literal, descriptive name of the concept — NEVER playful. \
  This is what every other part of the app reads (quiz stems, search, the list \
  of titles already covered you'll be shown next time). Getting this field \
  identical to `title` every time defeats the point — it exists specifically so \
  a joke in `title` doesn't make the concept unfindable elsewhere.
- summary: a purpose-written one-to-two sentence hook for a collapsed card face. \
  NOT a truncation of body — the opening of a good explanation is usually \
  throat-clearing, and a hook needs a different opening.
- body: the actual explanation, in markdown. Use markdown shapes that fit the \
  material: a fenced code block with a language tag for command/query/config-heavy \
  material, a compact arrow-chain diagram for request-flow/process-order material, \
  a "wrong way / right way" (X/checkmark) pair for misconception-correction \
  material. Plain prose is fine when nothing else fits better — don't force a \
  shape that doesn't belong.

CRITICAL: never repeat a title (canonical or display) from the "already covered" \
list below — write about something genuinely different within this subtopic. The \
list is tagged with the difficulty each existing card was written at; a card at a \
DIFFERENT difficulty on the same idea must differ in DEPTH, not just wording.
"""

_CARDS_USER = """\
Topic: {topic_name}
Subtopic: {subtopic_title}
Subtopic description: {subtopic_description}
Difficulty: {difficulty}
Write exactly {count} NEW cards at this difficulty for this subtopic.

Already covered in this subtopic (do not repeat any of these):
{existing_titles_block}
"""

_TOPIC_MATCH_SYSTEM = """\
You decide whether two topic names/descriptions refer to the SAME subject — \
e.g. "k8s" and "Kubernetes" are the same; "Java" and "JavaScript" are NOT, \
despite the similar name. If they're the same, also flag which of the existing \
topic's subtopics look genuinely relevant to the candidate — even if you decide \
they are NOT strictly the same topic, still flag any subtopics that could \
reasonably be adapted for the candidate.
"""

_TOPIC_MATCH_USER = """\
Candidate topic: {candidate_name}
Candidate description: {candidate_description}

Existing topic: {matched_topic_name}
Existing topic's subtopics: {matched_subtopic_titles}

Are these the same subject? Which existing subtopics are relevant to the \
candidate, whether or not they're the same subject?
"""

_DIFFICULTY_SYSTEM = """\
You are independently rating flashcard bodies by difficulty (beginner, \
intermediate, or advanced) and by factual accuracy. You are NOT told what \
difficulty was originally requested for each card — rate strictly from the \
content itself. Also flag any card containing a confidently-stated but incorrect \
fact (factually_sound = false) — this is the single most important check, since \
a wrong fact in this corpus is served to everyone who reads this subtopic.
"""

_DIFFICULTY_USER = """\
Rate each of the following {count} card bodies independently.

{bodies_block}
"""

_QUESTIONS_SYSTEM = """\
You write quiz questions FROM the given cards — one question per card, in the \
same order. All but the last question in a batch should be a 4-option multiple \
choice question with exactly one correct answer (kind="mcq") testing something \
the card body actually teaches, with a short explanation. The LAST question in \
the batch should instead be free-text (kind="free_text"): an open-ended prompt \
with a 0-3 level grading rubric (0 none / 1 surface / 2 solid / 3 deep) and a \
reference answer.
"""

_QUESTIONS_USER = """\
Difficulty: {difficulty}
Write one question per card below, in order, following the mcq/free_text split \
described above.

{cards_block}
"""


def _format_existing_titles(existing_titles: list[str]) -> str:
    if not existing_titles:
        return "(none yet)"
    return "\n".join(f"- {title}" for title in existing_titles)


class GeminiContentGenerator(ContentGenerator):
    """ADR-0008: cloud, quota-bound. Always the strongest available model for the
    curriculum pass; also generates cards until a local backend exists.
    """

    def __init__(self, settings: Settings) -> None:
        keys = settings.gemini_api_key_list
        if not keys:
            raise ValueError(
                "SPOIN_GENERATOR=gemini requires SPOIN_GEMINI_API_KEYS "
                "(comma-separated) — none configured."
            )
        self._keys = keys
        self._model_name = settings.gemini_model
        self._quota = QuotaGovernor(key_count=len(keys), daily_target=settings.quota_daily_requests)
        self._clients: dict[int, ChatGoogleGenerativeAI] = {}

    def _client(self, key_index: int) -> ChatGoogleGenerativeAI:
        if key_index not in self._clients:
            self._clients[key_index] = ChatGoogleGenerativeAI(
                model=self._model_name,
                google_api_key=self._keys[key_index],
                temperature=0.7,
            )
        return self._clients[key_index]

    async def _next_client(self) -> ChatGoogleGenerativeAI:
        index = await self._quota.acquire_key(now=datetime.now(UTC))
        return self._client(index)

    # --------------------------------------------------------------- curriculum --

    async def generate_curriculum(
        self,
        topic_name: str,
        description: str,
        related_subtopic_hints: list[str] | None = None,
        existing_subtopics: list[str] | None = None,
    ) -> CurriculumDraft:
        client = await self._next_client()
        structured = client.with_structured_output(CurriculumDraft)
        hints_block = ""
        if related_subtopic_hints:
            hints_block = (
                "\nSubtopics from a related existing topic you may adapt (never "
                "copy verbatim, only use what's genuinely relevant):\n"
                + "\n".join(f"- {hint}" for hint in related_subtopic_hints)
                + "\n"
            )
        existing_subtopics_block = ""
        if existing_subtopics:
            existing_subtopics_block = (
                "\nSubtopics already under THIS topic (reuse the exact title "
                "verbatim if one of these already covers what you were about to "
                "propose):\n" + "\n".join(f"- {item}" for item in existing_subtopics) + "\n"
            )
        prompt = [
            ("system", _CURRICULUM_SYSTEM),
            (
                "human",
                _CURRICULUM_USER.format(
                    topic_name=topic_name,
                    description=description or "(no additional description given)",
                    hints_block=hints_block,
                    existing_subtopics_block=existing_subtopics_block,
                ),
            ),
        ]
        result = await structured.ainvoke(prompt)
        assert isinstance(result, CurriculumDraft)
        return result

    async def judge_topic_match(
        self,
        candidate_name: str,
        candidate_description: str,
        matched_topic_name: str,
        matched_subtopic_titles: list[str],
    ) -> TopicMatchVerdict:
        client = await self._next_client()
        structured = client.with_structured_output(TopicMatchVerdict)
        prompt = [
            ("system", _TOPIC_MATCH_SYSTEM),
            (
                "human",
                _TOPIC_MATCH_USER.format(
                    candidate_name=candidate_name,
                    candidate_description=candidate_description or "(none given)",
                    matched_topic_name=matched_topic_name,
                    matched_subtopic_titles=", ".join(matched_subtopic_titles) or "(none)",
                ),
            ),
        ]
        result = await structured.ainvoke(prompt)
        assert isinstance(result, TopicMatchVerdict)
        return result

    # ----------------------------------------------------------------------- cards --

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
        client = await self._next_client()
        structured = client.with_structured_output(_WireCardBatch)
        prompt = [
            ("system", _CARDS_SYSTEM),
            (
                "human",
                _CARDS_USER.format(
                    topic_name=topic_name,
                    subtopic_title=subtopic_title,
                    subtopic_description=subtopic_description,
                    difficulty=difficulty.value,
                    count=count,
                    existing_titles_block=_format_existing_titles(existing_titles),
                ),
            ),
        ]
        try:
            wire_result = await structured.ainvoke(prompt)
        except Exception as exc:
            return BatchResult(items=[], failures=[f"generate_cards call failed: {exc}"])
        assert isinstance(wire_result, _WireCardBatch)

        items: list[CardDraft] = []
        failures: list[str] = []
        for wire_card in wire_result.cards:
            try:
                items.append(
                    CardDraft(
                        title=wire_card.title,
                        # difficulty is NEVER read from the model's own output —
                        # it's what we asked for (see CardDraft's docstring: the
                        # independent judge, not this call, is what validates it).
                        canonical_title=wire_card.canonical_title or wire_card.title,
                        summary=wire_card.summary,
                        body=wire_card.body,
                        difficulty=difficulty,
                    )
                )
            except ValidationError as exc:
                failures.append(f"malformed card: {exc}")
        return BatchResult(items=items, failures=failures)

    async def judge_difficulty(self, bodies: list[str]) -> BatchResult[DifficultyVerdict]:
        if not bodies:
            return BatchResult(items=[])

        client = await self._next_client()
        structured = client.with_structured_output(_WireDifficultyBatch)
        bodies_block = "\n\n".join(f"{index}. {body}" for index, body in enumerate(bodies))
        prompt = [
            ("system", _DIFFICULTY_SYSTEM),
            ("human", _DIFFICULTY_USER.format(count=len(bodies), bodies_block=bodies_block)),
        ]
        try:
            wire_result = await structured.ainvoke(prompt)
        except Exception as exc:
            return BatchResult(items=[], failures=[f"judge_difficulty call failed: {exc}"])
        assert isinstance(wire_result, _WireDifficultyBatch)

        items: list[DifficultyVerdict] = []
        failures: list[str] = []
        for wire_verdict in wire_result.verdicts:
            try:
                items.append(
                    DifficultyVerdict(
                        index=wire_verdict.index,
                        difficulty=Difficulty(wire_verdict.difficulty),
                        factually_sound=wire_verdict.factually_sound,
                        note=wire_verdict.note,
                    )
                )
            except (ValidationError, ValueError) as exc:
                failures.append(f"malformed difficulty verdict: {exc}")
        return BatchResult(items=items, failures=failures)

    async def generate_questions(
        self, cards: list[tuple[str, str]], difficulty: Difficulty
    ) -> BatchResult[QuestionDraft]:
        if not cards:
            return BatchResult(items=[])

        client = await self._next_client()
        structured = client.with_structured_output(_WireQuestionBatch)
        cards_block = "\n\n".join(
            f"{index}. {title}\n{body}" for index, (title, body) in enumerate(cards)
        )
        prompt = [
            ("system", _QUESTIONS_SYSTEM),
            (
                "human",
                _QUESTIONS_USER.format(difficulty=difficulty.value, cards_block=cards_block),
            ),
        ]
        try:
            wire_result = await structured.ainvoke(prompt)
        except Exception as exc:
            return BatchResult(items=[], failures=[f"generate_questions call failed: {exc}"])
        assert isinstance(wire_result, _WireQuestionBatch)

        items: list[QuestionDraft] = []
        failures: list[str] = []
        for wire_question in wire_result.questions:
            try:
                items.append(
                    QuestionDraft(
                        card_index=wire_question.card_index,
                        stem=wire_question.stem,
                        options=wire_question.options,
                        correct_index=wire_question.correct_index,
                        rubric=wire_question.rubric,
                        reference_answer=wire_question.reference_answer,
                        explanation=wire_question.explanation,
                    )
                )
            except ValidationError as exc:
                failures.append(f"malformed question: {exc}")
        return BatchResult(items=items, failures=failures)
