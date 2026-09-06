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

`match_topics` (ADR-0025) uses the wire/domain split, same as the other batch
methods, since a malformed verdict for one topic in the batch shouldn't fail
matching for every other topic in it.

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
`acquire()`, or a non-quota error) propagate to the caller -- every method's
existing `except Exception` converts it to a `BatchResult` failure.
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
from typing import Any, TypeVar

from google.genai.errors import ClientError, ServerError
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from pydantic import BaseModel, Field, ValidationError, model_validator

from spoin.content.ascii_library import AsciiLibraryEntry, top_candidates
from spoin.core.config import Settings
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
    FreeTextGradeQuery,
    FreeTextGradeResult,
    QuestionDraft,
    TopicMatchQuery,
    TopicMatchResult,
    TopicNameQuery,
    TopicNameVerdict,
)
from spoin.generation.load_balancer import (
    CURRENT_BALANCER,
    LadderKind,
    LoadBalancer,
    Reservation,
    estimate_tokens,
    make_ledger_writer,
    pack_by_tokens,
    seed_rpd,
)
from spoin.generation.quota import (
    AllCellsThrottledError,
    AllModelsUnavailableError,
    BoxPool,
    DailyQuotaExhaustedError,
    KeyBox,
    QuotaExhaustedError,
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


class _WaveGate:
    """Batch-and-pause admission control over this process's outbound Gemini calls.

    A *wave* is up to `size` calls in flight together. Once `size` have been
    admitted the gate is shut: nothing else leaves until every member of that
    wave has come home AND a `cooldown_s` pause has run. Then the next wave opens.

    This is deliberately stricter than the rolling semaphore it replaces. A
    semaphore refills a permit the instant any ONE call lands, so it keeps `size`
    calls perpetually open and the provider never sees a moment with nothing of
    ours in flight. `inflight_sweep.py` found the source-IP throttle sheds on
    exactly that number (1% failure at N<=3, 53% at N=4 -- a wall, not a
    gradient), and a rolling semaphore at N=3 still got shed on once the
    pipeline's long structured-output batches (7-17s open, against the probe's
    ~2.5s) began overlapping. Draining to zero between waves is the difference:
    it gives the edge a window with none of our sockets open in it, and the pause
    makes that window a length we chose rather than whatever latency left over.

    A wave that drains WITHOUT ever filling costs nothing: `_admitted` resets on
    every drain, so a trickle of sequential calls -- concurrency 1, measured safe
    -- is never made to wait. The pause is the price of having run at the ceiling.

    All state is mutated without a lock, and every mutation is a synchronous run
    between awaits on the one event loop. `_release` in particular takes no await,
    so a call cancelled mid-request still returns its slot instead of wedging the
    gate shut for everyone behind it.
    """

    def __init__(self, size: int, cooldown_s: float) -> None:
        self._size = max(1, size)
        self._cooldown_s = max(0.0, cooldown_s)
        #: Admitted into the CURRENT wave. Reset to 0 whenever the wave drains,
        #: which is what keeps a trickle from accumulating into a phantom wave.
        self._admitted = 0
        #: Requests sent whose response has not landed yet.
        self._inflight = 0
        #: Monotonic time before which the next wave may not open.
        self._open_at = 0.0
        #: Set while the current wave still has room; cleared the moment it fills.
        self._wave_open = asyncio.Event()
        self._wave_open.set()

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        """Wait for a slot in the current wave and hold it for the round trip."""

        while True:
            cooldown_left = self._open_at - time.monotonic()
            if cooldown_left > 0.0:
                await asyncio.sleep(cooldown_left)
                continue
            if self._admitted < self._size:
                break
            await self._wave_open.wait()

        self._admitted += 1
        self._inflight += 1
        if self._admitted >= self._size:
            # Shut the gate in the same synchronous step that fills the wave, so
            # no other waiter can slip through between the two.
            self._wave_open.clear()
        try:
            yield
        finally:
            self._release()

    def _release(self) -> None:
        self._inflight -= 1
        if self._inflight:
            return
        if self._admitted >= self._size:
            self._open_at = time.monotonic() + self._cooldown_s
        self._admitted = 0
        self._wave_open.set()


@dataclass(frozen=True)
class _RateLimit:
    """How to react to one real 429.

    `is_daily` is the whole point: it decides between spending this cell for the
    rest of the day and parking it for `retry_after_s` seconds. An
    unidentifiable 429 (no `quotaId`, no `RetryInfo`) is treated as per-minute
    (ADR-0060) -- and under ADR-0084 the balancer's learned-rpm update is a
    measured floor (`min(learned, sends in window)`), not AIMD's guess, so it is
    safe to apply on every per-minute 429 without a `scope_certain` gate.
    """

    is_daily: bool
    retry_after_s: float | None


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
    # A short `RetryInfo` outranks EVERY quotaId, `...PerDay...` included.
    #
    # Measured 2026-09-04 with direct single-key probes that bypass this module
    # entirely: Google throttles on the source IP, and the envelope it sends for
    # that throttle is `GenerateRequestsPerDayPerProjectPerModel-FreeTier,
    # limit: 500` on keys nowhere near 500 requests -- 12 keys from 12 separate
    # projects, fired together, all came back with an IDENTICAL retryDelay, and
    # firing them is what re-armed a window that had just decayed to 0s. The
    # quotaId is boilerplate on this path; the delay is the real signal, and
    # nothing daily resolves in 41 seconds.
    #
    # Trusting the id over the delay is what turned a 30s pause into a dead pool:
    # `on_rate_limited(per_minute=False)` force-sets `rpd_spent = rpd_limit`, so
    # one mislabelled 429 retires a cell until tomorrow AND writes a fabricated
    # 500 to `quota_ledger` that `seed_rpd` reads back into the next run. Measured
    # cost: 136 of 204 generator cells destroyed in 60 seconds, 0 cards.
    if retry_after is not None and retry_after <= _PER_MINUTE_RETRY_CEILING_S:
        return _RateLimit(is_daily=False, retry_after_s=retry_after)
    if "perday" in haystack:
        return _RateLimit(is_daily=True, retry_after_s=None)
    if "perminute" in haystack:
        return _RateLimit(is_daily=False, retry_after_s=retry_after)
    if retry_after is not None:
        # Past one RPM window with no recognisable scope -- a delay that long
        # cannot describe a per-minute limit.
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
    return _RateLimit(is_daily=False, retry_after_s=None)


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
_ASCII_CANDIDATE_COUNT = 5


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

    The split is by what a call PRODUCES (ADR-0090). `_thinking` covers the
    calls that return a **verdict** — curriculum, topic matching, topic-name
    validation, `verify_cards`, and quiz grading — where a weak model's answer
    is a constraint rather than a preference, and CLAUDE.md's "trusted for
    taste, never for constraints" rule applies. `_generator` covers the calls
    that return **prose**: `generate_cards`, `generate_questions` (ADR-0029),
    `plan_cards`, `fetch_ascii_scenes`, `repair_card_structure`, AskAI's
    `stream_topic_answer`, and — since ADR-0090 — `correct_cards`.

    `correct_cards` moving here split ADR-0030's two-pass gate across both
    ladders, which is deliberate: the pass that *rewrites* is prose work, the
    pass that *decides* is not. See the call site for the full reasoning.

    Each pool has its own key x model quota grid (ADR-0028) — a call to one
    never affects the other's remaining budget.
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
        #: Prompt-token ceiling for one call (ADR-0085) -- `fetch_ascii_scenes`
        #: packs its queries against it, since each carries whole artworks.
        self._prompt_token_budget = settings.gemini_prompt_token_budget
        #: The two model ladders (ADR-0028). A `LoadBalancer` walks whichever one
        #: a call's `kind` selects; both are over the same physical keys, so one
        #: balancer owns both ladders for its key set (ADR-0084).
        self._gen_ladder = parse_ladder(settings.gemini_generator_ladder)
        self._think_ladder = parse_ladder(settings.gemini_thinking_ladder)
        #: model -> epoch expiry. ONE dict shared by reference into every
        #: balancer this run builds: a 503/504 is the model's problem at the
        #: provider, not one box's (ADR-0084).
        self._model_unavailable: dict[str, float] = {}
        self._ledger_writer = make_ledger_writer()
        #: Min seconds between two sends to one key, passed into every balancer
        #: (ADR-0084 burst brake).
        self._send_gap_s = settings.gemini_send_gap_seconds
        #: Pool-wide dispatch stagger -- paces reservation RATE (ADR-0086).
        self._dispatch_stagger_s = settings.gemini_dispatch_stagger_seconds
        #: Batch-and-pause gate over every outbound call (`_WaveGate`). The
        #: source-IP throttle sheds on concurrency, not rate: at most
        #: `gemini_max_inflight_calls` are open together, and the next wave waits
        #: for the current one to drain plus `gemini_wave_cooldown_seconds`.
        #: Acquired at the single send site in `_invoke_with_backoff`, released
        #: when the response lands. One gate for the whole process -- card drafts
        #: and thinking calls share it.
        self._wave = _WaveGate(
            settings.gemini_max_inflight_calls, settings.gemini_wave_cooldown_seconds
        )
        #: Sliding active-key window over a box -- rotates only on facts local to
        #: it (top rung spent, or no budget anywhere in it), never on the failure
        #: rate (see the config comment on `gemini_active_key_window`).
        self._active_key_window = settings.gemini_active_key_window
        #: The pool's key indices, minus a fixed remainder held back for the
        #: claim-less path (ADR-0082/0084). `pool - max_topics*box` keys stay
        #: unboxed; a box and the remainder balancer never share a key.
        remainder = settings.gemini_pool_size - (
            settings.max_concurrent_topics * settings.topic_key_box_size
        )
        self._pool = BoxPool(
            len(keys), remainder_size=max(1, min(remainder, len(keys) - 1)) if len(keys) > 1 else 0
        )
        #: Built lazily on the first claim-less call (needs an async ledger read).
        self._remainder_lb: LoadBalancer | None = None
        self._clients: dict[tuple[int, str], ChatGoogleGenerativeAI] = {}
        #: (id(balancer), model) -> the running recovery-probe task for that
        #: model, if any -- keeps a stalled model from spawning a second probe
        #: on every subsequent timeout while the first one is still running.
        self._active_probes: dict[tuple[int, str], asyncio.Task[None]] = {}

    @asynccontextmanager
    async def claimed_key_scope(self, *, box: KeyBox | None = None) -> AsyncIterator[None]:
        """Everything called inside this block routes through `box`'s balancer
        (ADR-0084) -- so a topic's calls only ever touch its own keys. Without a
        box (the `fake` backend, a keyless CLI run) the ambient balancer is
        `None` and calls fall back to the remainder balancer.

        No key is 'claimed' or pinned any more (ADR-0083 retired the per-group
        pin; ADR-0084 removed the machinery): the balancer picks the
        least-spent key in scope fresh on every call. The box's lifetime is the
        run's, managed by `run_generation_pipeline`'s lease/release, not this
        scope."""

        token = CURRENT_BALANCER.set(box.balancer if box is not None else None)
        try:
            yield
        finally:
            CURRENT_BALANCER.reset(token)

    async def _remainder(self) -> LoadBalancer:
        """The balancer for claim-less calls -- curriculum, topic matching, quiz
        grading, the recovery probe (ADR-0084). Over the pool's reserved
        remainder keys, so it never contends with a box. Built once, lazily."""

        if self._remainder_lb is None:
            now = datetime.now(UTC)
            keys = self._pool.remainder or tuple(range(len(self._keys)))
            models = frozenset(r.model for r in (*self._gen_ladder, *self._think_ladder))
            self._remainder_lb = LoadBalancer(
                name="remainder",
                key_indices=keys,
                generator_ladder=self._gen_ladder,
                thinking_ladder=self._think_ladder,
                model_unavailable=self._model_unavailable,
                rpd_seed=await seed_rpd(keys, models, now=now),
                now=now,
                ledger_writer=self._ledger_writer,
                send_gap_s=self._send_gap_s,
                dispatch_stagger_s=self._dispatch_stagger_s,
            )
        return self._remainder_lb

    async def lease_key_box(self, size: int) -> KeyBox:
        """Cut a box of up to `size` keys and build its `LoadBalancer`
        (ADR-0082/0084), coldest-first from the ledger so a day of passes
        spreads across the pool instead of re-boxing keys 0..N every time. A
        short or empty box is not an error -- a topic with fewer keys still
        generates; an empty one runs on the remainder balancer."""

        now = datetime.now(UTC)
        models = frozenset(r.model for r in (*self._gen_ladder, *self._think_ladder))
        seed_all = await seed_rpd(tuple(range(len(self._keys))), models, now=now)
        per_key: dict[int, int] = {}
        for (k, _m), spent in seed_all.items():
            per_key[k] = per_key.get(k, 0) + spent
        coldest_first = sorted(range(len(self._keys)), key=lambda k: (per_key.get(k, 0), k))
        box_id, box_keys = self._pool.lease(size, prefer=coldest_first)
        if not box_keys:
            return KeyBox(box_id=box_id, key_indices=(), balancer=None)
        balancer = LoadBalancer(
            name=f"box-{box_id}",
            key_indices=box_keys,
            generator_ladder=self._gen_ladder,
            thinking_ladder=self._think_ladder,
            model_unavailable=self._model_unavailable,
            rpd_seed={cell: s for cell, s in seed_all.items() if cell[0] in box_keys},
            now=now,
            ledger_writer=self._ledger_writer,
            send_gap_s=self._send_gap_s,
            dispatch_stagger_s=self._dispatch_stagger_s,
            active_key_window=self._active_key_window,
        )
        return KeyBox(box_id=box_id, key_indices=box_keys, balancer=balancer)

    async def release_key_box(self, box: KeyBox) -> None:
        """Flush the box balancer's day counts to the ledger and return its keys
        to the pool (ADR-0082/0084). Idempotent."""

        if box.balancer is not None:
            await box.balancer.flush()
        if box.key_indices:
            self._pool.release(box.key_indices)

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
        lb: LoadBalancer,
        res: Reservation,
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
        window slot is stamped to the true send time (`lb.note_send`, ADR-0084):
        the reservation was taken when `assign()` chose the cell, seconds
        earlier, and counting the call in that earlier minute is how our window
        drifts wide of the provider's. Being inside the retry loop means a 503
        retried on this same cell is stamped again -- another real request."""

        key_index, model = res.key_index, res.model
        delay = _SERVER_ERROR_BASE_DELAY_S
        for attempt in range(1, _SERVER_ERROR_RETRIES + 1):
            try:
                lb.note_send(res, now=datetime.now(UTC), tokens=estimate_tokens(str(prompt)))
                # PROBE D (temporary, 2026-09-03): the call latency `L`. Queue
                # depth behind `cell_lock` is roughly `L / gap`, which is the
                # number the send gap has been tuned blind against three times.
                queued_at = time.monotonic()
                prompt_chars = len(str(prompt))
                # `latency` MUST measure the HTTP round trip alone. `queued` --
                # time spent waiting for a slot at the gate -- is reported
                # separately: folding the two together is what made the first
                # wave-gate run unreadable (every `latency=` climbed to 80-140s
                # and looked like provider slowness when it was our own queue).
                started = queued_at
                try:
                    # The one place a generation request leaves this process.
                    # `_wave` caps how many are open at once and drains to zero
                    # between waves: the source-IP throttle sheds on concurrency,
                    # so this -- not the dispatch stagger -- is the control that
                    # keeps us under it. Held for exactly the HTTP round trip; a
                    # 503 backoff between retries releases the slot.
                    async with self._wave.hold():
                        started = time.monotonic()
                        result = await structured.ainvoke(prompt)  # type: ignore[attr-defined]
                except BaseException as exc:
                    logger.info(
                        "lbprobe call key=%d model=%s latency=%.2f queued=%.2f chars=%d outcome=%s",
                        key_index,
                        model,
                        time.monotonic() - started,
                        started - queued_at,
                        prompt_chars,
                        type(exc).__name__,
                    )
                    raise
                logger.info(
                    "lbprobe call key=%d model=%s latency=%.2f queued=%.2f chars=%d outcome=ok",
                    key_index,
                    model,
                    time.monotonic() - started,
                    started - queued_at,
                    prompt_chars,
                )
                return result
            except ServerError as exc:
                if exc.code == 504 or attempt == _SERVER_ERROR_RETRIES:
                    lb.on_send_aborted(res)
                    raise
                logger.warning(
                    "lb %s: key=%d model=%s got a transient 503 (high demand, attempt "
                    "%d/%d) -- retrying in %.0fs",
                    lb.name,
                    key_index,
                    model,
                    attempt,
                    _SERVER_ERROR_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable: loop always returns or raises on its last attempt")

    async def _invoke_with_retry(
        self,
        kind: LadderKind,
        schema: type[_SchemaT],
        prompt: list[tuple[str, Any]],
    ) -> _SchemaT:
        """Assign a `(key, model)` cell from the ambient balancer (the box's, or
        the remainder) and call it. A REAL 429 means the provider disagreed with
        our local count: park or spend that exact cell and move to the next,
        bounded at one attempt per `(key, model)`.

        **`max_attempts` counts cells BURNED, not calls made** (ADR-0084). A
        per-minute 429 doesn't use a cell up -- it parks it -- so counting it
        here would let a brief throttle burn the whole grid's budget.

        **The retry loop stops on a per-minute-429 streak.** Every per-minute
        429 with no success in between adds one; any success resets it.
        `grid_size` (one full key x model sweep) in a row means the pool is
        refusing us wholesale -- `AllCellsThrottledError`, not exhaustion,
        because the daily budget is intact."""

        lb = CURRENT_BALANCER.get() or await self._remainder()
        ladder = lb.ladder(kind)
        # What this call will cost the cell's trailing-minute token window
        # (ADR-0085). Computed once: the prompt does not change across cells.
        est_tokens = estimate_tokens(str(prompt))
        max_attempts = lb.key_count * len(ladder)
        grid_size = max_attempts
        cells_burned = 0
        throttle_streak = 0
        last_server_error: ServerError | None = None
        # A 503/504 is per-MODEL, not per-key (every key hits the same wall):
        # once a model stays UNAVAILABLE through its own backoff, exclude it so
        # the next assign() jumps straight to the next rung.
        unavailable_models: set[str] = set()
        while cells_burned < max_attempts:
            attempt = cells_burned + 1
            try:
                res = await lb.assign(
                    kind,
                    now=datetime.now(UTC),
                    est_tokens=est_tokens,
                    exclude_models=frozenset(unavailable_models),
                )
            except QuotaExhaustedError:
                # Every remaining rung was excluded as overloaded, not actually
                # quota-exhausted -- surface the real 503 instead of a
                # misleading "quota exhausted" when no cell was ever spent.
                if last_server_error is not None:
                    raise last_server_error from None
                raise
            key_index, model = res.key_index, res.model
            client = self._client(key_index, model)
            structured = client.with_structured_output(schema)
            try:
                async with lb.cell_lock(key_index, model):
                    result = await self._invoke_with_backoff(structured, prompt, lb=lb, res=res)
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
                        # Throttled, not spent. Park THIS cell for exactly the
                        # `retryDelay` Google gave us (0-59s, measured) and take
                        # the next cell the balancer offers -- no caller-side
                        # sleep. `assign()` already skips cooling cells, and
                        # `gemini_dispatch_stagger_seconds` (2.0s, the measured
                        # sustainable rate) paces every reservation it hands back.
                        # This is the whole point of "use the load balancer": the
                        # ADR-0086 perimeter backoff that sat here was a second
                        # pacing layer built for a penalised IP, and it fought the
                        # balancer instead of using it.
                        lb.on_rate_limited(
                            res,
                            now=datetime.now(UTC),
                            per_minute=True,
                            retry_after_s=limit.retry_after_s,
                        )
                        throttle_streak += 1
                        if throttle_streak >= grid_size:
                            raise AllCellsThrottledError(
                                f"{throttle_streak} consecutive per-minute 429s with no "
                                f"success -- every cell in the {lb.key_count}x{len(ladder)} "
                                f"grid is refusing us. Daily quota remains; this is "
                                f"throttling, not exhaustion."
                            ) from exc
                        logger.info(
                            "lb %s: cell key=%d model=%s throttled (streak %d/%d) -- "
                            "parked %.0fs, taking next cell",
                            lb.name,
                            key_index,
                            model,
                            throttle_streak,
                            grid_size,
                            limit.retry_after_s or 0.0,
                        )
                        continue
                    lb.on_rate_limited(res, now=datetime.now(UTC), per_minute=False)
                    logger.warning(
                        "lb %s: key=%d model=%s got a per-day 429 despite our count showing "
                        "room -- marking spent, trying next cell (cell %d/%d): %s",
                        lb.name,
                        key_index,
                        model,
                        attempt,
                        max_attempts,
                        exc,
                    )
                else:
                    lb.mark_exhausted(key_index, model)
                    logger.warning(
                        "lb %s: key=%d model=%s got auth error %d (%s) -- marking spent, "
                        "trying next cell (cell %d/%d)",
                        lb.name,
                        key_index,
                        model,
                        real_error.code,
                        getattr(real_error, "message", str(exc)),
                        attempt,
                        max_attempts,
                    )
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
                    "lb %s: model=%s still UNAVAILABLE after backoff on key=%d -- excluding "
                    "this model, trying next one (attempt %d/%d): %s",
                    lb.name,
                    model,
                    key_index,
                    attempt,
                    max_attempts,
                    exc,
                )
                lb.exclude_model(model, now=datetime.now(UTC), expires_in_s=_PROBE_BUDGET_SECONDS)
                self._start_recovery_probe(lb, model)
                unavailable_models.add(model)
                last_server_error = exc
                cells_burned += 1
                continue
            assert isinstance(result, schema)
            # A call got through -- the throttle streak that would otherwise end
            # this loop is genuinely broken (ADR-0084).
            await lb.on_success(res, now=datetime.now(UTC))
            throttle_streak = 0
            return result
        if last_server_error is not None:
            # Every cell stayed UNAVAILABLE -- NOT quota exhaustion, so re-raise
            # the actual 503 rather than the assertion below.
            raise last_server_error
        raise DailyQuotaExhaustedError(
            f"lb {lb.name}: all {lb.key_count} key(s) x {len(ladder)} model(s) exhausted "
            f"for {datetime.now(UTC).date()} -- every cell was spent by a per-day 429 or "
            f"an auth failure during this call"
        )

    def _start_recovery_probe(self, lb: LoadBalancer, model: str) -> None:
        """Fire-and-forget: called the moment `_invoke_with_retry` excludes a
        model after a timeout. Only ever one probe in flight per
        `(balancer, model)`."""

        key = (id(lb), model)
        existing = self._active_probes.get(key)
        if existing is not None and not existing.done():
            return
        self._active_probes[key] = asyncio.create_task(self._probe_model(lb, model))

    async def _probe_model(self, lb: LoadBalancer, model: str) -> None:
        """Off the request path: checks whether a model excluded after a timeout
        has come back, cycling a different key each attempt so one bad key isn't
        mistaken for the whole model being down. A probe ping doesn't touch the
        balancer's counters -- a handful of calls over 20 minutes is noise next
        to real traffic, and the point is availability, not accounting.

        Only matters while this process lives; a short-lived worker pass that
        exits mid-probe just rediscovers the model on the next pass."""

        keys = lb.key_indices
        interval = max(_PROBE_MIN_INTERVAL_SECONDS, _PROBE_BUDGET_SECONDS / len(keys))
        deadline = time.monotonic() + _PROBE_BUDGET_SECONDS
        attempt = 0
        while time.monotonic() < deadline:
            key_index = keys[attempt % len(keys)]
            attempt += 1
            try:
                async with lb.cell_lock(key_index, model), self._wave.hold():
                    await self._client(key_index, model).ainvoke([("human", "ping")])
            except Exception as exc:
                logger.info(
                    "probe: lb %s key=%d model=%s still unavailable (%s) -- next attempt "
                    "in %.0fs with a different key",
                    lb.name,
                    key_index,
                    model,
                    exc,
                    interval,
                )
                await asyncio.sleep(interval)
                continue
            logger.warning(
                "probe: lb %s key=%d model=%s responded -- back into rotation",
                lb.name,
                key_index,
                model,
            )
            lb.include_model(model)
            return

        logger.warning(
            "probe: lb %s model=%s did not respond from any key within %.0fs -- "
            "marking its cells spent for the day, dropping the exclusion flag",
            lb.name,
            model,
            _PROBE_BUDGET_SECONDS,
        )
        for key_index in keys:
            lb.mark_exhausted(key_index, model)
        lb.include_model(model)

    # `generate_curriculum` lived here. Deleted, not grounded (ADR-0007,
    # authored-curriculum.md): the curriculum is authored beside the corpus and
    # projected into `Topic`/`Subtopic` by deterministic code, with no model call.

    async def match_topics(self, queries: list[TopicMatchQuery]) -> BatchResult[TopicMatchResult]:
        if not queries:
            return BatchResult(items=[])

        queries_block = "\n\n".join(_format_topic_match_query(query) for query in queries)
        prompt = [
            ("system", prompts.TOPIC_BATCH_MATCH_SYSTEM),
            ("human", prompts.TOPIC_BATCH_MATCH_USER.format(queries_block=queries_block)),
        ]
        try:
            wire_result = await self._invoke_with_retry("thinking", _WireTopicMatchBatch, prompt)
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
                "thinking", _WireTopicNameVerdictBatch, prompt
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
        grounding: str = "",
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
                    grounding_block=grounding,
                ),
            ),
        ]
        try:
            wire_result = await self._invoke_with_retry("generator", _WireCardPlanBatch, prompt)
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
        if not any(candidate_lists):
            # Library unavailable or fully excluded for this topic -- nothing to
            # pick from, every card free-draws.
            return BatchResult(
                items=[AsciiFetchResult(index=q.index, matched=False) for q in queries]
            )

        # Each query carries `_ASCII_CANDIDATE_COUNT` whole artworks into the
        # prompt, so an N-card tier used to send N x k of them in ONE request --
        # the heaviest prompt the pipeline builds. Pack the queries by their real
        # rendered weight instead (ADR-0085); every chunk is its own request and
        # so gets its own `(key, model)` from the balancer. Results are keyed by
        # `q.index`, not position, so chunking cannot scramble them.
        rendered = [
            (q, cands, _format_fetch_candidates(q, cands))
            for q, cands in zip(queries, candidate_lists, strict=True)
        ]
        chunks = pack_by_tokens(
            rendered,
            cost=lambda r: estimate_tokens(r[2]),
            budget=self._prompt_token_budget,
            max_items=len(rendered),
        )

        items: list[AsciiFetchResult] = []
        failures: list[str] = []
        for chunk in chunks:
            chunk_queries = [q for q, _cands, _text in chunk]
            allowed_ids = {c.id for _q, cands, _text in chunk for c in cands}
            cards_block = "\n\n".join(text for _q, _cands, text in chunk)
            prompt = [
                ("system", prompts.ASCII_FETCH_SYSTEM),
                (
                    "human",
                    prompts.ASCII_FETCH_USER.format(
                        topic_name=topic_name,
                        subtopic_title=subtopic_title,
                        difficulty=difficulty.value,
                        count=len(chunk_queries),
                        cards_block=cards_block,
                    ),
                ),
            ]
            try:
                wire = await self._invoke_with_retry("generator", _WireAsciiFetchBatch, prompt)
            except QuotaExhaustedError:
                raise
            except Exception as exc:
                # One chunk failing is not the whole tier failing: its cards
                # free-draw and the remaining chunks still get their shot.
                failures.append(f"fetch_ascii_scenes call failed: {exc}")
                items.extend(AsciiFetchResult(index=q.index, matched=False) for q in chunk_queries)
                continue

            valid_indices = {q.index for q in chunk_queries}
            by_index: dict[int, _WireAsciiFetch] = {}
            for scene in wire.scenes:
                if scene.index in valid_indices:
                    by_index[scene.index] = scene

            for q in chunk_queries:
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
                    failures.append(
                        f"card {q.index}: picked {picked.src_id} but returned empty art"
                    )
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
                redraw = await self._invoke_with_retry("generator", _WireAsciiRedrawBatch, prompt)
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
        grounding: str = "",
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
                    #: Already rendered and already packed to a token budget by
                    #: `generation/grounding.py` -- interpolated whole, and empty when
                    #: the run is ungrounded.
                    grounding_block=grounding,
                ),
            ),
        ]
        try:
            wire_result = await self._invoke_with_retry("generator", _WireCardBatch, prompt)
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
        grounding: str = "",
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
                    grounding_block=grounding,
                    count=len(queries),
                    cards_block=cards_block,
                ),
            ),
        ]
        try:
            #: ADR-0090: correction is REWRITING, not judgment. It takes a card and a
            #: criticism and produces better prose, against retrieved source material
            #: (ADR-0089) -- restatement rather than recall, which is the thing a small
            #: model can do. Its sibling `verify_cards` returns a VERDICT and stays on
            #: the thinking ladder permanently; that asymmetry is the whole point, and
            #: this line is the half of ADR-0030's two-pass gate that moved.
            wire_result = await self._invoke_with_retry("generator", _WireCorrectionBatch, prompt)
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
        grounding: str = "",
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
                    grounding_block=grounding,
                    count=len(queries),
                    cards_block=cards_block,
                ),
            ),
        ]
        try:
            wire_result = await self._invoke_with_retry("thinking", _WireVerificationBatch, prompt)
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
        grounding: str = "",
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
                    grounding_block=grounding,
                    cards_block=cards_block,
                ),
            ),
        ]
        try:
            wire_result = await self._invoke_with_retry("generator", _WireQuestionBatch, prompt)
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
            wire_result = await self._invoke_with_retry("thinking", _WireFreeTextGradeBatch, prompt)
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
            wire = await self._invoke_with_retry("generator", _WireRepairBatch, prompt)
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

        lb = await self._remainder()
        attempts = min(4, lb.key_count * len(lb.ladder("generator")))
        last_exc: Exception | None = None
        est_tokens = estimate_tokens(str(messages))
        for _ in range(max(1, attempts)):
            try:
                res = await lb.assign("generator", now=datetime.now(UTC), est_tokens=est_tokens)
            except QuotaExhaustedError:
                raise
            key_index, model = res.key_index, res.model
            client = self._client(key_index, model)
            try:
                lb.note_send(res, now=datetime.now(UTC), tokens=est_tokens)
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
                await lb.on_success(res, now=datetime.now(UTC))
                return
            except (ClientError, ChatGoogleGenerativeAIError, ServerError) as exc:
                # A one-shot user call: don't spend the cell, just move on. A
                # persistent failure falls through to the raise.
                lb.on_send_aborted(res)
                last_exc = exc
                logger.warning(
                    "askai stream: cell key=%d model=%s failed: %s", key_index, model, exc
                )
                continue
        raise AllModelsUnavailableError(f"no cell could serve the AskAI stream: {last_exc}")
