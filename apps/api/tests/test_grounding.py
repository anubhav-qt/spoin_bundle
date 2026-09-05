"""What a grounded prompt actually gets, and what it costs.

Two halves. The packing and rendering half is pure and needs nothing. The retrieval
half runs against the real corpus schema on `the_spoin_universe_test`, because what is
under test there is behaviour the database owns — the `topic_source` filter, and
`corpus_version` moving when the corpus does.

The `Grounding` tests count searches rather than asserting on their results. The cache
(rag-design-space §3.7) exists to turn a per-call cost into a per-subtopic one, so
"how many times did this hit the corpus" *is* the property, and it is invisible in the
returned context.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from frog.embeddings import Embedder, HashEmbedder
from frog.retrieval import Hit
from frog.universe.models import EMBEDDING_DIM, Chunk, Document, DocumentKind, DocumentScope
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from conftest import UNIVERSE_TEST_DATABASE_URL
from spoin.core.db import UniverseNotConfiguredError, get_universe_engine
from spoin.generation import grounding as grounding_module
from spoin.generation.grounding import (
    Grounding,
    GroundingContext,
    GroundingOutcome,
    build_query,
    pack,
    render_block,
)
from spoin.generation.load_balancer import estimate_tokens


def _hit(text_: str, *, title: str = "MVCC", score: float = 0.7) -> Hit:
    return Hit(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        score=score,
        text=text_,
        ordinal=0,
        topic_tags=["postgresql"],
        document_title=title,
        source="https://example.invalid/mvcc",
        source_path="cs/pg/mvcc.md",
        kind=DocumentKind.TOPIC_SOURCE,
        category="computer science",
        sub_category="databases",
    )


# -- packing and rendering -----------------------------------------------------


def test_pack_keeps_the_best_prefix_that_fits_and_drops_the_rest() -> None:
    """Hits arrive most-similar-first, so the prefix that fits is the best that fits.

    The dropped hits are dropped, not spilled into a second block: `pack_by_tokens`'s
    spillover means "these become another request", which is the right answer for a
    batch of cards and the wrong one for context that lost a relevance contest.
    """

    hits = [_hit("word " * 200) for _ in range(5)]
    per_hit = estimate_tokens(hits[0].text)

    packed = pack(hits, budget=per_hit * 2 + 100, max_chunks=99)

    assert packed == hits[:2]


def test_pack_stops_at_max_chunks_even_when_the_budget_would_allow_more() -> None:
    """The count is the ceiling and the budget cuts it shorter (ADR-0085's posture) —
    a prompt of thirty one-line fragments is within any budget and unreadable."""

    hits = [_hit("short") for _ in range(10)]

    assert len(pack(hits, budget=1_000_000, max_chunks=3)) == 3


def test_pack_keeps_one_oversized_hit_rather_than_returning_nothing() -> None:
    """`pack_by_tokens` gives an over-budget item its own chunk rather than dropping
    it, and taking the first chunk inherits that. Grounding a card in one long passage
    beats grounding it in nothing — the budget is a throughput target, not a
    correctness bound."""

    huge = _hit("word " * 10_000)

    assert pack([huge], budget=10, max_chunks=8) == [huge]


def test_pack_of_nothing_is_nothing() -> None:
    assert pack([], budget=1000, max_chunks=8) == []


def test_render_block_labels_every_passage_with_where_it_came_from() -> None:
    """A passage the model cannot tell from its own memory is not evidence, and the
    verifier is being asked to check claims against these specifically."""

    block = render_block(
        [_hit("Snapshot isolation.", title="MVCC"), _hit("Raft.", title="Consensus")]
    )

    assert "--- source 1: MVCC (https://example.invalid/mvcc) ---" in block
    assert "--- source 2: Consensus (https://example.invalid/mvcc) ---" in block
    assert "Snapshot isolation." in block
    assert "Raft." in block


def test_render_block_of_nothing_is_the_empty_string() -> None:
    """Prompt templates interpolate this unconditionally, the same way
    `_format_builds_on` and the other optional blocks work."""

    assert render_block([]) == ""


def test_the_chunks_contextual_header_survives_into_the_prompt() -> None:
    """It is what was embedded (task 0038 Phase 2). Stripping it would leave two
    identically-worded sections of different documents indistinguishable."""

    block = render_block([_hit("MVCC — Snapshot isolation\n\nEach transaction sees a snapshot.")])

    assert "MVCC — Snapshot isolation" in block


def test_the_query_carries_the_topic_as_well_as_the_subtopic() -> None:
    """ "Snapshots" means something different under PostgreSQL than under version
    control, and the corpus is searched cross-topic (ADR-0088) — so the topic is what
    keeps the disambiguation in the query rather than in a filter."""

    query = build_query("PostgreSQL", "Snapshots", "How a transaction sees a fixed view.")

    assert "PostgreSQL" in query
    assert "Snapshots" in query
    assert "How a transaction sees a fixed view." in query


def test_an_empty_context_says_which_kind_of_empty_it_is() -> None:
    """CLAUDE.md: a failed outcome and a rejected one are never the same number. A
    thin corpus and an unset environment variable both produce ungrounded cards and
    are not the same fact."""

    assert GroundingContext.empty(GroundingOutcome.NO_MATCH).outcome is GroundingOutcome.NO_MATCH
    unavailable = GroundingContext.empty(GroundingOutcome.UNAVAILABLE)
    assert unavailable.outcome is GroundingOutcome.UNAVAILABLE
    assert unavailable.block == ""
    assert unavailable.chunk_ids == ()


# -- retrieval, against the corpus schema ---------------------------------------


class _CountingEmbedder(Embedder):
    """`HashEmbedder` at the corpus's dimension, counting query embeddings.

    Semantically meaningless, and nothing here draws a conclusion from a similarity —
    what these tests assert is how OFTEN the corpus is asked, and which documents are
    eligible to be returned.
    """

    def __init__(self) -> None:
        self._inner = HashEmbedder(EMBEDDING_DIM)
        self.queries = 0

    def embed_passage(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_passage(texts)

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        self.queries += 1
        return self._inner.embed_query(texts)


def _document(path: str, *, kind: DocumentKind, ingested_at: datetime) -> Document:
    return Document(
        title=f"Document {path}",
        source=f"https://example.invalid/{path}",
        source_path=path,
        kind=kind,
        category=None if kind is DocumentKind.SPOIN_CANON else "computer science",
        sub_category=None,
        scope=None if kind is DocumentKind.SPOIN_CANON else DocumentScope.TOPIC,
        content_hash=path,
        ingested_at=ingested_at,
    )


async def _seed(session: AsyncSession, embedder: Embedder) -> None:
    """One `topic_source` document and one `spoin_canon` document, one chunk each."""

    now = datetime.now(UTC)
    documents = [
        _document("cs/pg/mvcc.md", kind=DocumentKind.TOPIC_SOURCE, ingested_at=now),
        _document("spoin/canon/ascii.md", kind=DocumentKind.SPOIN_CANON, ingested_at=now),
    ]
    session.add_all(documents)
    await session.flush()
    bodies = [
        "MVCC — Snapshot isolation\n\nEach transaction sees a snapshot.",
        "Spoin canon — ASCII\n\nArt fits in 40 columns.",
    ]
    session.add_all(
        Chunk(
            document_id=document.id,
            ordinal=0,
            text=body,
            embedding=embedder.embed_one_passage(body),
            topic_tags=["postgresql"],
        )
        for document, body in zip(documents, bodies, strict=True)
    )
    await session.commit()


@pytest.fixture
def bound_universe(universe_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """Point `grounding`'s session scope at the test corpus.

    Patched at the module rather than reconfigured through `Settings`, because
    `get_universe_engine` is `lru_cache`d — a settings override would leak an engine on
    the test database into every later test in the process.
    """

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        yield universe_session

    monkeypatch.setattr(grounding_module, "universe_session_scope", scope)
    return universe_session


async def test_grounding_retrieves_topic_material_and_reports_what_grounded_the_card(
    bound_universe: AsyncSession,
) -> None:
    embedder = _CountingEmbedder()
    await _seed(bound_universe, embedder)

    context = await Grounding(embedder, token_budget=6000, max_chunks=8).for_subtopic(
        subtopic_group_id=uuid.uuid4(),
        topic_name="PostgreSQL",
        subtopic_title="MVCC",
        subtopic_description="How a transaction sees a fixed view of the database.",
    )

    assert context.outcome is GroundingOutcome.GROUNDED
    assert len(context.chunk_ids) == 1
    #: ADR-0089 stores these on the card, so they have to be the chunks that are
    #: actually in the block — not the wider candidate set retrieval returned.
    assert context.estimated_tokens == estimate_tokens(context.block)
    assert "Each transaction sees a snapshot." in context.block


async def test_canon_is_not_retrieved_it_is_pinned(bound_universe: AsyncSession) -> None:
    """rag-design-space §3.9, amending ADR-0088. `prompts/canon.py` pins canon into
    every system prompt, so letting it compete for retrieval slots here would spend the
    budget twice on the same material — and displace the subject matter the call
    needed."""

    embedder = _CountingEmbedder()
    await _seed(bound_universe, embedder)

    context = await Grounding(embedder, token_budget=6000, max_chunks=8).for_subtopic(
        subtopic_group_id=uuid.uuid4(),
        topic_name="Spoin",
        subtopic_title="ASCII art",
        subtopic_description="Art fits in 40 columns.",
    )

    assert "Spoin canon" not in context.block


async def test_an_empty_corpus_is_no_match_not_unavailable(
    bound_universe: AsyncSession,
) -> None:
    """The corpus was reachable and had nothing. Reporting that as `UNAVAILABLE` would
    send someone to debug an environment variable that is fine."""

    context = await Grounding(_CountingEmbedder(), token_budget=6000, max_chunks=8).for_subtopic(
        subtopic_group_id=uuid.uuid4(),
        topic_name="PostgreSQL",
        subtopic_title="MVCC",
        subtopic_description="Nothing in this corpus covers it.",
    )

    assert context.outcome is GroundingOutcome.NO_MATCH
    assert context.block == ""


async def test_a_subtopic_group_is_retrieved_once_and_reused(
    bound_universe: AsyncSession,
) -> None:
    """The point of §3.7. The drafter, the redraft after a rejection and the verifier
    all want the same passages, and a different tier of the same group is still the
    same query — difficulty is how the card is written, not what it is written from."""

    embedder = _CountingEmbedder()
    await _seed(bound_universe, embedder)
    grounding = Grounding(embedder, token_budget=6000, max_chunks=8)
    group = uuid.uuid4()

    async def ask() -> GroundingContext:
        return await grounding.for_subtopic(
            subtopic_group_id=group,
            topic_name="PostgreSQL",
            subtopic_title="MVCC",
            subtopic_description="How a transaction sees a fixed view.",
        )

    first = await ask()
    embedded_after_first = embedder.queries

    assert (await ask()).chunk_ids == first.chunk_ids
    assert embedder.queries == embedded_after_first == 1


async def test_a_different_subtopic_group_is_retrieved_again(
    bound_universe: AsyncSession,
) -> None:
    embedder = _CountingEmbedder()
    await _seed(bound_universe, embedder)
    grounding = Grounding(embedder, token_budget=6000, max_chunks=8)

    for _ in range(2):
        await grounding.for_subtopic(
            subtopic_group_id=uuid.uuid4(),
            topic_name="PostgreSQL",
            subtopic_title="MVCC",
            subtopic_description="How a transaction sees a fixed view.",
        )

    assert embedder.queries == 2


async def test_a_re_ingestion_invalidates_the_cache(bound_universe: AsyncSession) -> None:
    """The worker is long-lived and the owner re-ingests the corpus on the same machine
    while it runs (ADR-0094), so "the process started before the corpus changed" is a
    real state. Without the corpus version in the key, a run would keep grounding cards
    in a passage that has since been revised — or retracted."""

    embedder = _CountingEmbedder()
    await _seed(bound_universe, embedder)
    grounding = Grounding(embedder, token_budget=6000, max_chunks=8)
    group = uuid.uuid4()

    async def ask() -> GroundingContext:
        return await grounding.for_subtopic(
            subtopic_group_id=group,
            topic_name="PostgreSQL",
            subtopic_title="MVCC",
            subtopic_description="How a transaction sees a fixed view.",
        )

    await ask()
    await ask()
    assert embedder.queries == 1

    document = _document(
        "cs/dist/consensus.md",
        kind=DocumentKind.TOPIC_SOURCE,
        ingested_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    bound_universe.add(document)
    await bound_universe.commit()

    await ask()
    assert embedder.queries == 2


async def test_an_unreachable_corpus_degrades_to_ungrounded_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ungrounded generation is the pre-ADR-0089 behaviour and it produces cards.
    Aborting a run because a corpus connection failed would trade every card in it for
    a missing environment variable — but the run has to be visibly ungrounded, which is
    what the outcome is for."""

    @asynccontextmanager
    async def unconfigured() -> AsyncIterator[AsyncSession]:
        raise UniverseNotConfiguredError("SPOIN_UNIVERSE_DATABASE_URL is not set")
        yield  # pragma: no cover - unreachable, present to make this a generator

    monkeypatch.setattr(grounding_module, "universe_session_scope", unconfigured)

    context = await Grounding(_CountingEmbedder(), token_budget=6000, max_chunks=8).for_subtopic(
        subtopic_group_id=uuid.uuid4(),
        topic_name="PostgreSQL",
        subtopic_title="MVCC",
        subtopic_description="How a transaction sees a fixed view.",
    )

    assert context.outcome is GroundingOutcome.UNAVAILABLE
    assert context.block == ""


def test_the_engine_refuses_to_be_built_without_a_corpus_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its own exception type rather than a fallback to `database_url`: that fallback
    would point retrieval at `spoin_db_2`, which has no `document` table, and the
    failure would arrive as a confusing SQL error instead of a missing setting."""

    get_universe_engine.cache_clear()
    monkeypatch.setenv("SPOIN_UNIVERSE_DATABASE_URL", "")
    with pytest.raises(UniverseNotConfiguredError):
        get_universe_engine()
    get_universe_engine.cache_clear()


async def test_the_corpus_engine_is_read_only(universe_session: AsyncSession) -> None:
    """CLAUDE.md's standing prohibition, enforced by Postgres rather than by review.
    `the_spoin_universe` shares `db-data` with production and this process has no
    legitimate reason to write it, so the engine's transactions are READ ONLY and a
    stray write raises instead of depending on nobody calling `commit()`.
    """

    engine = create_async_engine(
        UNIVERSE_TEST_DATABASE_URL, execution_options={"postgresql_readonly": True}
    )
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text("DELETE FROM document"))
    finally:
        await engine.dispose()
