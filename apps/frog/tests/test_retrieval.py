"""What `frog.retrieval` promises, asserted against a real database.

The load-bearing test here is `test_search_embeds_the_query_with_the_query_side`.
ADR-0092 made `Embedder` asymmetric, and calling the passage side for a query is a
**silent** recall loss: nothing raises, no row is wrong, the ranking is just quietly
worse than it should be. That failure cannot be caught by eyeballing output, so it is
caught here — and it is asserted twice, once on which method was called and once on the
ranking that a wrong call would reorder.

The filters get a real Postgres rather than a mock because what is under test is the
database's own behaviour: `topic_tags`'s array overlap, the enum comparison, and
`ORDER BY` on pgvector's cosine operator. Skipped when
`SPOIN_UNIVERSE_TEST_DATABASE_URL` is unset; see conftest.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from frog.embeddings import Embedder
from frog.retrieval import Hit, search, search_many
from frog.universe.models import (
    EMBEDDING_DIM,
    Chunk,
    Document,
    DocumentKind,
    DocumentScope,
)

#: Two orthogonal basis directions spanning the plane every fixture vector lives in.
#: Every chunk sits at a known angle from `_E0`, so a query embedded as `_E0` produces
#: scores this file can predict exactly rather than merely rank.
_E0 = 0
_E1 = 1


def _at_angle(radians: float) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[_E0] = math.cos(radians)
    vector[_E1] = math.sin(radians)
    return vector


#: Chosen so cos() is strictly decreasing down the list: chunk 0 is the best hit for a
#: query on the `_E0` axis, chunk 3 the worst, with no ties for `ORDER BY` to break
#: arbitrarily.
_ANGLES = [0.0, 0.3, 0.6, 0.9]


class _AsymmetricEmbedder(Embedder):
    """Stands in for Qwen3's query/passage asymmetry, exaggerated until it is visible.

    The query side answers on the `_E0` axis and the passage side on `_E1`, which are
    orthogonal — so the two sides do not merely score differently, they rank the corpus
    in **opposite** order. That is deliberate: it turns ADR-0092's silent failure into a
    ranking assertion, which is a thing a test can see.
    """

    def __init__(self) -> None:
        self.query_calls: list[list[str]] = []
        self.passage_calls: list[list[str]] = []

    @property
    def model_name(self) -> str:
        return "asymmetric-stub"

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        self.query_calls.append(list(texts))
        return [_at_angle(0.0) for _ in texts]

    def embed_passage(self, texts: list[str]) -> list[list[float]]:
        self.passage_calls.append(list(texts))
        return [_at_angle(math.pi / 2) for _ in texts]


#: `(source_path, kind, category, sub_category, scope, topic_tags)`, one row per axis of
#: a filter under test. The canon document carries no category or scope, which is not
#: laziness in the fixture: `ck_document_topic_source_has_category_and_scope` exempts
#: canon precisely because it is about Spoin rather than about a field.
_DOCUMENTS = [
    (
        "cs/pg/mvcc.md",
        DocumentKind.TOPIC_SOURCE,
        "computer science",
        "databases",
        DocumentScope.TOPIC,
        ["postgresql"],
    ),
    ("spoin/canon/ascii.md", DocumentKind.SPOIN_CANON, None, None, None, ["ascii art"]),
    (
        "cs/dist/consensus.md",
        DocumentKind.TOPIC_SOURCE,
        "computer science",
        None,
        DocumentScope.SURVEY,
        ["distributed systems"],
    ),
]

#: Which document each of the four chunks belongs to. The third document gets two, so
#: `exclude_document_ids` has something to remove that `exclude_chunk_ids` would not.
_CHUNK_OWNERS = [0, 1, 2, 2]


async def _corpus(session: AsyncSession) -> tuple[list[Document], list[Chunk]]:
    documents = [
        Document(
            title=f"Document {ordinal}",
            source=f"https://example.invalid/{ordinal}",
            source_path=path,
            kind=kind,
            category=category,
            sub_category=sub_category,
            scope=scope,
            content_hash=f"{ordinal:064d}",
            ingested_at=datetime.now(UTC),
        )
        for ordinal, (path, kind, category, sub_category, scope, _) in enumerate(_DOCUMENTS)
    ]
    session.add_all(documents)
    await session.flush()

    chunks = [
        Chunk(
            document_id=documents[owner].id,
            ordinal=index,
            text=f"Document {owner} — section {index}\n\nBody {index}.",
            embedding=_at_angle(angle),
            #: These vectors come from `_at_angle`, not from any model, so the
            #: stamp says so rather than naming one that never ran.
            embedding_model="fixture-at-angle",
            topic_tags=list(_DOCUMENTS[owner][5]),
        )
        for index, (owner, angle) in enumerate(zip(_CHUNK_OWNERS, _ANGLES, strict=True))
    ]
    session.add_all(chunks)
    await session.commit()
    return documents, chunks


async def test_search_returns_similarity_not_distance_most_similar_first(
    session: AsyncSession,
) -> None:
    """`Hit.score` reads as "how close", so a `min_score` floor means what it says.

    pgvector returns a distance, and a caller comparing it the intuitive way would
    silently keep the *worst* matches. The conversion is the module's job, so this
    asserts the actual numbers rather than only their order.
    """

    _, chunks = await _corpus(session)

    hits = await search(session, _AsymmetricEmbedder(), "anything")

    assert [hit.chunk_id for hit in hits] == [chunk.id for chunk in chunks]
    assert [round(hit.score, 4) for hit in hits] == [round(math.cos(a), 4) for a in _ANGLES]


async def test_search_embeds_the_query_with_the_query_side(session: AsyncSession) -> None:
    """ADR-0092's silent failure, caught two ways.

    The call assertion says which method ran; the ranking assertion says it mattered.
    Either alone would pass against a mistake the other catches — a future refactor
    that embeds correctly but ranks on the wrong vector, or one that ranks correctly
    today because both sides happen to agree, as `HashEmbedder`'s do.
    """

    _, chunks = await _corpus(session)
    embedder = _AsymmetricEmbedder()

    hits = await search(session, embedder, "how does MVCC work")

    assert embedder.query_calls == [["how does MVCC work"]]
    assert embedder.passage_calls == []
    #: The passage side ranks this corpus in exactly the opposite order, so a
    #: best-hit-first assertion is a direct statement about which side was used.
    assert hits[0].chunk_id == chunks[0].id


async def test_a_hit_carries_its_documents_provenance(session: AsyncSession) -> None:
    """ADR-0089 cites chunks on cards and a human audits them by source path, so both
    have to come back from the search itself — the alternative is a second query per
    hit."""

    documents, chunks = await _corpus(session)

    hit = (await search(session, _AsymmetricEmbedder(), "q", k=1))[0]

    assert hit.chunk_id == chunks[0].id
    assert hit.document_id == documents[0].id
    assert hit.document_title == documents[0].title
    assert hit.source_path == "cs/pg/mvcc.md"
    assert hit.kind is DocumentKind.TOPIC_SOURCE
    assert hit.category == "computer science"
    assert hit.sub_category == "databases"
    assert hit.ordinal == 0
    assert hit.topic_tags == ["postgresql"]
    #: The contextual header is what was embedded (task 0038 Phase 2). A consumer that
    #: never sees it cannot tell two identically-worded sections apart.
    assert hit.text.startswith("Document 0 — section 0")


async def test_k_limits_the_candidates(session: AsyncSession) -> None:
    await _corpus(session)

    assert len(await search(session, _AsymmetricEmbedder(), "q", k=2)) == 2


async def test_min_score_shortens_the_result_rather_than_widening_the_search(
    session: AsyncSession,
) -> None:
    """A floor is a quality bar on what came back, not a request for more candidates.

    Asserted as the pair, because the tempting implementation — over-fetch until `k`
    survive the floor — would pass a "nothing below the floor" test on its own while
    quietly turning every `k=1` lookup into a scan for the best passable hit.
    """

    await _corpus(session)
    embedder = _AsymmetricEmbedder()

    floor = math.cos(0.45)
    assert len(await search(session, embedder, "q", min_score=floor)) == 2
    assert len(await search(session, embedder, "q", k=3, min_score=floor)) == 2
    #: Task 0040's shape: top-1 above a floor, and an empty list when nothing clears it.
    assert await search(session, embedder, "q", k=1, min_score=1.5) == []


async def test_retrieval_is_cross_topic_until_a_caller_narrows_it(
    session: AsyncSession,
) -> None:
    """ADR-0088's default, asserted because it is a default rather than a parameter and
    so has nothing else stating it: a PostgreSQL card may legitimately ground itself in
    distributed-systems material."""

    await _corpus(session)
    embedder = _AsymmetricEmbedder()

    unfiltered = await search(session, embedder, "q")
    assert {hit.kind for hit in unfiltered} == {
        DocumentKind.SPOIN_CANON,
        DocumentKind.TOPIC_SOURCE,
    }
    assert len({hit.document_id for hit in unfiltered}) == 3

    canon_only = await search(session, embedder, "q", kinds=[DocumentKind.SPOIN_CANON])
    assert [hit.source_path for hit in canon_only] == ["spoin/canon/ascii.md"]


async def test_topic_tags_matches_a_chunk_that_carries_any_of_them(
    session: AsyncSession,
) -> None:
    """Overlap, not containment — a chunk tagged only `postgresql` must match a query
    filtered to `{postgresql, distributed systems}`."""

    await _corpus(session)

    hits = await search(
        session, _AsymmetricEmbedder(), "q", topic_tags=["postgresql", "distributed systems"]
    )

    assert [hit.source_path for hit in hits] == [
        "cs/pg/mvcc.md",
        "cs/dist/consensus.md",
        "cs/dist/consensus.md",
    ]


async def test_exclusions_drop_a_whole_document_or_a_single_chunk(
    session: AsyncSession,
) -> None:
    """The two exclusions are not interchangeable, which is why both exist: task 0040
    excludes documents a topic has already drawn from, while packing excludes the
    individual chunks already in the prompt."""

    documents, chunks = await _corpus(session)
    embedder = _AsymmetricEmbedder()

    by_document = await search(session, embedder, "q", exclude_document_ids=[documents[2].id])
    assert [hit.chunk_id for hit in by_document] == [chunks[0].id, chunks[1].id]

    by_chunk = await search(session, embedder, "q", exclude_chunk_ids=[chunks[2].id])
    assert [hit.chunk_id for hit in by_chunk] == [chunks[0].id, chunks[1].id, chunks[3].id]


async def test_an_exclusion_of_something_absent_changes_nothing(
    session: AsyncSession,
) -> None:
    """A caller passes whatever a topic has used so far, which on the first card is
    nothing and later is mostly IDs from other corpora. Neither may narrow the search."""

    await _corpus(session)
    embedder = _AsymmetricEmbedder()

    def ids(hits: list[Hit]) -> list[uuid.UUID]:
        return [hit.chunk_id for hit in hits]

    baseline = ids(await search(session, embedder, "q"))

    assert ids(await search(session, embedder, "q", exclude_document_ids=[])) == baseline
    assert ids(await search(session, embedder, "q", exclude_chunk_ids=[])) == baseline
    assert ids(await search(session, embedder, "q", exclude_chunk_ids=[uuid.uuid4()])) == baseline


async def test_search_many_embeds_once_and_answers_in_query_order(
    session: AsyncSession,
) -> None:
    """One `encode` over N strings is one GPU round trip instead of N, and the eval
    harness runs dozens at once. Order is what lets a caller zip results back to the
    subtopics that asked for them."""

    await _corpus(session)
    embedder = _AsymmetricEmbedder()
    queries = ["first", "second", "third"]

    results = await search_many(session, embedder, queries, k=1)

    assert embedder.query_calls == [queries]
    assert len(results) == len(queries)
    assert all(len(hits) == 1 for hits in results)


async def test_search_many_of_nothing_does_not_call_the_model(
    session: AsyncSession,
) -> None:
    """An empty batch is reachable — a subtopic group where every query was already
    cached — and embedding zero strings is a wasted round trip at best and a crash in
    an implementation that assumes a non-empty tensor."""

    embedder = _AsymmetricEmbedder()

    assert await search_many(session, embedder, []) == []
    assert embedder.query_calls == []
