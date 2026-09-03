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

For every BATCH-returning method (`generate_cards`, `correct_cards`, `verify_cards`,
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

`generate_curriculum` skips this — there's no meaningful "partial curriculum," so
a hard failure there is allowed to raise and fail the whole topic branch, matching
ADR-0007's framing of the curriculum pass as the highest-stakes single point of
failure. `match_topics` (ADR-0025) does use the wire/domain split, same as the
other batch methods, since a malformed verdict for one topic in the batch
shouldn't fail matching for every other topic in it.

## Real 429s vs. local ledger drift

ADR-0028's grid tracks OUR OWN belief about what's been spent, hand-copied from a
rate-limit screenshot -- it can drift from what the provider actually enforces
(confirmed live: a fresh key 0/gemini-3.7-flash cell our ledger believed had room
429'd immediately, quota already spent by out-of-band verification work). Every
call in this module goes through `_invoke_with_retry`, which treats a real 429
(`google.genai.errors.ClientError` with `.code == 429`) from the provider as ground
truth.

**But not every 429 means the same thing** (ADR-0058). Google's error envelope
distinguishes them by `quotaId`, and the two demand opposite responses:

- `...PerDay...` -- this cell really is spent until midnight. Mark it exhausted in
  the ledger (`QuotaGovernor.mark_exhausted`, so a concurrent caller also stops
  retrying it) and move to the next cell, bounded at one attempt per cell.
- `...PerMinute...` -- this cell has daily quota left and is merely being throttled;
  the envelope's `RetryInfo` even says for how long. Park it for that long
  (`QuotaGovernor.mark_rate_limited`) and let `acquire()` wait it out. Spending a
  cell's whole day on this is what ADR-0058 exists to stop.

`_classify_rate_limit` reads that distinction off the payload, and treats anything
it cannot positively identify as per-minute (ADR-0060 -- the day-long branch is the
one that costs the whole grid when guessed wrong). Only once every cell
has been genuinely exhausted does the final exception (a `QuotaExhaustedError` from
`acquire()`, or a non-quota error) propagate to the caller -- generate_curriculum
lets it raise hard (see above); every other method's existing `except Exception`
already converts it to a `BatchResult` failure.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

from google.genai.errors import ClientError, ServerError
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from pydantic import BaseModel, Field, ValidationError, model_validator

from spoin.content.ascii_library import AsciiLibraryEntry, top_candidates
from spoin.core.config import Settings
from spoin.core.db import session_scope
from spoin.domain.enums import CardType, Difficulty
from spoin.generation import prompts
from spoin.generation.base import (
    AsciiFetchQuery,
    AsciiFetchResult,
    AskTurnQuery,
    BatchResult,
    CardCorrectionQuery,
    CardCorrectionResult,
    CardDraft,
    CardPlan,
    CardRepairQuery,
    CardRepairResult,
    CardVerificationQuery,
    CardVerificationResult,
    ContentGenerator,
    CurriculumDraft,
    FreeTextGradeQuery,
    FreeTextGradeResult,
    QuestionDraft,
    TopicMatchQuery,
    TopicMatchResult,
    TopicNameQuery,
    TopicNameVerdict,
)
from spoin.generation.quota import (
    CURRENT_KEY_CLAIM,
    AllCellsThrottledError,
    AllModelsUnavailableError,
    DailyQuotaExhaustedError,
    KeyBox,
    KeyClaim,
    KeyClaimRegistry,
    QuotaExhaustedError,
    QuotaGovernor,
    key_spend_today,
    parse_ladder,
)

logger = logging.getLogger("spoin.generation.langchain_impl")

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)

#: Retries for a transient 503 (`ServerError`, "high demand") on one (key, model)
#: cell before `_invoke_with_retry` moves on to the next cell in the ladder.
_SERVER_ERROR_RETRIES = 3
_SERVER_ERROR_BASE_DELAY_S = 2.0

#: How long the background recovery probe keeps checking a timed-out model
#: before giving up and leaving it excluded for the rest of today.
_PROBE_BUDGET_SECONDS = 1200.0  # 20 minutes
#: Floor on the gap between probe attempts, so a pool with very few keys
#: doesn't hammer the provider every few seconds.
_PROBE_MIN_INTERVAL_SECONDS = 20.0

#: A `RetryInfo` delay at or under one RPM window is, by definition, describing a
#: per-minute limit -- no per-DAY exhaustion resolves itself inside a minute. Used
#: only when `quotaId` is absent, as corroborating evidence (see
#: `_classify_rate_limit`).
_PER_MINUTE_RETRY_CEILING_S = 60.0


@dataclass(frozen=True)
class _RateLimit:
    """How to react to one real 429 (ADR-0058).

    `is_daily` is the whole point: it decides between spending this cell for the
    rest of the day and parking it for `retry_after_s` seconds.

    `scope_certain` is False when neither a `quotaId` nor a `RetryInfo` was in
    the envelope and per-minute is only the safe *guess* (ADR-0060). The cell is
    still parked, but its learned rpm is NOT halved on a guess -- Google has
    been returning bare `RESOURCE_EXHAUSTED` for every 429, and halving on each
    one walked good cells down to the 1-rpm floor over a run for no real signal.
    """

    is_daily: bool
    retry_after_s: float | None
    scope_certain: bool = True


def _parse_retry_delay(raw: object) -> float | None:
    """`RetryInfo.retryDelay` arrives as a duration string (`"13s"`, `"1.5s"`)."""

    if not isinstance(raw, str) or not raw.endswith("s"):
        return None
    try:
        return float(raw[:-1])
    except ValueError:
        return None


def _classify_rate_limit(exc: ClientError) -> _RateLimit:
    """Reads a 429's envelope to tell a per-MINUTE throttle from a per-DAY
    exhaustion (module docstring, ADR-0058).

    `APIError.details` is the parsed response body, which is either the whole
    `{"error": {...}}` envelope or just the inner error object depending on which
    SDK path raised -- both shapes are handled rather than assumed.

    **Unknown scope falls back to per-MINUTE** (ADR-0060, reversing ADR-0058's
    original choice). Daily needs positive evidence; ambiguity does not get to
    spend a cell for the day.

    ADR-0058 picked the opposite default and called it conservative, weighing
    "one cell for a few hours" against "retry a genuinely dead cell hundreds of
    times". That trade was measured against the wrong failure: per-minute 429s
    do not arrive one at a time here. `gate_and_persist` fans out across every
    subtopic-tier at once (pipeline/nodes.py), so they all crowd the same RPM
    ceiling and all get throttled within seconds of each other -- and each one
    read as daily. The cost of guessing wrong is therefore the WHOLE grid for
    the rest of the day, not one cell; measured live on 2026-08-26, 64 of 66
    generator cells were slammed to their 500-request cap inside 100 seconds
    while the provider's own dashboard showed 37-87 requests actually spent.

    The opposite error stays bounded by a mechanism that already exists: a cell
    that keeps throttling still walks toward its own RPD ceiling on every
    `acquire()` (the ledger only counts up) and retires itself from rotation --
    the argument `_invoke_with_retry`'s docstring already makes for known
    per-minute 429s. So the recoverable direction is also the cheap one.

    `quotaId` remains the primary signal. `RetryInfo` is now read as evidence in
    its OWN right rather than only when no `quotaId` was sent: a delay inside one
    RPM window means per-minute whatever unrecognized quota id accompanied it,
    and a delay beyond one is positive evidence FOR daily.
    """

    raw = getattr(exc, "details", None)
    envelope = raw if isinstance(raw, dict) else {}
    inner = envelope.get("error")
    error = inner if isinstance(inner, dict) else envelope

    quota_ids: list[str] = []
    retry_after: float | None = None
    for detail in error.get("details", []) or []:
        if not isinstance(detail, dict):
            continue
        if detail.get("@type", "").endswith("RetryInfo"):
            retry_after = _parse_retry_delay(detail.get("retryDelay"))
        # A QuotaFailure carries its quotaIds one level down in `violations`;
        # the API has also been observed inlining them on the detail itself.
        violations = [v for v in detail.get("violations", []) or [] if isinstance(v, dict)]
        quota_ids.extend(str(c["quotaId"]) for c in (detail, *violations) if c.get("quotaId"))

    haystack = " ".join(quota_ids).lower()
    if "perday" in haystack:
        return _RateLimit(is_daily=True, retry_after_s=None)
    if "perminute" in haystack:
        return _RateLimit(is_daily=False, retry_after_s=retry_after)
    if retry_after is not None:
        if retry_after <= _PER_MINUTE_RETRY_CEILING_S:
            return _RateLimit(is_daily=False, retry_after_s=retry_after)
        return _RateLimit(is_daily=True, retry_after_s=None)
    # Neither signal present. Logged rather than silently guessed at, because
    # the guess below is the one thing standing between a throttle and a
    # day-long grid outage -- and because the envelope shape is the only way a
    # later session learns which quota ids this parser still doesn't know.
    logger.warning(
        "quota: a 429 arrived with no recognizable scope -- treating it as per-minute. "
        "quotaIds=%s envelope=%r",
        quota_ids or "(none)",
        error,
    )
    return _RateLimit(is_daily=False, retry_after_s=None, scope_certain=False)


# ------------------------------------------------------------- wire schemas --


class _LenientWireModel(BaseModel):
    """Gemini's structured output has been observed sending null for a plain
    `str` field the schema declares as always-present (`_WireQuestion.explanation`
    -- see the commit fixing the wrong-card-question bug for the log evidence).
    Because `with_structured_output` validates an entire batch as ONE Pydantic
    object, that single null fails validation for the WHOLE call, silently
    discarding every other valid item in the same batch, not just the bad one.

    Coerce null to the field's own default for any field declared as a plain
    `str` (never for `str | None`, which already tolerates null on purpose --
    that annotation means the model is EXPECTED to sometimes omit it) before
    validation runs, so one null string doesn't sink an otherwise-good batch."""

    @model_validator(mode="before")
    @classmethod
    def _null_str_to_default(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        for name, field in cls.model_fields.items():
            if data.get(name) is None and field.annotation is str:
                data[name] = field.default if isinstance(field.default, str) else ""
        return data


class _WireCard(_LenientWireModel):
    title: str = ""
    canonical_title: str = ""
    summary: str = ""
    body: str = ""
    #: Testing branch (non-ascii-library-generation-testing, see base.py's
    #: `CardDraft` docstring) — free-form ASCII art instead of a catalog
    #: `visual_id`. Empty string (not None — `_LenientWireModel` only coerces
    #: null for plain `str` fields) means the model chose not to draw one for
    #: this card, which is expected and fine most of the time.
    ascii_label: str = ""
    ascii_art: str = ""
    ascii_alt: str = ""


class _WireCardBatch(BaseModel):
    cards: list[_WireCard] = Field(default_factory=list)


class _WireAsciiScene(_LenientWireModel):
    #: One redrawn ASCII scene coming back from the ADR-0066 redraw call.
    #: `index` matches the number the over-budget scene was given in the
    #: redraw prompt -- that is how a redraw is attached back to its card.
    index: int = -1
    ascii_label: str = ""
    ascii_art: str = ""
    ascii_alt: str = ""


class _WireAsciiRedrawBatch(BaseModel):
    scenes: list[_WireAsciiScene] = Field(default_factory=list)


class _WireCardPlan(_LenientWireModel):
    canonical_title: str = ""
    card_type: str = ""
    asset_direction: str = ""
    content_direction: str = ""


class _WireCardPlanBatch(BaseModel):
    plans: list[_WireCardPlan] = Field(default_factory=list)


class _WireAsciiFetch(_LenientWireModel):
    #: ADR-0080: one card's pick from the curated-library candidates it was
    #: shown. `index` matches the number the card was given in the fetch prompt.
    #: `matched=False` (or an unrecognised `src_id`) => that card free-draws.
    index: int = -1
    matched: bool = False
    src_id: str = ""
    ascii_label: str = ""
    ascii_art: str = ""
    ascii_alt: str = ""


class _WireAsciiFetchBatch(BaseModel):
    scenes: list[_WireAsciiFetch] = Field(default_factory=list)


class _WireQuestion(_LenientWireModel):
    card_index: int = Field(
        default=-1,
        description=(
            "The number shown immediately before the card this question is about "
            "(e.g. '3. <title>' -> card_index=3). Must exactly match one of the "
            "input card numbers -- this is how the question gets attached back to "
            "the right card, so get it right even when you reorder your reasoning."
        ),
    )
    kind: str = "mcq"
    stem: str = ""
    options: list[str] | None = None
    correct_index: int | None = None
    rubric: str | None = None
    reference_answer: str | None = None
    explanation: str = ""


class _WireQuestionBatch(BaseModel):
    questions: list[_WireQuestion] = Field(default_factory=list)


class _WireCorrection(_LenientWireModel):
    index: int = -1
    title: str = ""
    canonical_title: str = ""
    summary: str = ""
    body: str = ""
    was_edited: bool = False
    note: str = ""


class _WireCorrectionBatch(BaseModel):
    corrections: list[_WireCorrection] = Field(default_factory=list)


class _WireVerification(_LenientWireModel):
    index: int = -1
    accepted: bool = True
    confirmed_difficulty: str = ""
    reason: str = ""


class _WireVerificationBatch(BaseModel):
    verdicts: list[_WireVerification] = Field(default_factory=list)


class _WireTopicMatchResult(BaseModel):
    request_index: int = -1
    matched_topic_id: str | None = None


class _WireTopicMatchBatch(BaseModel):
    results: list[_WireTopicMatchResult] = Field(default_factory=list)


class _WireTopicNameVerdict(_LenientWireModel):
    request_index: int = -1
    acceptable: bool = True
    reason: str = ""


class _WireTopicNameVerdictBatch(BaseModel):
    verdicts: list[_WireTopicNameVerdict] = Field(default_factory=list)


class _WireFreeTextGrade(_LenientWireModel):
    index: int = -1
    rubric_level: int = 0
    justification: str = ""


class _WireFreeTextGradeBatch(BaseModel):
    grades: list[_WireFreeTextGrade] = Field(default_factory=list)


class _WireRepair(_LenientWireModel):
    #: ADR-0076: one repaired card. `visual_slots` stays loose -- a dict or
    #: null; `_LenientWireModel` handles the null-for-str coercion on the
    #: string fields only.
    index: int = -1
    title: str = ""
    canonical_title: str = ""
    summary: str = ""
    body: str = ""
    visual_slots: dict[str, str] | None = None
    note: str = ""


class _WireRepairBatch(BaseModel):
    cards: list[_WireRepair] = Field(default_factory=list)


def _format_existing_titles(existing_titles: list[str]) -> str:
    if not existing_titles:
        return "(none yet)"
    return "\n".join(f"- {title}" for title in existing_titles)


def _format_difficulty_examples(examples: dict[Difficulty, list[str]]) -> str:
    """ADR-0030: a few example bodies per tier, shown together so the tiers
    have a concrete contrast rather than just a label. Empty (returns "") for
    a linked subtopic-tier, which gets real calibration from `builds_on`
    instead -- see `generate_cards`'s docstring in base.py."""

    blocks = []
    for difficulty in Difficulty:
        bodies = examples.get(difficulty) or []
        if not bodies:
            continue
        rendered = "\n".join(f"  - {body}" for body in bodies)
        blocks.append(f"{difficulty.value}:\n{rendered}")
    if not blocks:
        return ""
    header = "\nExample cards at each difficulty, for calibration only:\n"
    return header + "\n\n".join(blocks) + "\n"


def _format_type_quotas(type_quotas: dict[str, int]) -> str:
    """ADR-0059: the tier's shape budget, shown to the PLANNER as guidance. The
    realised mix is still counted in code afterwards -- this only aims the plan,
    it does not enforce anything (see `plan_cards` in base.py)."""

    wanted = {ct: n for ct, n in type_quotas.items() if n > 0}
    if not wanted:
        return "(no particular mix — pick whatever shape each idea actually wants)"
    return "\n".join(f"- {ct}: about {n}" for ct, n in wanted.items())


#: ADR-0080: how many curated-library candidates the ASCII fetcher is shown per
#: card. High enough that a genuinely good match is very likely in the set; low
#: enough that a tier's worth of candidates doesn't dwarf the fetch prompt (each
#: candidate carries its own small art block).
_ASCII_CANDIDATE_COUNT = 10


def _format_fetch_candidates(query: AsciiFetchQuery, candidates: list[AsciiLibraryEntry]) -> str:
    """One card's block in the ASCII fetch prompt (ADR-0080): its brief plus the
    curated-library candidates it may pick from, each with the ID the model must
    echo back in `src_id`."""

    head = [
        f"--- card {query.index} ---",
        f"concept: {query.canonical_title}",
    ]
    if query.asset_direction:
        head.append(f"scene should show: {query.asset_direction}")
    if query.content_direction:
        head.append(f"angle: {query.content_direction}")
    if not candidates:
        head.append("candidates: (none available — return matched=false)")
        return "\n".join(head)
    head.append("candidates:")
    blocks = [f'  [ID: {c.id}] "{c.title}"\n  ```\n{c.art}\n  ```' for c in candidates]
    return "\n".join(head) + "\n" + "\n".join(blocks)


def _format_plans(plans: list[CardPlan]) -> str:
    """ADR-0059: this writer call's slice of the tier's briefs. Returns "" when
    unplanned (the hero call, or a planning failure) so `CARDS_USER` renders
    exactly as it did before the planning stage existed.

    ADR-0080: an `ascii` brief carries its art disposition -- "PROVIDED" when the
    fetcher matched it to a curated-library scene (the writer leaves the ascii
    fields empty; the pipeline attaches the scene after this call), or "draw
    one" when no scene fit (the writer free-draws per ASCII_INSTRUCTIONS)."""

    if not plans:
        return ""

    blocks = []
    for n, plan in enumerate(plans, start=1):
        lines = [
            f"--- card {n} ---",
            f"concept: {plan.canonical_title}",
            f"form: {plan.card_type}",
        ]
        if plan.asset_direction:
            lines.append(f"what its code/diagram/art should show: {plan.asset_direction}")
        if plan.content_direction:
            lines.append(
                f"angle (what makes it different from the others): {plan.content_direction}"
            )
        if plan.card_type == CardType.ASCII.value:
            lines.append(
                "art: PROVIDED — a curated scene is already chosen and captioned for "
                "this card; leave ascii_label / ascii_art / ascii_alt EMPTY"
                if plan.fetched_scene is not None
                else "art: draw one — no library scene fit; draw a gag per the ASCII rules"
            )
        blocks.append("\n".join(lines))
    return (
        "\nThe briefs for the cards to write, one card each, in this order:\n"
        + "\n\n".join(blocks)
        + "\n"
    )


def _format_avoid_bodies(avoid_bodies: list[str]) -> str:
    """ADR-0030 addendum: full body text of this subtopic-tier's most recent
    near-duplicate rejections from a prior run -- shown as content to avoid
    reproducing, not as titles already covered."""

    if not avoid_bodies:
        return ""
    bodies = "\n\n".join(
        f"--- rejected as a near-duplicate {n + 1} ---\n{body}"
        for n, body in enumerate(avoid_bodies)
    )
    return (
        "\nThese were REJECTED in an earlier run as near-duplicates of other cards -- "
        "do not write anything this similar again, even reworded:\n" + bodies + "\n"
    )


def _format_rejection_feedback(rejection_feedback: list[tuple[str, str]]) -> str:
    """`rejection_feedback` is (body, reason) pairs -- unlike near-duplicate
    rejections (an algorithmic similarity score, no reasoning), pass-2
    verification rejections carry a real reason the judge model itself gave,
    so it's shown alongside the body rather than just the body."""

    if not rejection_feedback:
        return ""
    blocks = "\n\n".join(
        f"--- rejected {n + 1} (reviewer's reason: {reason}) ---\n{body}"
        for n, (body, reason) in enumerate(rejection_feedback)
    )
    return (
        "\nThese were REJECTED in an earlier run by the reviewer, with its stated "
        "reason -- fix the actual problem the reason describes, don't just reword "
        "the same card:\n" + blocks + "\n"
    )


def _format_existing_question_stems(existing_stems: list[str]) -> str:
    """`existing_stems` is every OTHER active question already written for this
    exact subtopic-tier -- shown so the writer doesn't repeat a question angle
    already covered, same "show what exists" principle `_format_existing_titles`
    already applies to card generation."""

    if not existing_stems:
        return ""
    lines = "\n".join(f"- {stem}" for stem in existing_stems)
    return (
        "\nThis subtopic's quiz already asks (do not repeat any of these, even "
        f"reworded):\n{lines}\n"
    )


def _format_builds_on(builds_on: list[str]) -> str:
    if not builds_on:
        return ""
    bodies = "\n\n".join(
        f"--- lower-tier card {n + 1} ---\n{body}" for n, body in enumerate(builds_on)
    )
    return f"\nBuilds on (lower-difficulty cards already written for this subtopic):\n{bodies}\n"


#: Free-form generator-drawn ASCII art (ADR-0042) carries the same width budget
#: ADR-0021's scene library enforced at catalog-load time — a phone renders
#: roughly 38-42 monospace columns and art that wraps is destroyed, not
#: degraded. The constraint is still enforced outside the model; what changed
#: (ADR-0066) is the response to a violation: the drawing is handed back to be
#: redrawn within budget, and only a card whose art is STILL over budget after
#: `ascii_redraw_attempts` tries is rejected — no more silent drop-the-visual.
_ASCII_MAX_WIDTH = 40


def _ascii_over_budget_lines(art: str) -> list[tuple[int, int]]:
    """`(line number, width)` for every line of `art` wider than the budget,
    1-indexed. Empty list means the art fits. Used both to decide whether a
    redraw is needed and to tell the model exactly which lines to tighten."""

    return [
        (n, len(line))
        for n, line in enumerate(art.split("\n"), start=1)
        if len(line) > _ASCII_MAX_WIDTH
    ]


#: `visual_slots.art` is meant to hold raw ASCII, but the model intermittently
#: leaves the ```lang fence it drew the scene inside around it -- left alone,
#: those backticks rendered as literal text at the top of the card (the
#: original report behind this fix: a card's lead visual showing a stray
#: ` ```text ` line). Stripped here, deterministically, rather than relied on
#: from the prompt alone -- CLAUDE.md's "trusted for taste, never for
#: constraints": the prompt already asks for no fence, this is the check.
_ASCII_FENCE_WRAPPER = re.compile(r"^```[a-zA-Z0-9_-]*\n(.*?)\n?```$", re.DOTALL)


def _strip_ascii_fence_wrapper(art: str) -> str:
    stripped = art.strip("\n")
    match = _ASCII_FENCE_WRAPPER.match(stripped.strip())
    return match.group(1) if match is not None else stripped


#: Loose identity for "is this the same scene" -- whitespace differences
#: between `visual_slots.art` and a copy of it inside `body` are common (they
#: come from two different generation slots), so exact string equality misses
#: most real duplicates. Same normalization as the frontend's
#: `looseFenceKey` in Card.tsx -- the two must agree on what "the same
#: scene" means.
def _loose_scene_key(text: str) -> str:
    return re.sub(r"\s+", "", text)


#: A fenced block, keeping enough to both classify it (content/archetype.py's
#: own logic, duplicated in spirit here since importing it would need the
#: language tag reasoning it already encodes) and remove it verbatim from
#: `body`.
_FENCE_BLOCK = re.compile(r"```[a-zA-Z0-9_-]*\n.*?```\n?", re.DOTALL)

#: Same shape as `_FENCE_BLOCK`, but captures the language tag and inner
#: content separately -- used to find a specific fence (e.g. ```mermaid)
#: rather than to remove one wholesale.
_FENCE = re.compile(r"```([a-zA-Z0-9_-]*)\n(.*?)```", re.DOTALL)


def _strip_duplicate_scene_from_body(body: str, art: str) -> str:
    """Removes the FIRST fenced block in `body` whose content loosely matches
    `art` -- the prompt (ASCII_INSTRUCTIONS) tells the model not to redraw its
    own scene into `body`, but a card is not trusted to have honored that on
    its own. A body with no matching fence is returned unchanged."""

    art_key = _loose_scene_key(art)
    if not art_key:
        return body

    for match in _FENCE_BLOCK.finditer(body):
        fenced = match.group(0)
        inner = fenced.split("\n", 1)[1].rsplit("```", 1)[0]
        if _loose_scene_key(inner) != art_key:
            continue
        # Remove exactly this one match and collapse the blank run it leaves
        # behind -- every other fence in `body` (a genuinely different code
        # or diagram block) is left untouched.
        result = body[: match.start()] + body[match.end() :]
        return re.sub(r"\n{3,}", "\n\n", result).strip()

    return body


def _finalize_ascii_fields(
    label: str, art: str, alt: str, *, src_id: str = ""
) -> tuple[str, dict[str, str]]:
    """Assemble the `visual_id` / `visual_slots` pair from art already known to
    be non-empty and within budget (originally or after a redraw).

    `src_id` (ADR-0080) is the curated-library entry a fetched scene was adapted
    from -- carried in `visual_slots` so the card records which library piece it
    used, and that piece is then excluded from every later fetch in the topic.
    Empty for a writer-drawn scene (the free-draw fallback and the hero card)."""

    slots = {"art": art, "alt": alt}
    if src_id:
        slots["src_id"] = src_id
    return (label.strip() or "untitled-scene")[:64], slots


#: ADR-0067: diagram cards write ```mermaid, and the prompt is trusted for
#: WHAT the diagram shows, never for whether the syntax is valid mermaid --
#: same "trusted for taste, never for constraints" line as the ASCII width
#: budget above. This is deliberately a light structural check, not a real
#: parser: it exists to catch the failure modes an LLM actually produces (an
#: empty fence, a diagram-type keyword typo'd or omitted, no edges at all,
#: unbalanced brackets from a truncated generation) without maintaining a
#: mermaid grammar in Python. The client (`MermaidBlock.tsx`) runs the real
#: parser at render time and falls back to showing the source verbatim on
#: failure -- this check exists to keep an obviously-broken diagram from
#: reaching that fallback silently on every single viewer, not to guarantee
#: perfect syntax.
_MERMAID_DIAGRAM_TYPES = (
    "flowchart",
    "graph",
    "sequencediagram",
    "statediagram",
    "statediagram-v2",
    "classdiagram",
    "erdiagram",
    "gantt",
    "pie",
    "timeline",
    "journey",
    "mindmap",
    "quadrantchart",
)

#: A relationship of some kind: an arrow (flowchart/graph), a `->`/`->>`/`-->>`
#: message (sequenceDiagram), or a `-->`/`:` transition (stateDiagram). Loose
#: on purpose -- this only needs to rule out a diagram with declared nodes and
#: nothing connecting them, not validate the exact arrow grammar per type.
_MERMAID_EDGE_RE = re.compile(r"-{1,3}>|->>|--x|--o|:::|\.\.>|:")

#: A pipe-delimited edge label in a flowchart/graph (`A -->|label| B`). Mermaid's
#: grammar rejects an unquoted `(`, `)`, `[`, `]`, `{`, or `}` inside one, and a
#: single bad label fails the whole diagram -- card `0afd7193` shipped this way
#: before this check existed (`-->|Screen Pixels (e.g., 500, 300)|`). A label
#: wrapped in double quotes (`|"… (…)"|`) is valid, so only the unquoted case is
#: flagged; `[(…)]` and other bracketed NODE shapes are untouched because they
#: never sit between pipes.
_MERMAID_PIPE_LABEL_RE = re.compile(r"\|([^|\n]*)\|")
_MERMAID_LABEL_PUNCT_RE = re.compile(r"[()\[\]{}]")


def _mermaid_structural_issue(source: str) -> str | None:
    """Returns a short reason string if `source` fails the light structural
    check, or `None` if it passes. Deliberately permissive -- a false
    rejection costs a whole card; a false pass costs nothing beyond what the
    client's own fallback already covers."""

    lines = [line for line in source.split("\n") if line.strip()]
    if not lines:
        return "empty mermaid block"

    first = lines[0].strip().lower()
    # `flowchart TD` / `graph LR` / etc. carry a direction after the type; every
    # other diagram type is the bare keyword, optionally with a title after it.
    first_word = first.split()[0] if first.split() else ""
    if first_word not in _MERMAID_DIAGRAM_TYPES:
        return f"first line {lines[0].strip()!r} does not name a known mermaid diagram type"

    if first_word in ("flowchart", "graph") and not _MERMAID_EDGE_RE.search(source):
        return "flowchart/graph has no edges connecting its nodes"

    opens = source.count("[") + source.count("(") + source.count("{")
    closes = source.count("]") + source.count(")") + source.count("}")
    if opens != closes:
        return f"unbalanced brackets ({opens} opening vs {closes} closing)"

    for label in _MERMAID_PIPE_LABEL_RE.findall(source):
        stripped = label.strip()
        if len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"':
            continue
        if _MERMAID_LABEL_PUNCT_RE.search(stripped):
            return (
                f"edge label {stripped!r} has unquoted parens/brackets -- "
                "wrap the label in double quotes"
            )

    return None


def _ascii_redraw_prompt(
    pending: dict[int, tuple[str, str, str]], *, escalated: bool
) -> list[tuple[str, str]]:
    """Build the batched redraw call (ADR-0066) for every scene still over
    budget. `escalated` is set on the second and later attempts, when a prior
    redraw of these same scenes came back too wide anyway."""

    blocks: list[str] = []
    for index, (label, art, _alt) in pending.items():
        violations = (
            ", ".join(
                f"line {n} is {width} cols ({width - _ASCII_MAX_WIDTH} over)"
                for n, width in _ascii_over_budget_lines(art)
            )
            or "one or more lines exceed the limit"
        )
        blocks.append(
            f"Scene index {index} (label: {label or 'unlabeled'})\n"
            f"Lines over {_ASCII_MAX_WIDTH} columns: {violations}\n"
            f"Current drawing:\n```\n{art}\n```"
        )
    escalation_block = (
        "A previous redraw of these scenes STILL came back over "
        f"{_ASCII_MAX_WIDTH} columns. Be more aggressive now — drop a caption, "
        "stack the panels vertically, or simplify the drawing rather than "
        "exceed the limit even once.\n\n"
        if escalated
        else ""
    )
    return [
        ("system", prompts.CARDS_ASCII_REDRAW_SYSTEM),
        (
            "human",
            prompts.CARDS_ASCII_REDRAW_USER.format(
                escalation_block=escalation_block,
                count=len(pending),
                scenes_block="\n\n".join(blocks),
            ),
        ),
    ]


def _format_free_text_grade_query(query: FreeTextGradeQuery) -> str:
    # The <student_answer> delimiter is the load-bearing part of the prompt
    # injection defence (see _FREE_TEXT_GRADE_SYSTEM) — everything the user
    # typed lives inside it and nowhere else in this block, so there is no
    # position in the prompt where their text is adjacent to an instruction
    # without an explicit "this is data" boundary around it.
    return (
        f"{query.index}. Question: {query.stem}\n"
        f"   Rubric: {query.rubric}\n"
        f"   Reference answer: {query.reference_answer}\n"
        f"   <student_answer>\n{query.user_answer}\n   </student_answer>"
    )


def _format_topic_match_query(query: TopicMatchQuery) -> str:
    if query.candidates:
        candidates_block = "\n".join(
            f"     - id={c.topic_id} name={c.name} similarity={c.similarity:.2f}"
            for c in query.candidates
        )
    else:
        candidates_block = "     (none)"
    return (
        f"{query.request_index}. Candidate: {query.name}\n"
        f"   Description: {query.description or '(none given)'}\n"
        f"   Existing topics:\n{candidates_block}"
    )


class GeminiContentGenerator(ContentGenerator):
    """ADR-0008/ADR-0028/ADR-0029/ADR-0030: cloud, quota-bound, two
    independently-rotating pools.

    `_thinking` covers curriculum, topic matching, the two-pass quality gate
    (`correct_cards`/`verify_cards`, ADR-0030), and quiz grading — calls where
    a weak model has a real consequence (ADR-0008's "trusted for taste, never
    for constraints" rule) — and walks the (newer, better) thinking ladder.
    `_generator` covers `generate_cards` AND `generate_questions` (ADR-0029):
    both are high-volume, one-per-item prose calls, so they share the cheaper,
    higher-throughput lite ladder instead of competing with the thinking
    pool's much smaller daily budget. Each pool has its own key x model quota
    grid (ADR-0028) — a call to one never affects the other's remaining
    budget.
    """

    def __init__(self, settings: Settings) -> None:
        keys = settings.gemini_api_key_list
        if not keys:
            raise ValueError(
                "SPOIN_GENERATOR=gemini requires SPOIN_GEMINI_API_KEYS "
                "(comma-separated) — none configured."
            )
        self._keys = keys
        self._request_timeout_s = settings.gemini_request_timeout_seconds
        self._ascii_redraw_attempts = settings.ascii_redraw_attempts
        #: ONE registry across BOTH pools (ADR-0074): the pools are separate
        #: ladders over the same physical keys, so a claim only one of them
        #: could see would let another group's judging land on the key this
        #: group is writing cards with.
        self._claims = KeyClaimRegistry(len(keys))
        self._thinking = QuotaGovernor(
            key_count=len(keys),
            ladder=parse_ladder(settings.gemini_thinking_ladder),
            reserve_rungs=settings.gemini_thinking_reserve_rungs,
            claims=self._claims,
        )
        #: No reserve on the generator pool. The reserve exists because a weak
        #: model doing curriculum or judging degrades the corpus (ADR-0008), and
        #: because thinking RPD is small (20/cell). Card and question writing is
        #: 500/cell and independently gated afterwards -- there is nothing to
        #: hold back and nothing that would notice.
        self._generator = QuotaGovernor(
            key_count=len(keys),
            ladder=parse_ladder(settings.gemini_generator_ladder),
            claims=self._claims,
        )
        self._clients: dict[tuple[int, str], ChatGoogleGenerativeAI] = {}
        #: (id(pool), model) -> the running recovery-probe task for that
        #: model, if any -- keeps a stalled model from spawning a second probe
        #: on every subsequent timeout while the first one is still running.
        self._active_probes: dict[tuple[int, str], asyncio.Task[None]] = {}

    @asynccontextmanager
    async def claimed_key_scope(self, *, box: KeyBox | None = None) -> AsyncIterator[None]:
        """ADR-0074: everything called inside this block runs on ONE key.

        The claim starts UNBOUND. Binding it here would need a key chosen
        without consulting the ledger, and the ordering that matters --
        least-spent first -- already lives in `acquire()`; the first call made
        inside the scope binds it there instead, using the same query every
        other key choice uses.

        With `box` (ADR-0082) that binding scan -- and the later move to a
        fresher key -- sees only the topic's own keys. Without it the claim
        ranges over the whole pool, exactly as ADR-0074 described.

        The claim is released even when the body raises, which is what keeps a
        failed subtopic group from parking a key for the rest of the run. Both
        pools share `self._claims`, so releasing frees the key for thinking and
        generator work alike.
        """

        claim = KeyClaim(box=box)
        token = CURRENT_KEY_CLAIM.set(claim)
        try:
            yield
        finally:
            CURRENT_KEY_CLAIM.reset(token)
            await self._claims.release(claim)

    async def lease_key_box(self, size: int) -> KeyBox:
        """Take `size` keys from the pool as one topic's box for its whole run
        (ADR-0082), coldest first so a day of passes spreads across the pool
        instead of re-boxing keys 0..N every time (ADR-0065's principle, applied
        to boxes: a box is held for a run, so first-fit from key 0 would burn the
        low indices down pass after pass and leave the high ones permanently
        cold). May return fewer keys when the pool is tight -- see
        `KeyClaimRegistry.lease_box`."""

        async with session_scope() as session:
            spent = await key_spend_today(session, key_count=len(self._keys), now=datetime.now(UTC))
        coldest_first = sorted(range(len(self._keys)), key=lambda k: (spent.get(k, 0), k))
        return self._claims.lease_box(size, prefer=coldest_first)

    async def release_key_box(self, box: KeyBox) -> None:
        """Return a topic's box to the pool (ADR-0082)."""

        await self._claims.release_box(box)

    def _client(self, key_index: int, model: str) -> ChatGoogleGenerativeAI:
        cache_key = (key_index, model)
        if cache_key not in self._clients:
            self._clients[cache_key] = ChatGoogleGenerativeAI(
                model=model,
                google_api_key=self._keys[key_index],
                temperature=0.7,
                # Without this, a stalled call (open connection, no response)
                # hangs forever -- see config.py's gemini_request_timeout_seconds
                # docstring. `_invoke_with_retry` treats the resulting timeout
                # like any other cell failure and rotates to the next one.
                timeout=self._request_timeout_s,
                # LangChain's own client retries a 429 in-place with
                # exponential backoff (default max_retries=6, ~2 minutes of
                # wall time) before ever raising a ClientError up to
                # _invoke_with_retry -- that defeats the whole point of this
                # module's own cross-cell fallback (see module docstring),
                # which wants to move to the next (key, model) immediately on
                # a real 429, not sit retrying a cell it's about to mark
                # exhausted anyway.
                max_retries=0,
            )
        return self._clients[cache_key]

    async def _invoke_with_backoff(
        self,
        structured: object,
        prompt: list[tuple[str, Any]],
        *,
        pool: QuotaGovernor,
        key_index: int,
        model: str,
    ) -> Any:
        """A 503 (`ServerError`, status `UNAVAILABLE`) means the model itself is
        overloaded -- Google's own docs describe this as "usually temporary."
        It has nothing to do with OUR quota, so unlike a real 429 it does not
        mark the cell exhausted; instead retry the SAME cell a few times with
        exponential backoff before `_invoke_with_retry` gives up on it and
        rotates to the next cell in the ladder.

        A 504 (also a `ServerError` -- confirmed live: `gemini_request_timeout_seconds`
        firing on a genuinely stalled call surfaces as `google.genai.errors.ServerError`
        with `.code == 504`, NOT a distinct exception class) skips this same-cell
        retry entirely: the call already burned its FULL timeout budget once,
        so retrying it again would just burn that budget again for nothing --
        raise immediately and let `_invoke_with_retry` move to the next cell.

        This is the module's single outbound send site, so it is also where the
        per-minute window is stamped (`note_request_sent`, ADR-0058): at the
        moment the request actually leaves, not when `acquire()` reserved the
        cell some seconds earlier. Being inside the retry loop means a 503
        retried on this same cell is counted too -- it is another real request,
        and the reservation only covered the first one."""

        delay = _SERVER_ERROR_BASE_DELAY_S
        for attempt in range(1, _SERVER_ERROR_RETRIES + 1):
            try:
                await pool.note_request_sent(key_index, model, now=datetime.now(UTC))
                return await structured.ainvoke(prompt)  # type: ignore[attr-defined]
            except ServerError as exc:
                if exc.code == 504 or attempt == _SERVER_ERROR_RETRIES:
                    raise
                logger.warning(
                    "quota: key=%d model=%s got a transient 503 (high demand, attempt "
                    "%d/%d) -- retrying in %.0fs",
                    key_index,
                    model,
                    attempt,
                    _SERVER_ERROR_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable: loop always returns or raises on its last attempt")

    @staticmethod
    def _claim_for_scope(key_scope: Literal["sticky", "box", "pool"]) -> KeyClaim | None:
        """Resolve `_invoke_with_retry`'s `key_scope` against the ambient claim.

        `sticky` returns the claim as-is (or None when none is set -- curriculum,
        topic matching, grading, every test). `pool` forces None: least-spent
        over the whole pool. `box` keeps the claim's box but strips the pin --
        a fresh `sticky=False` claim so this one call picks the least-spent key
        in the box and the next call re-picks, rather than all of a unit's
        calls landing on the key the first one bound.
        """

        current = CURRENT_KEY_CLAIM.get()
        if key_scope == "pool" or current is None:
            return None
        if key_scope == "box":
            return KeyClaim(box=current.box, sticky=False)
        return current

    async def _invoke_with_retry(
        self,
        pool: QuotaGovernor,
        schema: type[_SchemaT],
        prompt: list[tuple[str, Any]],
        *,
        key_scope: Literal["sticky", "box", "pool"] = "sticky",
    ) -> _SchemaT:
        """Acquire a `(key, model)` cell from `pool` and call it; a REAL 429
        means our local ledger's belief disagreed with the provider's actual
        state (see this module's docstring). Mark that exact cell exhausted
        and retry the next cell in the grid, bounded at one attempt per
        `(key, model)`.

        **`max_attempts` counts cells BURNED, not calls made** (ADR-0058). A
        per-minute 429 doesn't use a cell up -- it parks it for a few seconds --
        so counting it here would let a brief throttle burn the whole grid's
        attempt budget and surface as a hard failure.

        **Throttle retries are bounded by evidence, not by erosion** (ADR-0065).
        They used to be bounded by quota erosion: each retry's `acquire()`
        billed a cell's RPD and never gave it back, so a throttle storm walked
        the whole grid toward its ceiling and terminated by exhausting it. That
        worked, and cost a full day's budget to do it.

        The charge is refunded now, so the loop needs a real stopping condition
        instead. It counts only throttles arriving on a cell ALREADY at its rpm
        floor, because those are the only ones that say anything about the
        provider: a 429 on a cell we had not yet slowed down means our pacing
        was too fast, and AIMD's response is to slow down and try again -- that
        is the mechanism working, not failing. A 429 on a cell already down to
        one request per minute has no such answer; there is no slower to go.
        `grid_size` of those in a row, with no success in between, means every
        cell in the grid refused us at the slowest pace we have. Any success
        resets the count."""

        max_attempts = pool.key_count * len(pool.ladder)
        # Not a tuning knob: one full sweep of the grid, all of it floored and
        # all of it still refusing, is the smallest streak that distinguishes
        # "this cell is busy" from "nothing here will serve us right now".
        grid_size = max_attempts
        cells_burned = 0
        floored_throttles = 0
        last_server_error: ServerError | None = None
        # A 503 overload -- and a 504 timeout, see the ServerError handler
        # below -- is treated as per-MODEL, not per-key (every key hits the
        # same wall) -- once a model has stayed UNAVAILABLE through its own
        # backoff, exclude it entirely so the next acquire() jumps straight
        # to the next model in the ladder instead of burning through every
        # remaining key on a model that's already proven overloaded.
        unavailable_models: set[str] = set()
        while cells_burned < max_attempts:
            attempt = cells_burned + 1
            try:
                key_index, model = await pool.acquire(
                    now=datetime.now(UTC),
                    exclude_models=frozenset(unavailable_models),
                    # ADR-0074's key claim, three ways (see `KeyClaim.sticky`):
                    #  "sticky" -- the claim as set by `claimed_key_scope`;
                    #     pins the unit to one key. Also the no-claim callers
                    #     (curriculum, matching, grading), which just get the
                    #     whole pool.
                    #  "box"   -- keep the claim's BOX scope but not its pin, so
                    #     a unit's burst of calls (a tier's plan + per-type
                    #     drafts + ascii) spreads least-spent across its box
                    #     instead of hammering one key past 15 rpm. Card
                    #     writing, planning, ascii, questions.
                    #  "pool"  -- drop the claim entirely; least-spent over the
                    #     whole pool. The thinking gate (`correct_cards` /
                    #     `verify_cards`), whose rpm-5 calls must spread widest.
                    claim=self._claim_for_scope(key_scope),
                )
            except QuotaExhaustedError:
                # Every remaining rung was excluded as overloaded, not actually
                # quota-exhausted -- surface the real 503 instead of a
                # misleading "quota exhausted" when no cell was ever marked so.
                if last_server_error is not None:
                    raise last_server_error from None
                raise
            client = self._client(key_index, model)
            structured = client.with_structured_output(schema)
            try:
                async with pool.cell_lock(key_index, model):
                    result = await self._invoke_with_backoff(
                        structured, prompt, pool=pool, key_index=key_index, model=model
                    )
            except (ClientError, ChatGoogleGenerativeAIError) as exc:
                # The new `google-genai` SDK (langchain-google-genai>=4.0) has no
                # dedicated ResourceExhausted class -- every 4xx is a ClientError,
                # distinguished by `.code`/`.status` from the API's error envelope
                # (`{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", ...}}`).
                # BUT `ChatGoogleGenerativeAI._agenerate` catches that `ClientError`
                # itself and unconditionally re-wraps it as a generic
                # `ChatGoogleGenerativeAIError` (langchain_google_genai's own
                # `_handle_client_error`) before it ever reaches this method -- a
                # raw `ClientError` from `structured.ainvoke()` essentially never
                # happens in practice. The real error survives as `__cause__`, so
                # unwrap that to find the actual `.code` this branch needs.
                real_error = exc if isinstance(exc, ClientError) else exc.__cause__
                # 429: quota exhausted for this key/project.
                # 401/403: key disabled, service account invalid, or unauthenticated.
                # In either case, mark this cell exhausted for today and rotate to the next key.
                # Anything else (e.g. malformed request, bad schema) re-raises immediately.
                if not isinstance(real_error, ClientError) or (
                    real_error.code not in (401, 403, 429)
                ):
                    raise
                if real_error.code == 429:
                    limit = _classify_rate_limit(real_error)
                    if not limit.is_daily:
                        # Throttled, not spent. Park the cell for as long as the
                        # provider asked, refund the day's charge and narrow the
                        # cell's learned rpm (all three inside mark_rate_limited,
                        # ADR-0058 + ADR-0065), then try another -- without
                        # burning a cell.
                        # Read BEFORE mark_rate_limited, which is what shrinks
                        # it: the question is whether this call went out at a
                        # pace we had already bottomed out, not what we are
                        # about to reduce it to.
                        was_floored = pool.is_at_rpm_floor(key_index, model)
                        await pool.mark_rate_limited(
                            key_index,
                            model,
                            now=datetime.now(UTC),
                            retry_after_s=limit.retry_after_s,
                            shrink_rpm=limit.scope_certain,
                        )
                        if was_floored:
                            floored_throttles += 1
                            if floored_throttles >= grid_size:
                                raise AllCellsThrottledError(
                                    f"{floored_throttles} consecutive per-minute 429s at the "
                                    f"one-request-per-minute floor with no success -- every "
                                    f"cell in the {pool.key_count}x{len(pool.ladder)} grid is "
                                    f"refusing us at the slowest pace we have. Daily quota "
                                    f"remains; this is throttling, not exhaustion."
                                ) from exc
                        continue
                    logger.warning(
                        "quota: key=%d model=%s got a per-day 429 from the provider despite "
                        "our ledger showing room -- marking exhausted, trying next cell "
                        "(cell %d/%d): %s",
                        key_index,
                        model,
                        attempt,
                        max_attempts,
                        exc,
                    )
                else:
                    logger.warning(
                        "quota: key=%d model=%s got auth error %d (%s) -- marking exhausted, "
                        "trying next cell (cell %d/%d)",
                        key_index,
                        model,
                        real_error.code,
                        getattr(real_error, "message", str(exc)),
                        attempt,
                        max_attempts,
                    )
                await pool.mark_exhausted(key_index, model, now=datetime.now(UTC))
                cells_burned += 1
                continue
            except ServerError as exc:
                # Persistently UNAVAILABLE even after _invoke_with_backoff's own
                # retries (or, for a 504, on the very first attempt -- see that
                # method's docstring) -- this cell's ledger entry is untouched
                # (neither 503 nor 504 is a quota condition). Exclude the whole
                # MODEL, not just this key or this call: a 503 overload hits
                # every key alike, and a 504 stall observed on one key isn't
                # evidence the others would respond any faster either. The
                # exclusion outlives this call (`pool.exclude_model`, not just
                # the local `unavailable_models` below) and a background probe
                # checks in the background whether it's come back, cycling
                # through a different key each attempt.
                logger.warning(
                    "quota: model=%s still UNAVAILABLE after backoff on key=%d -- "
                    "excluding this model, trying next one (attempt %d/%d): %s",
                    model,
                    key_index,
                    attempt,
                    max_attempts,
                    exc,
                )
                await pool.exclude_model(
                    model,
                    now=datetime.now(UTC),
                    # The probe about to start is what will clear this row; the
                    # exclusion should therefore outlive exactly as long as that
                    # probe is entitled to take, and no longer (ADR-0065).
                    expires_in_s=_PROBE_BUDGET_SECONDS,
                    reason=str(exc),
                )
                self._start_recovery_probe(pool, model)
                unavailable_models.add(model)
                last_server_error = exc
                cells_burned += 1
                continue
            assert isinstance(result, schema)
            # A call got through: the cell can carry a little more than we last
            # believed (AIMD's additive increase), and the throttle streak that
            # would otherwise end this loop is genuinely broken, not merely
            # paused (ADR-0065).
            pool.note_call_succeeded(key_index, model)
            floored_throttles = 0
            return result
        if last_server_error is not None:
            # Every cell in the grid stayed UNAVAILABLE -- NOT a quota exhaustion
            # (no cell was marked exhausted), so re-raise the actual 503 rather
            # than the misleading "unreachable" assertion below.
            raise last_server_error
        # Every cell in the grid has now been marked exhausted by the loop above,
        # so this is the same error acquire() would have raised directly had our
        # ledger been accurate from the start. Raised here rather than by calling
        # acquire() again: a re-acquire would spend a ledger slot on a call we
        # have no intention of making, and -- now that a per-minute 429 leaves a
        # cell alive but cooling -- could block on `acquire()`'s self-pacing sleep
        # instead of returning the failure the caller is waiting on.
        raise DailyQuotaExhaustedError(
            f"All {pool.key_count} key(s) x {len(pool.ladder)} model(s) exhausted "
            f"for {datetime.now(UTC).date()} -- every cell was marked exhausted by a "
            f"per-day 429 or an auth failure during this call"
        )

    def _start_recovery_probe(self, pool: QuotaGovernor, model: str) -> None:
        """Fire-and-forget: called the moment `_invoke_with_retry` excludes a
        model after a timeout. Only ever one probe in flight per (pool,
        model) -- a second timeout on the same model while a probe is already
        running just excludes it again (already true) rather than piling up
        duplicate probes."""

        key = (id(pool), model)
        existing = self._active_probes.get(key)
        if existing is not None and not existing.done():
            return
        self._active_probes[key] = asyncio.create_task(self._probe_model(pool, model))

    async def _probe_model(self, pool: QuotaGovernor, model: str) -> None:
        """Runs off the request path, checking whether a model excluded after
        a timeout has come back. Cycles through a DIFFERENT key each attempt
        (not just the one that originally stalled) so a single bad key isn't
        mistaken for the whole model being down, spaced out so every
        configured key gets tried at least once inside the budget. A
        successful probe call counts against today's ledger exactly like a
        real acquired call (`record_probe_attempt`) -- it is one real request
        against the provider, not free reconnaissance.

        Only matters for as long as this process stays alive -- fine for the
        API process and local dev's `--watch` worker loop, but the production
        worker is a short-lived batch cron pass (apps/worker/README.md) that
        will usually exit before a 20-minute probe finishes; the next cron
        run just rediscovers the same model fresh, at the cost of one more
        timeout.
        """

        interval = max(_PROBE_MIN_INTERVAL_SECONDS, _PROBE_BUDGET_SECONDS / len(self._keys))
        deadline = time.monotonic() + _PROBE_BUDGET_SECONDS
        tried_keys: set[int] = set()
        attempt = 0
        while time.monotonic() < deadline:
            key_index = attempt % len(self._keys)
            attempt += 1
            tried_keys.add(key_index)
            await pool.record_probe_attempt(key_index, model, now=datetime.now(UTC))
            try:
                async with pool.cell_lock(key_index, model):
                    client = self._client(key_index, model)
                    await pool.note_request_sent(key_index, model, now=datetime.now(UTC))
                    await client.ainvoke([("human", "ping")])
            except Exception as exc:
                logger.info(
                    "probe: key=%d model=%s still unavailable (%s) -- next attempt "
                    "in %.0fs with a different key",
                    key_index,
                    model,
                    exc,
                    interval,
                )
                await asyncio.sleep(interval)
                continue
            logger.warning(
                "probe: key=%d model=%s responded -- resuming normal rotation "
                "(today's ledger counts are kept as-is, not reset)",
                key_index,
                model,
            )
            await pool.include_model(model)
            return

        logger.warning(
            "probe: model=%s did not respond from any of %d key(s) tried within %.0fs -- "
            "marking every tried key exhausted, staying excluded for the rest of today",
            model,
            len(tried_keys),
            _PROBE_BUDGET_SECONDS,
        )
        for key_index in tried_keys:
            await pool.mark_exhausted(key_index, model, now=datetime.now(UTC))
        # The ledger now keeps every TRIED key out of rotation for the rest of
        # today on its own; releasing the manual flag only matters for a key
        # this probe never got to (e.g. a key pool larger than fit in the
        # budget), which real traffic is then free to discover for itself.
        await pool.include_model(model)

    # --------------------------------------------------------------- curriculum --

    async def generate_curriculum(
        self,
        topic_name: str,
        description: str,
        existing_subtopics: list[str] | None = None,
    ) -> CurriculumDraft:
        existing_subtopics_block = ""
        if existing_subtopics:
            existing_subtopics_block = (
                "\nSubtopics already under THIS topic (reuse the exact title "
                "verbatim if one of these already covers what you were about to "
                "propose):\n" + "\n".join(f"- {item}" for item in existing_subtopics) + "\n"
            )
        prompt = [
            ("system", prompts.CURRICULUM_SYSTEM),
            (
                "human",
                prompts.CURRICULUM_USER.format(
                    topic_name=topic_name,
                    description=description or "(no additional description given)",
                    existing_subtopics_block=existing_subtopics_block,
                ),
            ),
        ]
        return await self._invoke_with_retry(self._thinking, CurriculumDraft, prompt)

    async def match_topics(self, queries: list[TopicMatchQuery]) -> BatchResult[TopicMatchResult]:
        if not queries:
            return BatchResult(items=[])

        queries_block = "\n\n".join(_format_topic_match_query(query) for query in queries)
        prompt = [
            ("system", prompts.TOPIC_BATCH_MATCH_SYSTEM),
            ("human", prompts.TOPIC_BATCH_MATCH_USER.format(queries_block=queries_block)),
        ]
        try:
            wire_result = await self._invoke_with_retry(
                self._thinking, _WireTopicMatchBatch, prompt
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            return BatchResult(items=[], failures=[f"match_topics call failed: {exc}"])

        items: list[TopicMatchResult] = []
        failures: list[str] = []
        for wire in wire_result.results:
            try:
                items.append(
                    TopicMatchResult(
                        request_index=wire.request_index, matched_topic_id=wire.matched_topic_id
                    )
                )
            except ValidationError as exc:
                failures.append(f"malformed topic match result: {exc}")
        return BatchResult(items=items, failures=failures)

    async def validate_topic_names(
        self, queries: list[TopicNameQuery]
    ) -> BatchResult[TopicNameVerdict]:
        if not queries:
            return BatchResult(items=[])

        queries_block = "\n".join(f'- request_index {q.request_index}: "{q.name}"' for q in queries)
        prompt = [
            ("system", prompts.TOPIC_NAME_VALIDATE_SYSTEM),
            ("human", prompts.TOPIC_NAME_VALIDATE_USER.format(queries_block=queries_block)),
        ]
        try:
            wire_result = await self._invoke_with_retry(
                self._thinking, _WireTopicNameVerdictBatch, prompt
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            # Fails OPEN, not closed (see TopicNameVerdict's default) — a
            # sanity check that can't run should never be the reason a real
            # learner's request gets stuck.
            return BatchResult(
                items=[TopicNameVerdict(request_index=q.request_index) for q in queries],
                failures=[f"validate_topic_names call failed: {exc}"],
            )

        items: list[TopicNameVerdict] = []
        failures: list[str] = []
        for wire in wire_result.verdicts:
            try:
                items.append(
                    TopicNameVerdict(
                        request_index=wire.request_index,
                        acceptable=wire.acceptable,
                        reason=wire.reason,
                    )
                )
            except ValidationError as exc:
                failures.append(f"malformed topic name verdict: {exc}")
        return BatchResult(items=items, failures=failures)

    # ----------------------------------------------------------------------- cards --

    async def plan_cards(
        self,
        *,
        topic_name: str,
        subtopic_title: str,
        subtopic_description: str,
        difficulty: Difficulty,
        count: int,
        type_quotas: dict[str, int],
        existing_titles: list[str],
        builds_on: list[str],
        avoid_bodies: list[str],
        rejection_feedback: list[tuple[str, str]],
    ) -> BatchResult[CardPlan]:
        prompt = [
            ("system", prompts.PLAN_SYSTEM),
            (
                "human",
                prompts.PLAN_USER.format(
                    topic_name=topic_name,
                    subtopic_title=subtopic_title,
                    subtopic_description=subtopic_description,
                    difficulty=difficulty.value,
                    count=count,
                    type_quotas_block=_format_type_quotas(type_quotas),
                    existing_titles_block=_format_existing_titles(existing_titles),
                    avoid_bodies_block=_format_avoid_bodies(avoid_bodies),
                    rejection_feedback_block=_format_rejection_feedback(rejection_feedback),
                    builds_on_block=_format_builds_on(builds_on),
                ),
            ),
        ]
        try:
            wire_result = await self._invoke_with_retry(
                self._generator, _WireCardPlanBatch, prompt, key_scope="box"
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            return BatchResult(items=[], failures=[f"plan_cards call failed: {exc}"])

        items: list[CardPlan] = []
        failures: list[str] = []
        for wire_plan in wire_result.plans:
            try:
                items.append(
                    CardPlan(
                        canonical_title=wire_plan.canonical_title,
                        card_type=wire_plan.card_type,
                        asset_direction=wire_plan.asset_direction,
                        content_direction=wire_plan.content_direction,
                    )
                )
            except ValidationError as exc:
                failures.append(f"malformed card plan: {exc}")
        return BatchResult(items=items, failures=failures)

    async def fetch_ascii_scenes(
        self,
        queries: list[AsciiFetchQuery],
        *,
        topic_name: str,
        subtopic_title: str,
        difficulty: Difficulty,
        exclude_ids: frozenset[str],
    ) -> BatchResult[AsciiFetchResult]:
        """ADR-0080: retrieve curated-library candidates per query (excluding
        anything already used in this topic), then one model call to pick and
        caption one per card. Survivable: an empty/failed result means every
        ascii card in the tier free-draws."""

        if not queries:
            return BatchResult(items=[])

        # One retrieval per card -- each card's scene is its own query, so the
        # candidate sets are not pooled (they may still overlap, which is fine).
        candidate_lists = await asyncio.gather(
            *(
                top_candidates(
                    q.asset_direction or q.canonical_title,
                    k=_ASCII_CANDIDATE_COUNT,
                    exclude_ids=exclude_ids,
                )
                for q in queries
            )
        )
        allowed_ids = {c.id for cands in candidate_lists for c in cands}
        if not allowed_ids:
            # Library unavailable or fully excluded for this topic -- nothing to
            # pick from, every card free-draws.
            return BatchResult(
                items=[AsciiFetchResult(index=q.index, matched=False) for q in queries]
            )

        cards_block = "\n\n".join(
            _format_fetch_candidates(q, cands)
            for q, cands in zip(queries, candidate_lists, strict=True)
        )
        prompt = [
            ("system", prompts.ASCII_FETCH_SYSTEM),
            (
                "human",
                prompts.ASCII_FETCH_USER.format(
                    topic_name=topic_name,
                    subtopic_title=subtopic_title,
                    difficulty=difficulty.value,
                    count=len(queries),
                    cards_block=cards_block,
                ),
            ),
        ]
        try:
            wire = await self._invoke_with_retry(
                self._generator, _WireAsciiFetchBatch, prompt, key_scope="box"
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            return BatchResult(items=[], failures=[f"fetch_ascii_scenes call failed: {exc}"])

        valid_indices = {q.index for q in queries}
        by_index: dict[int, _WireAsciiFetch] = {}
        for scene in wire.scenes:
            if scene.index in valid_indices:
                by_index[scene.index] = scene

        items: list[AsciiFetchResult] = []
        failures: list[str] = []
        for q in queries:
            picked = by_index.get(q.index)
            # A missing entry, an explicit refusal, or a src_id the query was
            # never shown all collapse to the same "this card free-draws"
            # outcome -- distinct from a call failure (handled above).
            if picked is None or not picked.matched or picked.src_id not in allowed_ids:
                items.append(AsciiFetchResult(index=q.index, matched=False))
                continue
            art = _strip_ascii_fence_wrapper(picked.ascii_art)
            if not art.strip():
                items.append(AsciiFetchResult(index=q.index, matched=False))
                failures.append(f"card {q.index}: picked {picked.src_id} but returned empty art")
                continue
            items.append(
                AsciiFetchResult(
                    index=q.index,
                    matched=True,
                    src_id=picked.src_id,
                    label=picked.ascii_label,
                    art=art,
                    alt=picked.ascii_alt,
                )
            )
        return BatchResult(items=items, failures=failures)

    async def _resolve_ascii_art(
        self, wire_cards: list[_WireCard]
    ) -> tuple[dict[int, tuple[str, str, str]], set[int]]:
        """ADR-0066: hand every over-budget ASCII drawing back to the generator
        to redraw within the 40-column budget instead of silently dropping it.

        Returns ``(resolved, rejected)``:

        - ``resolved[i]`` is the final ``(label, art, alt)`` for card ``i``'s
          scene — unchanged if it already fit, redrawn if it didn't.
        - ``rejected`` is the set of card indices whose art was STILL over
          budget after ``ascii_redraw_attempts`` tries; the caller rejects
          those cards whole rather than shipping them without art.

        A card that drew no scene is in neither set. Each redraw attempt is one
        batched call (ADR-0005) covering every scene still over budget."""

        resolved: dict[int, tuple[str, str, str]] = {}
        pending: dict[int, tuple[str, str, str]] = {}
        for i, wc in enumerate(wire_cards):
            if not wc.ascii_art.strip():
                continue
            # Strip a stray ```lang fence wrapper before the width check, not
            # after -- the fence's own backtick line is short enough to never
            # trip the budget itself, so a wrapped scene could otherwise sail
            # through here and ship with literal backticks at the top of the
            # card (see `_strip_ascii_fence_wrapper`'s docstring).
            art = _strip_ascii_fence_wrapper(wc.ascii_art)
            slot = (wc.ascii_label, art, wc.ascii_alt)
            if _ascii_over_budget_lines(art):
                pending[i] = slot
            else:
                resolved[i] = slot

        for attempt in range(self._ascii_redraw_attempts):
            if not pending:
                break
            logger.info(
                "generate_cards: ascii redraw attempt %d/%d for %d over-budget scene(s)",
                attempt + 1,
                self._ascii_redraw_attempts,
                len(pending),
            )
            prompt = _ascii_redraw_prompt(pending, escalated=attempt > 0)
            try:
                redraw = await self._invoke_with_retry(
                    self._generator, _WireAsciiRedrawBatch, prompt, key_scope="box"
                )
            except QuotaExhaustedError:
                raise
            except Exception as exc:
                logger.info(
                    "generate_cards: ascii redraw call failed (%s) -- %d scene(s) "
                    "will be rejected with their card",
                    exc,
                    len(pending),
                )
                break
            by_index = {scene.index: scene for scene in redraw.scenes}
            next_pending: dict[int, tuple[str, str, str]] = {}
            for i, (label, art, alt) in pending.items():
                scene = by_index.get(i)
                if scene is None:
                    # The model dropped this one from its response -- keep the
                    # current art for the next round's feedback.
                    next_pending[i] = (label, art, alt)
                    continue
                redrawn_art = _strip_ascii_fence_wrapper(scene.ascii_art)
                latest = (scene.ascii_label or label, redrawn_art, scene.ascii_alt or alt)
                if not redrawn_art.strip() or _ascii_over_budget_lines(redrawn_art):
                    # Still too wide (or returned empty, meaning "can't fit it").
                    # Feed the latest attempt back in with fresh violation
                    # numbers; fall back to the prior art if it gave us nothing.
                    next_pending[i] = latest if redrawn_art.strip() else (label, art, alt)
                    continue
                resolved[i] = latest
            pending = next_pending

        if pending:
            logger.info(
                "generate_cards: %d ascii scene(s) still over the %d-column budget after "
                "%d redraw attempt(s) -- rejecting those cards (ADR-0066)",
                len(pending),
                _ASCII_MAX_WIDTH,
                self._ascii_redraw_attempts,
            )
        return resolved, set(pending)

    async def generate_cards(
        self,
        *,
        topic_name: str,
        subtopic_title: str,
        subtopic_description: str,
        difficulty: Difficulty,
        count: int,
        existing_titles: list[str],
        builds_on: list[str],
        difficulty_examples: dict[Difficulty, list[str]],
        avoid_bodies: list[str],
        rejection_feedback: list[tuple[str, str]],
        want_hero: bool = False,
        card_type: CardType | str | None = None,
        plans: list[CardPlan] | None = None,
    ) -> BatchResult[CardDraft]:
        if want_hero:
            system_prompt = prompts.HERO_CARDS_SYSTEM
        elif card_type in (CardType.ASCII, "ascii"):
            system_prompt = prompts.CARDS_ASCII_SYSTEM
        elif card_type in (CardType.COMPARISON, "comparison"):
            system_prompt = prompts.CARDS_COMPARISON_SYSTEM
        elif card_type in (CardType.CODE, "code"):
            system_prompt = prompts.CARDS_CODE_SYSTEM
        elif card_type in (CardType.DIAGRAM, "diagram"):
            system_prompt = prompts.CARDS_DIAGRAM_SYSTEM
        elif card_type in (CardType.PROSE, "prose"):
            system_prompt = prompts.CARDS_PROSE_SYSTEM
        else:
            system_prompt = prompts.CARDS_SYSTEM

        # The plan instructions ride on the SYSTEM prompt (ADR-0059) so they sit
        # alongside the card-type requirement they qualify, rather than arriving
        # after it as user content that reads like a competing request.
        if plans:
            system_prompt = system_prompt + prompts.PLANNED_CARDS_INSTRUCTIONS

        prompt = [
            ("system", system_prompt),
            (
                "human",
                prompts.CARDS_USER.format(
                    topic_name=topic_name,
                    subtopic_title=subtopic_title,
                    subtopic_description=subtopic_description,
                    difficulty=difficulty.value,
                    count=count,
                    plans_block=_format_plans(plans or []),
                    difficulty_examples_block=_format_difficulty_examples(difficulty_examples),
                    existing_titles_block=_format_existing_titles(existing_titles),
                    avoid_bodies_block=_format_avoid_bodies(avoid_bodies),
                    rejection_feedback_block=_format_rejection_feedback(rejection_feedback),
                    builds_on_block=_format_builds_on(builds_on),
                ),
            ),
        ]
        try:
            wire_result = await self._invoke_with_retry(
                self._generator, _WireCardBatch, prompt, key_scope="box"
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            return BatchResult(items=[], failures=[f"generate_cards call failed: {exc}"])

        items: list[CardDraft] = []
        failures: list[str] = []
        # ADR-0066: redraw any over-budget ASCII art before assembling cards.
        # Called outside the try/except above on purpose — a QuotaExhaustedError
        # from a redraw call must propagate, same as the main generate call.
        resolved_art, rejected_for_art = await self._resolve_ascii_art(wire_result.cards)
        for i, wire_card in enumerate(wire_result.cards):
            # ADR-0080: a planned `ascii` card the fetcher matched carries its
            # scene on the plan (positional: brief i -> card i, the
            # PLANNED_CARDS_INSTRUCTIONS contract). The fetcher owns that card's
            # art; whatever the writer drew for it is ignored, including an
            # over-budget scene that would otherwise trip the ADR-0066 rejection.
            plan = plans[i] if plans is not None and i < len(plans) else None
            fetched = plan.fetched_scene if plan is not None else None

            if fetched is None and i in rejected_for_art:
                failures.append(
                    f"ascii art {wire_card.ascii_label or '(unlabeled)'!r} still exceeded "
                    f"{_ASCII_MAX_WIDTH} cols after redraw -- card rejected (ADR-0066)"
                )
                continue
            body = wire_card.body

            # Any ```mermaid fence in the body is a genuine content defect if
            # it fails the structural check, not a call failure -- the model
            # returned something, it's just not usable (CLAUDE.md's rejected-
            # vs-failed distinction). Checked before art resolution so a bad
            # diagram never gets as far as `CardDraft`.
            mermaid_issue: str | None = None
            for lang, content in _FENCE.findall(body):
                if lang.strip().lower() != "mermaid":
                    continue
                issue = _mermaid_structural_issue(content)
                if issue is not None:
                    mermaid_issue = issue
                    break
            if mermaid_issue is not None:
                failures.append(f"malformed mermaid diagram: {mermaid_issue}")
                continue

            try:
                if fetched is not None:
                    # ADR-0080: fetched scenes are already <= 40 cols (the fetch
                    # prompt's hard rule, over candidates that are all <= 40) --
                    # this guard is for a fetcher bug, not the normal path. An
                    # empty or over-budget fetched scene rejects the card rather
                    # than shipping broken art; it re-fetches next round.
                    if not fetched.art.strip() or _ascii_over_budget_lines(fetched.art):
                        failures.append(
                            f"fetched ascii scene {fetched.label!r} (src {fetched.src_id!r}) "
                            f"was empty or over {_ASCII_MAX_WIDTH} cols -- card rejected (ADR-0080)"
                        )
                        continue
                    body = _strip_duplicate_scene_from_body(body, fetched.art)
                    visual_id, visual_slots = _finalize_ascii_fields(
                        fetched.label, fetched.art, fetched.alt, src_id=fetched.src_id
                    )
                elif i in resolved_art:
                    label, art, alt = resolved_art[i]
                    # The prompt tells the model not to redraw its own scene a
                    # second time into `body` (ASCII_INSTRUCTIONS), but a card
                    # is not trusted to have honored that on its own -- strip a
                    # duplicate copy deterministically rather than shipping the
                    # same picture twice.
                    body = _strip_duplicate_scene_from_body(body, art)
                    visual_id, visual_slots = _finalize_ascii_fields(label, art, alt)
                else:
                    visual_id, visual_slots = None, None
                items.append(
                    CardDraft(
                        title=wire_card.title,
                        # difficulty is NEVER read from the model's own output —
                        # it's what we asked for (see CardDraft's docstring: the
                        # independent judge, not this call, is what validates it).
                        canonical_title=wire_card.canonical_title or wire_card.title,
                        summary=wire_card.summary,
                        body=body,
                        difficulty=difficulty,
                        visual_id=visual_id,
                        visual_slots=visual_slots,
                        # NEVER read from the wire model, same reasoning as
                        # `difficulty` above -- is_hero is entirely a fact
                        # about which call this is, not something the model
                        # gets a vote on.
                        is_hero=want_hero,
                    )
                )
            except ValidationError as exc:
                failures.append(f"malformed card: {exc}")
        return BatchResult(items=items, failures=failures)

    async def correct_cards(
        self,
        queries: list[CardCorrectionQuery],
        *,
        difficulty_examples: dict[Difficulty, list[str]],
    ) -> BatchResult[CardCorrectionResult]:
        if not queries:
            return BatchResult(items=[])

        topic_name = queries[0].topic_name
        topic_description = queries[0].topic_description
        cards_block = "\n\n".join(
            f"{q.index}. title: {q.title}\n"
            f"   canonical_title: {q.canonical_title}\n"
            f"   summary: {q.summary}\n"
            f"   body: {q.body}"
            for q in queries
        )
        prompt = [
            ("system", prompts.CORRECTION_SYSTEM),
            (
                "human",
                prompts.CORRECTION_USER.format(
                    topic_name=topic_name,
                    topic_description=topic_description or "(no additional description given)",
                    difficulty_examples_block=_format_difficulty_examples(difficulty_examples),
                    count=len(queries),
                    cards_block=cards_block,
                ),
            ),
        ]
        try:
            wire_result = await self._invoke_with_retry(
                self._thinking, _WireCorrectionBatch, prompt, key_scope="pool"
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            return BatchResult(items=[], failures=[f"correct_cards call failed: {exc}"])

        items: list[CardCorrectionResult] = []
        failures: list[str] = []
        for wire_correction in wire_result.corrections:
            try:
                items.append(
                    CardCorrectionResult(
                        index=wire_correction.index,
                        title=wire_correction.title,
                        canonical_title=wire_correction.canonical_title,
                        summary=wire_correction.summary,
                        body=wire_correction.body,
                        was_edited=wire_correction.was_edited,
                        note=wire_correction.note,
                    )
                )
            except ValidationError as exc:
                failures.append(f"malformed correction: {exc}")
        return BatchResult(items=items, failures=failures)

    async def verify_cards(
        self,
        queries: list[CardVerificationQuery],
        *,
        difficulty_examples: dict[Difficulty, list[str]],
    ) -> BatchResult[CardVerificationResult]:
        if not queries:
            return BatchResult(items=[])

        cards_block = "\n\n".join(
            f"{q.index}. Requested difficulty: {q.requested_difficulty.value}\n"
            f"   canonical_title: {q.canonical_title}\n"
            f"   body: {q.body}"
            for q in queries
        )
        prompt = [
            ("system", prompts.VERIFICATION_SYSTEM),
            (
                "human",
                prompts.VERIFICATION_USER.format(
                    difficulty_examples_block=_format_difficulty_examples(difficulty_examples),
                    count=len(queries),
                    cards_block=cards_block,
                ),
            ),
        ]
        try:
            wire_result = await self._invoke_with_retry(
                self._thinking, _WireVerificationBatch, prompt, key_scope="pool"
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            return BatchResult(items=[], failures=[f"verify_cards call failed: {exc}"])

        items: list[CardVerificationResult] = []
        failures: list[str] = []
        for wire_verdict in wire_result.verdicts:
            try:
                items.append(
                    CardVerificationResult(
                        index=wire_verdict.index,
                        accepted=wire_verdict.accepted,
                        confirmed_difficulty=Difficulty(wire_verdict.confirmed_difficulty),
                        reason=wire_verdict.reason,
                    )
                )
            except (ValidationError, ValueError) as exc:
                failures.append(f"malformed verification verdict: {exc}")
        return BatchResult(items=items, failures=failures)

    async def generate_questions(
        self,
        cards: list[tuple[str, str]],
        difficulty: Difficulty,
        *,
        existing_stems: list[str],
        is_backfill: bool,
    ) -> BatchResult[QuestionDraft]:
        if not cards:
            return BatchResult(items=[])

        backfill_tag = (
            " [BACKFILL -- already accepted, just missing a question]" if is_backfill else ""
        )
        cards_block = "\n\n".join(
            f"{index}. {title}{backfill_tag}\n{body}" for index, (title, body) in enumerate(cards)
        )
        prompt = [
            ("system", prompts.QUESTIONS_SYSTEM),
            (
                "human",
                prompts.QUESTIONS_USER.format(
                    difficulty=difficulty.value,
                    existing_stems_block=_format_existing_question_stems(existing_stems),
                    cards_block=cards_block,
                ),
            ),
        ]
        try:
            wire_result = await self._invoke_with_retry(
                self._generator, _WireQuestionBatch, prompt, key_scope="box"
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            return BatchResult(
                items=[],
                failures=[f"generate_questions call failed: {type(exc).__name__}: {exc}"],
            )

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

        # The model self-reports card_index (see _WireQuestion's field
        # description) rather than the code deriving it from response
        # position, so a mislabeled item is possible. Two items claiming the
        # same card_index would otherwise silently overwrite one another at
        # the QUESTION table's card_id FK with no signal that a different
        # card went without a question -- keep the first, drop the rest as
        # failures instead of guessing which one is right.
        seen_indices: set[int] = set()
        deduped: list[QuestionDraft] = []
        for draft in items:
            if draft.card_index in seen_indices:
                failures.append(
                    f"duplicate card_index {draft.card_index} (question dropped, "
                    "another question already claimed this card)"
                )
                continue
            seen_indices.add(draft.card_index)
            deduped.append(draft)

        return BatchResult(items=deduped, failures=failures)

    async def grade_free_text(
        self, items: list[FreeTextGradeQuery]
    ) -> BatchResult[FreeTextGradeResult]:
        if not items:
            return BatchResult(items=[])

        items_block = "\n\n".join(_format_free_text_grade_query(item) for item in items)
        prompt = [
            ("system", prompts.FREE_TEXT_GRADE_SYSTEM),
            ("human", prompts.FREE_TEXT_GRADE_USER.format(items_block=items_block)),
        ]
        try:
            wire_result = await self._invoke_with_retry(
                self._thinking, _WireFreeTextGradeBatch, prompt
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            return BatchResult(items=[], failures=[f"grade_free_text call failed: {exc}"])

        results: list[FreeTextGradeResult] = []
        failures: list[str] = []
        for wire_grade in wire_result.grades:
            try:
                results.append(
                    FreeTextGradeResult(
                        index=wire_grade.index,
                        rubric_level=wire_grade.rubric_level,
                        justification=wire_grade.justification,
                    )
                )
            except ValidationError as exc:
                failures.append(f"malformed free-text grade: {exc}")
        return BatchResult(items=results, failures=failures)

    async def repair_card_structure(
        self, queries: list[CardRepairQuery]
    ) -> BatchResult[CardRepairResult]:
        """ADR-0076 `mode=fix`. One multimodal call: the card fields as text plus
        each query's rendered PNG as an image part, matched back by `index`.
        Runs on the generator ladder -- this is repair, not judgment."""

        if not queries:
            return BatchResult(items=[])

        blocks = "\n\n---\n\n".join(
            "card index {index}\n{block}".format(
                index=q.index,
                block=prompts.REPAIR_USER.format(
                    title=q.title,
                    canonical_title=q.canonical_title,
                    summary=q.summary,
                    topic_name=q.topic_name,
                    topic_description=q.topic_description,
                    visual_id=q.visual_id or "(none)",
                    visual_slots=q.visual_slots or "(none)",
                    body=q.body,
                    reason_notes="\n".join(f"- {n}" for n in q.reason_notes) or "(none)",
                    operator_guidance=q.operator_guidance or "(none -- keep all prose verbatim)",
                ),
            )
            for q in queries
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": blocks}]
        for q in queries:
            if q.image_png:
                b64 = base64.b64encode(q.image_png).decode("ascii")
                content.append(
                    {"type": "text", "text": f"(image below: how card index {q.index} renders)"}
                )
                content.append({"type": "image_url", "image_url": f"data:image/png;base64,{b64}"})

        prompt: list[tuple[str, Any]] = [
            ("system", prompts.REPAIR_SYSTEM),
            ("human", content),
        ]
        try:
            wire = await self._invoke_with_retry(
                self._generator, _WireRepairBatch, prompt, key_scope="box"
            )
        except QuotaExhaustedError:
            raise
        except Exception as exc:
            return BatchResult(items=[], failures=[f"repair_card_structure call failed: {exc}"])

        results: list[CardRepairResult] = []
        failures: list[str] = []
        for card in wire.cards:
            try:
                results.append(
                    CardRepairResult(
                        index=card.index,
                        title=card.title,
                        canonical_title=card.canonical_title,
                        summary=card.summary,
                        body=card.body,
                        visual_slots=card.visual_slots,
                        note=card.note,
                    )
                )
            except ValidationError as exc:
                failures.append(f"malformed repair result: {exc}")
        return BatchResult(items=results, failures=failures)

    async def stream_topic_answer(self, query: AskTurnQuery) -> AsyncIterator[str]:
        """ADR-0077 (revised). One streamed flash-lite call per conversation
        turn, through the generator pool.

        Simpler failover than `_invoke_with_retry`: a user-facing call that
        needs to succeed or fail fast, not grind a whole grid. A few fresh
        `acquire()`s (each self-paced, least-spent-first); if none serve, raise
        -- the endpoint turns that into an `error` SSE event."""

        subtopic_lines = "\n".join(f"- {s}" for s in query.subtopics) or "- (none listed)"
        messages: list[tuple[str, Any]] = [
            (
                "system",
                prompts.ASK_SYSTEM.format(
                    topic_name=query.topic_name,
                    subtopics=subtopic_lines,
                    current_card=query.current_card_title or "(browsing the topic)",
                    context=query.context,
                ),
            ),
        ]
        for role, text in query.history:
            messages.append(("ai" if role == "assistant" else "human", text))
        messages.append(("human", query.question))

        attempts = min(4, self._generator.key_count * len(self._generator.ladder))
        last_exc: Exception | None = None
        for _ in range(max(1, attempts)):
            try:
                key_index, model = await self._generator.acquire(now=datetime.now(UTC), claim=None)
            except QuotaExhaustedError:
                raise
            client = self._client(key_index, model)
            try:
                await self._generator.note_request_sent(key_index, model, now=datetime.now(UTC))
                async for chunk in client.astream(messages):
                    raw: object = chunk.content
                    if isinstance(raw, list):
                        text = "".join(
                            str(part.get("text", "")) if isinstance(part, dict) else str(part)
                            for part in raw
                        )
                    else:
                        text = str(raw)
                    if text:
                        yield text
                return
            except (ClientError, ChatGoogleGenerativeAIError, ServerError) as exc:
                # Don't touch the ledger for a one-shot user call -- just move to
                # another cell. A persistent failure falls through to the raise.
                last_exc = exc
                logger.warning(
                    "askai stream: cell key=%d model=%s failed: %s", key_index, model, exc
                )
                continue
        raise AllModelsUnavailableError(f"no cell could serve the AskAI stream: {last_exc}")
