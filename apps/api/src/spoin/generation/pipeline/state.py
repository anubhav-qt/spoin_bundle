"""Shared types, runtime handle and small pure helpers for the pipeline.

The bottom layer: everything here is either a `TypedDict` describing graph
state, the `_Runtime` bundle each node unpacks from LangGraph's config, or a
pure function with no session and no generator. Nothing in this module talks to
the database or to a model, which is what lets every other pipeline module
import it without creating a cycle.

`logger` lives here rather than in each module so every pipeline line keeps
emitting under the name it always has (`spoin.generation.pipeline`) — splitting
the module should not silently rename the logger anything watching production
logs is keyed to.
"""

from __future__ import annotations

import asyncio
import logging
import operator
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from spoin.content.archetype import classify_archetype
from spoin.core.config import Settings
from spoin.domain.enums import CardType, Difficulty, RejectionStage
from spoin.domain.models import RejectedCard
from spoin.embeddings import Embedder
from spoin.generation.base import CardDraft, ContentGenerator
from spoin.generation.quota import TopicKeyLease

logger = logging.getLogger("spoin.generation.pipeline")


#: ADR-0030: no calibration examples for a linked subtopic-tier -- it gets
#: real, concept-specific calibration from `builds_on` instead.
_NO_DIFFICULTY_EXAMPLES: dict[Difficulty, list[str]] = {difficulty: [] for difficulty in Difficulty}


_SLUG_KEEP = "abcdefghijklmnopqrstuvwxyz0123456789-"


def _slugify(name: str) -> str:
    lowered = "-".join(name.strip().lower().split())
    return "".join(char for char in lowered if char in _SLUG_KEEP) or "topic"


def _existing_title_tag(canonical_title: str, title: str, difficulty: Difficulty) -> str:
    """ADR-0022 + ADR-0007: the already-covered list a generator sees must carry
    the canonical title (so the model can tell a subject is taken), the display
    title (so it doesn't invent the same joke twice under new wording), AND the
    difficulty it was written at (so a beginner and advanced card on the same
    concept differ in depth, not just wording)."""

    label = f"{canonical_title} ({title})" if canonical_title != title else canonical_title
    return f"{label} [{difficulty.value}]"


def _min_cards(target_cards: int, fraction: float) -> int:
    return max(1, round(target_cards * fraction))


#: Canonical name fragments that identify a topic as technical enough to carry
#: `code` archetype cards. Matched case-insensitively against the topic's
#: `canonical_name`. The curriculum prompt already tells the planner "code
#: quota MUST BE 0" for non-CS topics, but the planner is trusted for taste,
#: never for constraints (CLAUDE.md) — this is the enforcement layer.
_TECHNICAL_DOMAIN_MARKERS: tuple[str, ...] = (
    "computer science",
    "programming",
    "software",
    "python",
    "javascript",
    "typescript",
    "java ",  # trailing space avoids matching "Japanese"
    "c++",
    "rust",
    "golang",
    "ruby",
    "sql",
    "database",
    "postgresql",
    "mysql",
    "mongodb",
    "redis",
    "docker",
    "kubernetes",
    "devops",
    "linux",
    "bash",
    "shell",
    "cli",
    "api",
    "web development",
    "frontend",
    "backend",
    "machine learning",
    "data science",
    "data engineering",
    "algorithms",
    "data structures",
    "operating system",
    "networking",
    "cybersecurity",
    "cloud computing",
    "system design",
    "react",
    "angular",
    "vue",
    "node.js",
    "django",
    "flask",
    "fastapi",
    "html",
    "css",
    "git",
)


def is_technical_topic(topic_name: str) -> bool:
    """True when `topic_name` belongs to a domain where code archetype cards
    (fenced code blocks with a language tag) are topically appropriate.

    The check is deliberately broad and false-positive-tolerant: a technical
    topic that slips through still has the curriculum prompt's own "code
    quota MUST BE 0" instruction as a second layer, so the only real cost
    of a false positive is one wasted instruction the planner already obeys.
    A false NEGATIVE — a spiritual topic classified as technical — lets code
    cards through for a topic they make no sense for, which is the bug this
    guard exists to prevent."""

    lowered = topic_name.lower()
    return any(marker in lowered for marker in _TECHNICAL_DOMAIN_MARKERS)


def _card_matches_type(draft: CardDraft, card_type: str, *, topic_name: str | None = None) -> bool:
    """Matches a generated draft to a predetermined card type.

    When `topic_name` is provided and the topic is non-technical,
    a `code` card type never matches — the planner should not have
    assigned it, but the planner is trusted for taste, not constraints
    (CLAUDE.md), so this is the enforcement layer."""

    if card_type == CardType.CODE.value:
        if topic_name is not None and not is_technical_topic(topic_name):
            return False
        return "code" in classify_archetype(draft.body)
    if card_type == CardType.ASCII.value:
        return draft.visual_id is not None or bool(draft.visual_slots)
    tags = classify_archetype(draft.body)
    if card_type == CardType.DIAGRAM.value:
        return "diagram" in tags
    if card_type == CardType.COMPARISON.value:
        return "comparison" in tags
    if card_type == CardType.PROSE.value:
        return not tags and draft.visual_id is None
    return False


class TopicRequest(TypedDict):
    name: str
    description: str


class TopicMatchOutcome(TypedDict):
    """One `match_and_create_topics` result: either an alias onto an existing
    topic (nothing else happened) or a freshly-minted, not-yet-generated one."""

    topic_id: str
    topic_name: str
    matched_existing: bool


class SubtopicPlan(TypedDict):
    topic_id: str
    topic_name: str
    subtopic_id: str
    #: Groups this subtopic with its sibling difficulty tiers of the same
    #: curriculum-authored concept -- what generate_subtopic_cards fans out on.
    subtopic_group_id: str
    difficulty: str
    title: str
    description: str
    target_cards: int
    card_type_quotas: dict[str, int]
    #: Pre-fetched in resolve_and_plan_topic -- see module docstring for why
    #: this can't be a DB read inside generate_subtopic_cards. Spans every
    #: sibling subtopic in the same subtopic_group_id (ADR-0007's cross-tier ask).
    existing_titles: list[str]
    existing_count: int
    #: Bodies of this EXACT subtopic-tier's (not group-wide -- near-dup
    #: detection is subtopic-scoped, see generation/dedup.py) most recent
    #: `rejected_card` rows with stage=near_duplicate, from a prior run.
    #: Prevention feedback (ADR-0030 addendum): the writer sees actual
    #: rejected content and is told not to reproduce it, rather than
    #: rediscovering the same duplicate only to have it rejected again.
    avoid_duplicate_bodies: list[str]
    #: (body, reason) pairs -- as `{"body", "reason"}` dicts, JSON-safe like
    #: everything else here -- for this EXACT subtopic-tier's most recent
    #: pass-2 verification rejections. Unlike `avoid_duplicate_bodies`
    #: (algorithmic similarity, no reasoning), `reason` here is text the
    #: judge model itself gave, fed to the writer so it fixes the actual
    #: problem next time instead of just rewording the same card.
    rejection_feedback: list[dict[str, str]]
    #: Active cards under THIS subtopic-tier with no `Question` row yet --
    #: `gate_and_persist` commits a tier's cards and its questions as two
    #: separate steps, so an interrupted run (crash, quota exhaustion) can
    #: leave cards persisted with no questions at all. `existing_count`
    #: already meeting `target_cards` makes `generate_subtopic_cards` skip
    #: drafting new cards for this tier forever after -- without this,
    #: nothing would ever revisit it to fill the gap. Each entry is
    #: `{"card_id", "title", "body"}` (JSON-safe strings, matching every
    #: other field on this TypedDict).
    cards_missing_questions: list[dict[str, str]]
    #: This EXACT subtopic-tier's already-active `Question.stem`s (capped at
    #: `settings.max_existing_question_stems`), shown to `generate_questions`
    #: so it doesn't repeat a question angle already asked -- and, combined
    #: with the BACKFILL framing `cards_missing_questions` triggers, gives the
    #: writer a sense of what this subtopic-tier's quiz already looks like
    #: rather than writing each batch as if it were the first.
    existing_question_stems: list[str]
    #: Pre-fetched, same reasoning as `existing_titles` -- whether THIS
    #: subtopic-tier already has an active `is_hero` card (task 0006 / ADR-
    #: 0018's real hero mechanism). `generate_subtopic_cards` uses this,
    #: together with `existing_count == 0`, to decide whether to issue the
    #: one-time hero call before its normal rounds.
    has_hero: bool
    #: Dynamic question budget for THIS subtopic-tier, calibrated in
    #: `_load_subtopic_plans` so the topic's total question count stays
    #: within the 200-300 band regardless of how many subtopics it has.
    target_questions: int


class SubtopicGroupPlan(TypedDict):
    """One curriculum concept's 1-3 difficulty tiers, ordered lowest first --
    the Send fan-out unit for card generation (ADR-0026)."""

    topic_id: str
    topic_name: str
    #: Threaded through so `generate_subtopic_cards` can gate+persist its own
    #: group immediately without needing the full `topic_plans` state (a
    #: `Send`-invoked branch only sees its own payload, not the graph's
    #: accumulated state -- see `PipelineState.topic_plans`'s docstring).
    topic_description: str
    tiers: list[SubtopicPlan]


class TopicPlanResult(TypedDict):
    topic_id: str
    topic_name: str
    #: Fed to the quality gate's correction pass as the canonical topic
    #: description (ADR-0030) -- pulled from `Topic.description`, not stored
    #: anywhere else in the plan.
    topic_description: str
    is_survey: bool
    deep_dive_topic_names: list[str]
    subtopics: list[SubtopicPlan]


class SubtopicCardsResult(TypedDict):
    topic_id: str
    subtopic_id: str
    difficulty: str
    drafts: list[CardDraft]
    generator_failures: list[str]
    #: True iff this subtopic-tier has no sibling tiers in its
    #: `subtopic_group_id` -- decides whether the quality gate's two passes
    #: get the hand-curated difficulty example catalog (ADR-0030) instead of
    #: relying on `builds_on`'s real sibling-tier context.
    is_standalone: bool
    #: Passed straight through from `SubtopicPlan` regardless of whether this
    #: tier drafted any new cards this run -- see that field's docstring.
    cards_missing_questions: list[dict[str, str]]
    #: Passed straight through from `SubtopicPlan`, same reasoning as
    #: `cards_missing_questions` above.
    existing_question_stems: list[str]
    #: Passed straight through from `SubtopicPlan`.
    target_questions: int


class TopicJob(TypedDict):
    """The outer fan-out's per-branch payload."""

    topic_id: str
    #: This topic's key-lease size for the run (ADR-0078) -- the worker's
    #: allocation, or `settings.default_topic_key_budget` when it couldn't know
    #: the tier width yet. `resolve_and_plan_topic` corrects it post-curriculum.
    key_budget: int


class PipelineState(TypedDict, total=False):
    #: Already-existing Topic ids (ADR-0025 decided that upstream).
    topic_ids: list[str]
    #: topic_id -> key-lease size for the run (ADR-0078). Set once in
    #: `run_generation_pipeline`; `fan_out_topics` copies each entry into the
    #: matching `TopicJob`.
    topic_key_budgets: dict[str, int]
    #: Only set on a per-branch Send invocation (outer fan-out).
    topic_job: TopicJob
    #: Globally accumulated across every topic branch -- used by gate_and_persist
    #: to build the final per-topic report. NOTE: this is also the only way
    #: `resolve_and_plan_topic` gets its own subtopics to a downstream fan-out --
    #: see that function's docstring for why a plain (non-reducer) key doesn't
    #: work here: concurrent topic branches in the same superstep all write into
    #: the SAME shared channels, and a plain "last value" channel raises
    #: `InvalidUpdateError` the moment two branches write to it in one step.
    #: `Send`-created branches are NOT isolated forks with their own local state.
    topic_plans: Annotated[list[TopicPlanResult], operator.add]
    #: Only set on a per-branch Send invocation (inner fan-out).
    subtopic_group_job: SubtopicGroupPlan
    #: One dict per subtopic-tier gating ROUND this run (topic_id, subtopic_id,
    #: difficulty, accepted/rejected/failed, new_card_ids) -- written by
    #: `generate_subtopic_cards` itself (it gates+persists its own group
    #: immediately, ADR-0026), not by a separate global writer node.
    #:
    #: Per ROUND, not per tier: `_redraft_until_bar` appends a fresh entry for
    #: every redraft round, so one tier can appear here many times over. Anything
    #: that must happen once per TIER has to merge by
    #: (topic_id, subtopic_id, difficulty) first -- see
    #: `_run_topic_question_phase`, which does exactly that and whose regression
    #: test exists because doing it per entry silently generated a tier's
    #: questions once per round.
    #:
    #: Question counts are NOT here: questions are written by the topic-wide
    #: phase at the fan-in (ADR-0074), which reports its own totals. `new_card_ids`
    #: is what that phase uses to tell a card drafted THIS run from one it is
    #: merely backfilling.
    item_reports: Annotated[list[dict[str, object]], operator.add]
    report: dict[str, object]


@dataclass
class _Runtime:
    """Dependencies threaded through `config["configurable"]` rather than graph
    state -- none of these are pipeline *data*."""

    session: AsyncSession
    generator: ContentGenerator
    embedder: Embedder
    settings: Settings
    batch_id: uuid.UUID
    #: topic_id -> the key lease that topic holds for this run (ADR-0078).
    #: Populated by `resolve_and_plan_topic` once curriculum exists, read by the
    #: subtopic-group branches and the question phase to scope their key claims,
    #: and released in `gate_and_persist` / `run_generation_pipeline`'s finally.
    #: A `Send`-spawned branch does not inherit the parent node's contextvars, so
    #: the lease can't ride `CURRENT_KEY_CLAIM` -- it lives here on the shared
    #: runtime instead, keyed by topic.
    topic_leases: dict[str, TopicKeyLease] = field(default_factory=dict)
    topic_plan_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: topic_id -> curated-library entry ids already used by the ASCII fetcher
    #: for this topic (ADR-0080). Seeded from `topic_used_ascii_ids` on the first
    #: fetch for a topic (active cards + rejected drafts, the cross-pass source
    #: of truth), then extended in-process as the fetcher picks within this run
    #: so a scene is never reused across tiers of the same pass either. Guarded
    #: by `topic_ascii_lock` -- concurrent subtopic branches share it.
    topic_ascii_used: dict[str, set[str]] = field(default_factory=dict)
    topic_ascii_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: `AsyncSession` is not safe for concurrent use across coroutines -- every
    #: DB-touching section of `_process_gate_item` (dedup reads, card/question
    #: persist+commit) is serialized through this lock so subtopic-tiers can
    #: still run their LLM phases (correction, verification, question
    #: generation) fully concurrently. See `gate_and_persist`'s docstring.
    session_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


#: `config` is deliberately left untyped on every node function below (here and
#: in resolve_and_plan_topic / generate_subtopic_cards / gate_and_persist).
#: LangGraph's own node config type is `RunnableConfig` (from langchain_core), and
#: at runtime it inspects each node's `config` parameter annotation -- if present
#: and not exactly `RunnableConfig`, it emits a `UserWarning` ("should be typed as
#: RunnableConfig"), which this repo's `filterwarnings = ["error"]` pytest config
#: turns into a hard test failure. Importing `RunnableConfig` here to satisfy it
#: would violate ADR-0002/0024's "pipeline.py never imports langchain*" boundary
#: (enforced by tests/test_architecture.py) for a type that carries no
#: model/prompt surface at all. Leaving the parameter unannotated is the one
#: option LangGraph's own inspection treats as a non-issue.
def _runtime(config) -> _Runtime:  # type: ignore[no-untyped-def]
    configurable = config["configurable"]
    runtime = configurable["runtime"]
    assert isinstance(runtime, _Runtime)
    return runtime


@dataclass
class _GateItem:
    """One subtopic-tier's worth of drafts, tracked through the whole gate
    (ADR-0030) so the two concurrent LLM phases and the sequential DB phase
    can all find their way back to the right subtopic/topic report."""

    topic_id: str
    subtopic_id: str
    difficulty: str
    topic_name: str
    topic_description: str
    difficulty_examples: dict[Difficulty, list[str]]
    survivors: list[CardDraft]
    #: (draft, reason) for cards that never made it past structural
    #: validation -- kept as the ORIGINAL draft, since correction never ran.
    structural_rejects: list[tuple[CardDraft, str]]
    generator_failure_count: int
    #: Existing active cards under this tier with no Question row yet (see
    #: `SubtopicPlan.cards_missing_questions`) -- question generation runs on
    #: these IN ADDITION TO any cards accepted by the gate this run, so a
    #: tier that already has all its cards still gets its questions backfilled.
    existing_cards_missing_questions: list[dict[str, str]] = field(default_factory=list)
    #: This tier's already-active question stems (see
    #: `SubtopicPlan.existing_question_stems`) -- shown to `generate_questions`
    #: so it doesn't repeat a question angle already asked.
    existing_question_stems: list[str] = field(default_factory=list)
    #: Dynamic question budget for this tier (see `SubtopicPlan.target_questions`).
    target_questions: int = 0
    #: Filled in by later phases.
    corrected: list[CardDraft] = field(default_factory=list)
    correction_failure_count: int = 0
    dedup_survivors: list[tuple[CardDraft, list[float]]] = field(default_factory=list)
    #: (draft, reason) for near-duplicate rejects, post-correction.
    dedup_rejects: list[tuple[CardDraft, str]] = field(default_factory=list)
    verified: list[tuple[CardDraft, list[float], Difficulty]] = field(default_factory=list)
    #: (draft, reason) for pass-2 rejects, post-correction.
    verification_rejects: list[tuple[CardDraft, str]] = field(default_factory=list)
    verification_failure_count: int = 0


#: Stamped into every `gen_meta` this pipeline writes -- cards, questions, and
#: rejected drafts alike (ADR-0059). This is the PROMPT/pipeline generation, not
#: `Card.version`, which is family-scoped regeneration lineage and means
#: something entirely different; the two are unrelated and must not be conflated
#: in a query. Bump it when the prompts or the pipeline's shape change enough
#: that content either side of the change shouldn't be pooled when judging
#: quality -- which is the whole reason it is recorded.
#:
#: Corpus written before this existed carries NO `prompt_version` key at all
#: (only `backend`/`generated_at`/`batch_id`), and is v1 by absence. Nothing
#: backfills it: rewriting `gen_meta` across the live corpus would be a bulk
#: UPDATE on real production content to record something the absence already
#: says (CLAUDE.md's database rule). Query v1 as
#: `gen_meta->>'prompt_version' IS NULL`.
#:
#: v2 -> v3 (ADR-0066): over-budget ASCII art is now redrawn and, failing that,
#: rejected with its card, instead of silently dropped; the card prompt asks
#: for art more freely and the curriculum quota for `ascii` cards went up. v3
#: corpora carry a materially higher share of art-bearing cards and should not
#: be pooled with v2 when judging quality.
#:
#: v3 -> v4 (ADR-0067 + ADR-0068): mermaid replaces hand-drawn ASCII diagrams;
#: ASCII scenes are strictly pictorial; a curated ~2,487-entry reference
#: library is wired in via embedding retrieval for every planned ascii card;
#: three generation-time defects (fence wrapper, duplicate scene in body,
#: structurally-invalid mermaid) are now enforced deterministically server-side.
#: v4 content should not be pooled with v3 when judging quality.
#:
#: v4 -> v5 (ADR-0079 + ADR-0080): the ASCII library is gags-only (the
#: informative-visualisation file is no longer loaded) and the curriculum's
#: ascii floor rose from 2-3 to 4-5 per subtopic-tier; a dedicated ASCII FETCHER
#: node now picks one curated scene per ascii card and captions it (the writer
#: no longer draws matched cards), and each scene is single-use within a topic
#: (`visual_slots['src_id']`). v5 corpora carry a materially different ASCII mix
#: -- more cards, all gags, mostly library-sourced -- and should not be pooled
#: with v4 when judging quality.
CARD_PROMPT_VERSION = 5


def _clean_null_bytes(val: Any) -> Any:
    if isinstance(val, str):
        return val.replace("\x00", "")
    if isinstance(val, dict):
        return {
            (k.replace("\x00", "") if isinstance(k, str) else k): _clean_null_bytes(v)
            for k, v in val.items()
        }
    if isinstance(val, list):
        return [_clean_null_bytes(item) for item in val]
    return val


def _rejected_card(
    *,
    topic_id: str,
    subtopic_id: str,
    draft: CardDraft,
    stage: RejectionStage,
    reason: str,
    generated_at: str,
    backend: str,
    batch_id: uuid.UUID,
) -> RejectedCard:
    return RejectedCard(
        topic_id=uuid.UUID(topic_id),
        subtopic_id=uuid.UUID(subtopic_id),
        requested_difficulty=draft.difficulty,
        title=_clean_null_bytes(draft.title[:120]),
        canonical_title=_clean_null_bytes(draft.canonical_title[:160]),
        summary=_clean_null_bytes(draft.summary),
        body=_clean_null_bytes(draft.body),
        stage=stage,
        reason=_clean_null_bytes(reason),
        gen_meta={
            "backend": backend,
            "generated_at": generated_at,
            "batch_id": str(batch_id),
            # Rejections are stamped too, not just the cards that survived: a
            # v2-vs-v1 comparison that only sees what passed the gate measures
            # the gate, not the prompts (CLAUDE.md -- a rejected draft plus its
            # reason is a labeled example, and it is only usable as one if you
            # can tell which prompt version produced it).
            "prompt_version": CARD_PROMPT_VERSION,
            # ADR-0080: a rejected ascii card still burns the curated-library
            # scene it used -- recorded here (not `visual_slots`, which
            # RejectedCard has no column for) so `topic_used_ascii_ids` keeps
            # excluding it from later fetches in the topic.
            **(
                {"src_id": (draft.visual_slots or {})["src_id"]}
                if draft.visual_slots and draft.visual_slots.get("src_id")
                else {}
            ),
        },
    )
