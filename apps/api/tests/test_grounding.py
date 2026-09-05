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
from typing import Any

import pytest
from frog.embeddings import Embedder, HashEmbedder
from frog.retrieval import Hit
from frog.universe.models import EMBEDDING_DIM, Chunk, Document, DocumentKind, DocumentScope
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from conftest import UNIVERSE_TEST_DATABASE_URL
from spoin.core.config import Settings
from spoin.core.db import UniverseNotConfiguredError, get_universe_engine
from spoin.domain.models import Card
from spoin.generation import grounding as grounding_module
from spoin.generation.fake import FakeContentGenerator
from spoin.generation.grounding import (
    Grounding,
    GroundingContext,
    GroundingOutcome,
    build_query,
    render_block,
)
from spoin.generation.load_balancer import estimate_tokens
from spoin.generation.pipeline import TopicRequest, match_and_create_topics, run_generation_pipeline


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

    @property
    def model_name(self) -> str:
        return self._inner.model_name

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
def bound_universe(
    universe_sessions: async_sessionmaker[AsyncSession],
    universe_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncSession:
    """Point `grounding`'s session scope at the test corpus.

    Patched at the module rather than reconfigured through `Settings`, because
    `get_universe_engine` is `lru_cache`d — a settings override would leak an engine on
    the test database into every later test in the process.

    A fresh session per scope, as production's pool gives. The returned session is the
    test's own, for seeding; retrieval never borrows it, so a pipeline retrieving from
    concurrent subtopic branches does not trip over `AsyncSession`'s concurrency rule.
    """

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        async with universe_sessions() as session:
            yield session

    monkeypatch.setattr(grounding_module, "universe_session_scope", scope)
    return universe_session


async def test_grounding_retrieves_topic_material_and_reports_what_grounded_the_card(
    bound_universe: AsyncSession,
) -> None:
    embedder = _CountingEmbedder()
    await _seed(bound_universe, embedder)

    context = await Grounding(embedder, chunks=8).for_subtopic(
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

    context = await Grounding(embedder, chunks=8).for_subtopic(
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

    context = await Grounding(_CountingEmbedder(), chunks=8).for_subtopic(
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
    grounding = Grounding(embedder, chunks=8)
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
    grounding = Grounding(embedder, chunks=8)

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
    grounding = Grounding(embedder, chunks=8)
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

    context = await Grounding(_CountingEmbedder(), chunks=8).for_subtopic(
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


# -- the wiring: one set of passages, shared by every call about a subtopic ------


class _RecordingGenerator(FakeContentGenerator):
    """Records the `grounding` block each generation call was handed.

    Subclassing the fake rather than mocking the pipeline: what is under test is
    which calls the pipeline threads the block into, and that is only visible from
    where the calls land.
    """

    def __init__(self) -> None:
        super().__init__()
        self.seen: dict[str, list[str]] = {}

    def _note(self, call: str, grounding: str) -> None:
        self.seen.setdefault(call, []).append(grounding)

    async def plan_cards(self, **kwargs: Any) -> Any:
        self._note("plan_cards", kwargs.get("grounding", ""))
        return await super().plan_cards(**kwargs)

    async def generate_cards(self, **kwargs: Any) -> Any:
        self._note("generate_cards", kwargs.get("grounding", ""))
        return await super().generate_cards(**kwargs)

    async def correct_cards(self, queries: Any, **kwargs: Any) -> Any:
        self._note("correct_cards", kwargs.get("grounding", ""))
        return await super().correct_cards(queries, **kwargs)

    async def verify_cards(self, queries: Any, **kwargs: Any) -> Any:
        self._note("verify_cards", kwargs.get("grounding", ""))
        return await super().verify_cards(queries, **kwargs)

    async def generate_questions(self, cards: Any, difficulty: Any, **kwargs: Any) -> Any:
        self._note("generate_questions", kwargs.get("grounding", ""))
        return await super().generate_questions(cards, difficulty, **kwargs)


async def test_every_content_call_in_a_run_sees_the_same_passages(
    session: AsyncSession,
    settings: Settings,
    bound_universe: AsyncSession,
) -> None:
    """ADR-0089's actual claim, end to end.

    The drafter writing from one set of sources while the verifier judges against
    another is the coin-flip this design exists to remove, so the assertion is not
    "everything got grounding" but "everything got the SAME grounding". It holds
    because `Grounding` caches on the subtopic group and every node asks it rather
    than retrieving for itself.
    """

    #: Seeded with what `get_embedder()` returns under the test settings, which is
    #: the constraint this test also documents: a query embedded by a different model
    #: than the chunks is not a worse result, it is a dimension error. ADR-0097 made
    #: that structural by deleting the second factory -- there is one model and one
    #: 1024-dim space now, so the pipeline's embedder and the corpus's are the same
    #: object.
    await _seed(bound_universe, HashEmbedder(EMBEDDING_DIM))
    generator = _RecordingGenerator()
    embedder = HashEmbedder(EMBEDDING_DIM)

    outcomes = await match_and_create_topics(
        session,
        generator,
        embedder,
        settings,
        topic_requests=[TopicRequest(name="PostgreSQL internals", description="")],
    )
    topic_ids = [uuid.UUID(outcome["topic_id"]) for outcome in outcomes]
    await run_generation_pipeline(session, generator, embedder, settings, topic_ids=topic_ids)

    #: Every content call, drafters and thinkers alike (ADR-0089 is explicit that
    #: the gate grounding in the same corpus is the point, not a nicety).
    assert set(generator.seen) == {
        "plan_cards",
        "generate_cards",
        "correct_cards",
        "verify_cards",
        "generate_questions",
    }
    blocks = {block for blocks in generator.seen.values() for block in blocks}
    assert len(blocks) == 1
    assert "Each transaction sees a snapshot." in blocks.pop()

    #: ADR-0089's third commitment: the card records what grounded it, and it
    #: records the chunks that were actually IN the prompt rather than what a later
    #: re-query would return.
    #: The corpus's one `topic_source` chunk -- the canon document's is never
    #: retrieved, which is the pinned-not-retrieved rule the sibling test asserts.
    chunk_id = (
        (
            await bound_universe.execute(
                select(Chunk.id)
                .join(Document, Document.id == Chunk.document_id)
                .where(Document.kind == DocumentKind.TOPIC_SOURCE)
            )
        )
        .scalars()
        .one()
    )
    grounded = (await session.execute(select(Card.grounded_chunk_ids))).scalars().all()
    assert grounded
    assert all(ids == [chunk_id] for ids in grounded)


async def test_only_the_shipped_count_of_passages_reaches_the_prompt(
    bound_universe: AsyncSession,
    settings: Settings,
) -> None:
    """`grounding_chunks` is the `k` handed to the search, not a trim applied after.

    Asserted against the SHIPPED setting and a corpus holding more matches than it
    allows, because the failure is invisible: every passage in the corpus reaching
    every prompt still produces cards, just larger and slower ones.

    Its predecessor guarded a token budget against a chunk count. Both are gone --
    a budget could not bind once the count is 2, and a limit that cannot bind is the
    dead setting `8a8e64c` removed. Two passages are bounded at roughly 1200 prompt
    tokens by the ingestion contract's `MAX_SECTION_CHARS`, not by anything here.
    """

    embedder = HashEmbedder(EMBEDDING_DIM)
    now = datetime.now(UTC)
    document = _document("cs/pg/mvcc.md", kind=DocumentKind.TOPIC_SOURCE, ingested_at=now)
    bound_universe.add(document)
    await bound_universe.flush()
    bodies = [
        f"MVCC — Snapshot isolation {n}\n\nEach transaction sees a snapshot." for n in range(4)
    ]
    bound_universe.add_all(
        Chunk(
            document_id=document.id,
            ordinal=ordinal,
            text=body,
            embedding=embedder.embed_one_passage(body),
            topic_tags=["postgresql"],
        )
        for ordinal, body in enumerate(bodies)
    )
    await bound_universe.commit()

    context = await Grounding(embedder, chunks=settings.grounding_chunks).for_subtopic(
        subtopic_group_id=uuid.uuid4(),
        topic_name="PostgreSQL",
        subtopic_title="MVCC",
        subtopic_description="How a transaction sees a fixed view of the database.",
    )

    assert settings.grounding_chunks == 2
    assert len(context.chunk_ids) == settings.grounding_chunks
    #: `retrieved` is what the search returned, and the search was asked for exactly
    #: this many -- nothing is fetched to be discarded.
    assert context.retrieved == settings.grounding_chunks
