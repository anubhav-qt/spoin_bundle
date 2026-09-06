"""Retrieved corpus context, reused across a subtopic.

Shape and reasoning: docs/adr/0089-retrieval-grounded-generation.md.
`frog.retrieval` does the search; this module decides what a prompt actually gets.

**Two passages, asked for as two.** `Settings.grounding_chunks` is the `k` handed to
the database, not a cap applied to a wider result. There is no token budget and no
score floor — see that setting for why neither can earn its place: the ingestion
contract already bounds two passages at roughly 1200 prompt tokens, and the corpus
covers a topic before that topic is live. This module used to pack a top-10 result
down to a budget; that budget could never bind, which is the dead code `8a8e64c`
removed and this change stops recreating.

**Why this lives in `spoin` and not in `frog`.** It is prompt-shaped work — what a
generation prompt is given — which is this package's job rather than the search
package's. frog answers "what is most similar"; this decides what that is worth.

**Canon is not retrieved.** `generation/prompts/canon.py` pins it into every system
prompt as a fixed preamble (rag-design-space §3.9, amending ADR-0088), so retrieval
here asks for `topic_source` only and the whole budget goes to subject matter. Letting
canon compete for retrieval slots fails in both directions: it displaces facts the
model needed, and it is sometimes not retrieved at all for a call that needed it.

**Retrieval is per subtopic GROUP, not per call** (rag-design-space §3.7). The query
is known before generation and does not change within a subtopic — the drafter, the
redraft after a rejection, and the verifier grounding its check in the same passages
(ADR-0089) all want the same context. `Grounding` caches on that, which turns a
per-call cost into a per-subtopic one. Difficulty is deliberately NOT part of the
query or the key: difficulty-aware retrieval is rag-design-space §3.11 and is
deferred, and tier is a matter of how the card is WRITTEN, which is the prompt's job
(CLAUDE.md's trusted-for-taste-never-for-constraints split).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from frog.curriculum.contract import split_grounding_ref
from frog.embeddings import Embedder
from frog.retrieval import Hit, corpus_version, search, search_many
from frog.universe.models import Chunk, Document, DocumentKind
from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.db import UniverseNotConfiguredError, universe_session_scope
from spoin.generation.base import CardPlan
from spoin.generation.load_balancer import estimate_tokens

logger = logging.getLogger(__name__)


class GroundingOutcome(StrEnum):
    """Why a call's prompt carries the context it carries.

    Three states rather than a bool, because CLAUDE.md's rule applies exactly here: a
    corpus that was searched and had nothing relevant is a **content** fact about the
    corpus, and a corpus that could not be reached is an **infrastructure** fact about
    this process. Folding them into "not grounded" is how a run of ungrounded cards
    gets read as a thin corpus when it was an unset environment variable — or worse,
    the reverse, with the corpus-authoring track sent to write material that was
    always there.
    """

    GROUNDED = "grounded"
    #: The corpus was searched and returned nothing to pack.
    NO_MATCH = "no_match"
    #: The corpus could not be searched at all. Never a statement about the corpus.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GroundingContext:
    """What one subtopic's retrieval produced, ready to drop into a prompt.

    Immutable and shared: the same instance is handed to every call in a subtopic
    group, including calls running concurrently on different tiers.
    """

    #: The prompt block, ready to interpolate. Empty string whenever `outcome` is not
    #: `GROUNDED`, so a prompt template can always interpolate it — the same
    #: empty-block-means-omitted convention `_format_builds_on` and friends use.
    block: str

    #: The chunks that produced `block`, in the order they appear in it. ADR-0089
    #: records these on the card so it can cite what grounded it — which is also what
    #: makes "which cards did this retracted chunk ground?" answerable
    #: (rag-design-space §3.12).
    chunk_ids: tuple[uuid.UUID, ...]

    outcome: GroundingOutcome

    #: `estimate_tokens(block)`. Carried rather than recomputed because it is what
    #: Phase 4 measures and what a caller logs; recomputing it at each call site is
    #: how two slightly different numbers end up in the same report.
    estimated_tokens: int

    #: How many hits the search returned before packing cut it to the budget. The
    #: gap between this and `len(chunk_ids)` is the only visible signal that the
    #: budget is binding, and it is the number Phase 4 wants.
    retrieved: int

    @classmethod
    def empty(cls, outcome: GroundingOutcome) -> GroundingContext:
        return cls(block="", chunk_ids=(), outcome=outcome, estimated_tokens=0, retrieved=0)


def build_card_query(topic_name: str, subtopic_title: str, plan: CardPlan) -> str:
    """The retrieval query for ONE card, from the brief the planner wrote for it.

    ADR-0059's planning pass is what makes per-card retrieval possible at all: it
    produces a `CardPlan` for every card BEFORE any card is written, so there is a
    real per-card query at the moment retrieval has to happen. rag-design-space §3.7
    assumed no such query existed and cached one block per subtopic on that basis.

    `content_direction` carries the angle and `canonical_title` the concept; the topic
    and subtopic keep a short brief from matching the wrong field entirely.
    """

    return f"{topic_name}: {subtopic_title}. {plan.canonical_title}. {plan.content_direction}"


def build_query(topic_name: str, subtopic_title: str, subtopic_description: str) -> str:
    """The retrieval query for a subtopic.

    The description carries most of the signal — it is prose written for a model to
    read (`Subtopic.description`), not a label — and the topic name disambiguates a
    title that is only meaningful inside its topic ("Snapshots" under PostgreSQL
    versus under version control). Not normalized through
    `normalize_topic_text`: that normalizer exists to make two spellings of a topic
    NAME match (ADR-0093), and stripping punctuation from a sentence before embedding
    it discards signal the model was trained on.
    """

    return f"{topic_name}: {subtopic_title}. {subtopic_description}"


def render_block(hits: list[Hit]) -> str:
    """The retrieved passages as a prompt block, or `""` for no hits.

    Each passage is labelled with where it came from. That is not decoration: the
    verifier is asked to check a claim against a passage, and a passage the model
    cannot tell apart from the model's own memory is not evidence. The chunk text is
    interpolated whole, contextual header included — that header is what was embedded
    (task 0038 Phase 2) and stripping it makes two identically-worded sections
    indistinguishable.
    """

    if not hits:
        return ""
    passages = "\n\n".join(
        f"--- source {n + 1}: {hit.document_title} ({hit.source}) ---\n{hit.text}"
        for n, hit in enumerate(hits)
    )
    return (
        "\nSource material, retrieved for this subtopic. Everything factual you write "
        "must be supported by it; where it is silent, say less rather than filling the "
        "gap from memory:\n"
        f"{passages}\n"
    )


class Grounding:
    """Retrieval for a generation run, cached per subtopic group.

    One instance per run rather than a module-level singleton: the cache is only
    correct while the corpus is fixed, and tying its lifetime to a run makes that
    obvious. The corpus version is checked anyway (`corpus_version`), because the
    worker is long-lived and the owner re-ingests on the same machine while it runs.

    **Never raises.** A corpus that cannot be reached degrades to ungrounded
    generation, which is the pre-ADR-0089 behaviour and produces cards; a retrieval
    failure that aborted a run would trade every card for a missing environment
    variable. The reason is logged and reported in `GroundingContext.outcome` rather
    than swallowed — an ungrounded run has to be visible as one.
    """

    def __init__(self, embedder: Embedder, *, chunks: int) -> None:
        self._embedder = embedder
        self._chunks = chunks
        self._cache: dict[tuple[str, uuid.UUID], GroundingContext] = {}
        #: Resolved scopes, keyed by corpus version + the refs themselves. A tier's
        #: refs resolve to the same chunk ids for every batch and every redraft
        #: round it runs, and re-resolving them per batch would be a join per call.
        self._scopes: dict[tuple[str, tuple[str, ...]], list[uuid.UUID]] = {}

    async def for_subtopic(
        self,
        *,
        subtopic_group_id: uuid.UUID,
        topic_name: str,
        subtopic_title: str,
        subtopic_description: str,
    ) -> GroundingContext:
        """Context for every call in this subtopic group, retrieved at most once.

        A miss is not cached: `UNAVAILABLE` is usually transient (the corpus database
        was restarting), and caching it would make one blip ground nothing for the
        rest of the run. `NO_MATCH` *is* cached — it is a fact about the corpus at
        this version, and re-asking will not change it.

        A cache hit still costs one `corpus_version` query, which is a count and a max
        over a few hundred rows. That is deliberately not optimised away: it is what
        makes the cache correct across a mid-run re-ingestion, and it is noise next to
        the LLM call this context is being assembled for.
        """

        try:
            async with universe_session_scope() as session:
                version = await corpus_version(session)
                key = (version, subtopic_group_id)
                cached = self._cache.get(key)
                if cached is not None:
                    return cached

                hits = await search(
                    session,
                    self._embedder,
                    build_query(topic_name, subtopic_title, subtopic_description),
                    #: Asked of the database as the final count, not trimmed to it
                    #: afterwards -- retrieving ten to keep two is nine wasted rows
                    #: per call and an invitation to re-rank in the application.
                    k=self._chunks,
                    #: Canon is pinned into the system prompt, not retrieved
                    #: (rag-design-space §3.9), so this is subject matter only.
                    kinds=[DocumentKind.TOPIC_SOURCE],
                )
        except UniverseNotConfiguredError:
            logger.warning("grounding unavailable: SPOIN_UNIVERSE_DATABASE_URL is not set")
            return GroundingContext.empty(GroundingOutcome.UNAVAILABLE)
        except SQLAlchemyError:
            logger.exception("grounding unavailable: the corpus database could not be read")
            return GroundingContext.empty(GroundingOutcome.UNAVAILABLE)

        context = self._context(hits)
        self._cache[key] = context
        return context

    async def for_cards(
        self,
        *,
        topic_name: str,
        subtopic_title: str,
        plans: Sequence[CardPlan],
        grounding_refs: Sequence[str] | None,
    ) -> CardGrounding:
        """Retrieve per card, send one deduplicated block (generation-pipeline-v2).

        Two things happen here that `for_subtopic` could not:

        **Retrieval is per card.** Each plan gets its own query, so a batch of fifteen
        cards no longer shares the two passages their subtopic happened to match.
        rag-design-space 3.7 cached one block per subtopic because "the query does not
        change within a subtopic" -- true before ADR-0059's planner existed, false now.

        **The author declares the scope.** `grounding_refs` names the sections this
        tier's cards may be written from; ranking happens WITHIN them. That is
        CLAUDE.md's rule applied to retrieval -- the constraint belongs to the author,
        who knows which passages teach this tier, and the taste belongs to the machine,
        which picks better among a dozen candidates than a human would across hundreds
        of cards.

        **The allowance.** When the declared scope cannot fill `k` for a card, the
        shortfall is topped up from an open corpus-wide query. It is meant to be rare,
        it keeps a slightly-wrong declaration from starving a card, and it is COUNTED
        (`allowance_used`) rather than silent -- a tier that keeps using it is
        reporting that its scope is too narrow.

        Never raises, same contract as `for_subtopic`: an unreachable corpus degrades
        to ungrounded generation rather than losing the run.
        """

        if not plans:
            return CardGrounding.empty(GroundingOutcome.NO_MATCH)

        queries = [build_card_query(topic_name, subtopic_title, plan) for plan in plans]
        try:
            async with universe_session_scope() as session:
                version = await corpus_version(session)
                scope = await self._scope_for(session, version, grounding_refs)
                per_card = await self._retrieve(session, queries, scope)
        except UniverseNotConfiguredError:
            logger.warning("grounding unavailable: SPOIN_UNIVERSE_DATABASE_URL is not set")
            return CardGrounding.empty(GroundingOutcome.UNAVAILABLE)
        except SQLAlchemyError:
            logger.exception("grounding unavailable: the corpus database could not be read")
            return CardGrounding.empty(GroundingOutcome.UNAVAILABLE)

        allowance_used = sum(1 for _hits, topped_up in per_card if topped_up)

        #: The union, in first-seen order, deduplicated by chunk id. Cards in one batch
        #: share a subtopic, so this collapses hard -- which is what makes per-card
        #: retrieval affordable inside a batched call.
        union: list[Hit] = []
        seen: set[uuid.UUID] = set()
        for hits, _topped_up in per_card:
            for hit in hits:
                if hit.chunk_id not in seen:
                    seen.add(hit.chunk_id)
                    union.append(hit)

        if not union:
            return CardGrounding.empty(GroundingOutcome.NO_MATCH)

        block = render_block(union)
        return CardGrounding(
            block=block,
            chunk_ids_by_index={
                index: tuple(hit.chunk_id for hit in hits)
                for index, (hits, _topped_up) in enumerate(per_card)
            },
            union=tuple(hit.chunk_id for hit in union),
            outcome=GroundingOutcome.GROUNDED,
            estimated_tokens=estimate_tokens(block),
            retrieved=len(union),
            allowance_used=allowance_used,
        )

    async def block_for_chunk_ids(self, chunk_ids: Sequence[uuid.UUID]) -> str:
        """The prompt block for an EXPLICIT set of chunks, in relevance-free order.

        This is how the gate keeps ADR-0089's invariant now that drafting is per
        card: the corrector and the verifier are handed the passages the cards
        in front of them were actually written from, read back by id, rather
        than a fresh subtopic query that would show them different sources. A
        verifier holding different evidence than the writer turns a disagreement
        between two models into a coin flip, which is the failure ADR-0089
        exists to remove.
        """

        if not chunk_ids:
            return ""
        try:
            async with universe_session_scope() as session:
                rows = (
                    await session.execute(
                        select(
                            Chunk.id,
                            Chunk.text,
                            Chunk.ordinal,
                            Chunk.topic_tags,
                            Document.id.label("document_id"),
                            Document.title,
                            Document.source,
                            Document.source_path,
                            Document.kind,
                            Document.category,
                            Document.sub_category,
                        )
                        .join(Document, Document.id == Chunk.document_id)
                        .where(Chunk.id.in_(list(dict.fromkeys(chunk_ids))))
                    )
                ).all()
                hits = [
                    Hit(
                        chunk_id=row.id,
                        document_id=row.document_id,
                        score=0.0,
                        text=row.text,
                        ordinal=row.ordinal,
                        topic_tags=list(row.topic_tags),
                        document_title=row.title,
                        source=row.source,
                        source_path=row.source_path,
                        kind=row.kind,
                        category=row.category,
                        sub_category=row.sub_category,
                    )
                    for row in rows
                ]
        except UniverseNotConfiguredError:
            return ""
        except SQLAlchemyError:
            logger.exception("grounding: could not read back the drafters' passages")
            return ""

        return render_block(hits)

    async def _scope_for(
        self, session: AsyncSession, version: str, refs: Sequence[str] | None
    ) -> list[uuid.UUID] | None:
        """This tier's declared scope as chunk ids, or None for "no scope declared".

        No declaration means the open corpus-wide query. Every reference failing to
        resolve produces the same open query but is a completely different fact, so it
        is logged at ERROR: the cards look identical either way, and confusing the two
        would hide a whole tier grounding on material its curriculum never named.
        """

        if not refs:
            return None
        key = (version, tuple(refs))
        cached = self._scopes.get(key)
        if cached is not None:
            return cached

        chunk_ids, missing = await _resolve_scope(session, refs)
        if missing:
            logger.warning(
                "grounding: %d of %d declared reference(s) did not resolve -- %s. "
                "Re-run `make curriculum-check`, then `make corpus-ingest`.",
                len(missing),
                len(refs),
                "; ".join(missing[:3]),
            )
        if not chunk_ids:
            logger.error(
                "grounding: NONE of the %d declared reference(s) resolved; this tier "
                "falls back to an open corpus-wide query, so its cards are NOT scoped "
                "the way its curriculum says they are.",
                len(refs),
            )
            return None
        self._scopes[key] = chunk_ids
        return chunk_ids

    async def _retrieve(
        self,
        session: AsyncSession,
        queries: list[str],
        scope: list[uuid.UUID] | None,
    ) -> list[tuple[list[Hit], bool]]:
        """Top-k per query within `scope`, topped up from the open corpus when short.

        Returns `(hits, allowance_was_used)` per query, in the order given.
        """

        scoped = await search_many(
            session,
            self._embedder,
            queries,
            k=self._chunks,
            kinds=[DocumentKind.TOPIC_SOURCE],
            include_chunk_ids=scope,
        )
        if scope is None:
            return [(hits, False) for hits in scoped]

        #: The trigger is STRUCTURAL -- fewer chunks came back than were asked for --
        #: rather than a similarity floor. No calibrated floor exists yet, and inventing
        #: a constant to defend a guess is worse than not having one; the scores are
        #: recorded per card, so the first real run can settle what the floor should be.
        short = [index for index, hits in enumerate(scoped) if len(hits) < self._chunks]
        if not short:
            return [(hits, False) for hits in scoped]

        logger.info(
            "grounding: declared scope filled %d/%d card(s); topping the rest up from "
            "the open corpus",
            len(queries) - len(short),
            len(queries),
        )
        topped = await search_many(
            session,
            self._embedder,
            [queries[index] for index in short],
            k=self._chunks,
            kinds=[DocumentKind.TOPIC_SOURCE],
            exclude_chunk_ids=scope,
        )
        results: list[tuple[list[Hit], bool]] = [(hits, False) for hits in scoped]
        for index, extra in zip(short, topped, strict=True):
            hits = scoped[index]
            room = self._chunks - len(hits)
            results[index] = (hits + extra[:room], True)
        return results

    def _context(self, hits: list[Hit]) -> GroundingContext:
        if not hits:
            return GroundingContext.empty(GroundingOutcome.NO_MATCH)
        block = render_block(hits)
        return GroundingContext(
            block=block,
            chunk_ids=tuple(hit.chunk_id for hit in hits),
            outcome=GroundingOutcome.GROUNDED,
            estimated_tokens=estimate_tokens(block),
            retrieved=len(hits),
        )


@dataclass(frozen=True)
class CardGrounding:
    """Per-card retrieval for one batch of cards, plus how it was obtained.

    `blocks` is what the prompt carries: ONE deduplicated block for the whole batch,
    not a block per card. Addressing passages to individual cards in the prompt --
    "card 1 write from P1,P2; card 2 from P3,P4" -- would load the whole scheme onto
    instruction-following, which ADR-0090 names as the drafting model's weak spot. The
    union costs less than it looks: cards in one batch share a subtopic, so their
    passages overlap heavily and collapse.

    `chunk_ids_by_index` stays exact per card regardless, because we know which query
    returned what. That is what finally makes `card.grounded_chunk_ids` mean "the
    passages retrieved for THIS card" rather than "the passages this card's subtopic
    got", which is what ADR-0089 wanted and rag-design-space §3.12 needs.
    """

    block: str
    #: Position in the batch -> the chunks retrieved for that card, in rank order.
    chunk_ids_by_index: dict[int, tuple[uuid.UUID, ...]]
    #: Every chunk in `block`, deduplicated. The citation for a card that has no
    #: brief of its own -- the hero call, or a round whose planning failed -- which
    #: read this block and nothing else.
    union: tuple[uuid.UUID, ...]
    outcome: GroundingOutcome
    estimated_tokens: int
    #: Distinct chunks in `block`, after the union collapsed duplicates.
    retrieved: int
    #: Cards whose declared scope could not fill `k` and were topped up from an open
    #: corpus-wide query. Counted, never silent: a tier that keeps falling back is
    #: telling the author their `grounding` is too narrow, and that is feedback to act
    #: on rather than a failure to paper over.
    allowance_used: int

    def chunk_ids_for(self, count: int) -> list[tuple[uuid.UUID, ...]]:
        """Per-card citations for the `count` drafts a writer actually returned.

        Matched positionally, because the writer is briefed with the plans in
        order and asked to write one card per brief. It is best-effort by
        construction -- the model is trusted for taste, never for constraints
        (CLAUDE.md), so it can return fewer cards than briefs, or more.

        A card with no matching brief cites the ROUND's union rather than
        nothing: it was written from that block, so the union is the honest
        answer, and an empty citation would read as ungrounded.
        """

        return [self.chunk_ids_by_index.get(index, self.union) for index in range(count)]

    @classmethod
    def empty(cls, outcome: GroundingOutcome) -> CardGrounding:
        return cls(
            block="",
            chunk_ids_by_index={},
            union=(),
            outcome=outcome,
            estimated_tokens=0,
            retrieved=0,
            allowance_used=0,
        )


async def _resolve_scope(
    session: AsyncSession, refs: Sequence[str]
) -> tuple[list[uuid.UUID], list[str]]:
    """Authored `<path>#<heading>` references -> chunk ids, plus the ones that missed.

    A join on `(document.source_path, chunk.heading)`, which is why `chunk.heading` is
    a column rather than something recovered from the front of `chunk.text`: a prefix
    match would resolve `#Ownership` to `## Ownership Foundations`, silently grounding
    a tier on the wrong passage.

    Unresolved references are RETURNED, not logged and dropped. A curriculum whose
    refs stopped resolving -- a renamed heading, or a corpus not re-ingested since --
    is a condition the run has to be able to report, and it is the difference between
    "the author scoped this narrowly" and "the scope evaporated".
    """

    #: (ref, (path, heading)) kept together: a malformed ref has no key, and zipping
    #: two lists that dropped different elements would misattribute the misses.
    keyed = [(ref, split_grounding_ref(ref)) for ref in refs]
    wanted = [key for _ref, key in keyed if key is not None]
    if not wanted:
        return [], list(refs)

    rows = (
        await session.execute(
            select(Document.source_path, Chunk.heading, Chunk.id)
            .join(Chunk, Chunk.document_id == Document.id)
            .where(tuple_(Document.source_path, Chunk.heading).in_(wanted))
        )
    ).all()
    found = {(source_path, heading): chunk_id for source_path, heading, chunk_id in rows}

    chunk_ids: list[uuid.UUID] = []
    missing: list[str] = []
    for ref, key in keyed:
        chunk_id = found.get(key) if key is not None else None
        if chunk_id is None:
            missing.append(ref)
        else:
            chunk_ids.append(chunk_id)
    return chunk_ids, missing
