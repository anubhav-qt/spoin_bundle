"""Search over `the_spoin_universe`.

Shape and reasoning: docs/adr/0089-retrieval-grounded-generation.md, and
docs/adr/0088-the-spoin-universe.md for why the filters exist but are off by default.

**This module is search and nothing else.** Context assembly — packing hits into a
prompt against a token budget — deliberately lives in `spoin.generation.grounding`
rather than here, for two reasons. Packing is prompt-shaped work, and the budgeting
posture it must reuse (`pack_by_tokens`, ADR-0085) lives in `spoin`, which frog cannot
import (ADR-0087). Reusing the real function beats reimplementing its posture on this
side of the boundary and letting the two drift.

The split is also what task 0040 needs. Assigning a photograph to a card is a retrieval
query that is not prompt assembly at all — top-1 above a similarity floor, filtered by
what a topic has already used, returning a row rather than prose. A `search` that only
existed inside a `build_prompt_context()` would force that consumer to reimplement it.

⚠️ **Queries embed with `embed_query`; ingestion embedded with `embed_passage`.**
ADR-0092 made `Embedder` asymmetric precisely because getting this backwards is a
silent recall loss rather than an error — nothing raises, the numbers just quietly get
worse. `test_retrieval.py` asserts which side this module calls.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from frog.embeddings import Embedder
from frog.universe.models import Chunk, Document, DocumentKind

#: Candidates per query when the caller does not say. Deliberately larger than what a
#: prompt will actually carry: packing downstream cuts to a token budget, and a reranker
#: (rag-design-space §3.4) would want a wide candidate set to rerank. Retrieval being
#: exact rather than approximate (see `search`'s note on the missing ANN index) means a
#: generous k costs a slightly longer sequential scan, not recall risk.
DEFAULT_K = 20


@dataclass(frozen=True)
class Hit:
    """One retrieved chunk, with everything needed to cite it or to pack it.

    Carries the document's provenance alongside the chunk because every consumer needs
    it and the alternative is a second query per hit: ADR-0089 records `chunk_id` on the
    card, task 0040 filters on `document_id`, and a human auditing a card wants
    `source_path`.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID

    #: Cosine similarity in [-1, 1], NOT the distance pgvector returns. Higher is
    #: closer. Converted here so no caller has to remember which direction the
    #: operator points — a `min_score` filter reading as "at least this similar" is
    #: the whole reason.
    score: float

    #: The stored chunk text, contextual header included. ⚠️ Do not strip the
    #: `<document title> — <section heading>` first line and do not add a second one:
    #: it is what was embedded (task 0038 Phase 2), and the model reading a retrieved
    #: chunk is meant to see it.
    text: str

    ordinal: int
    topic_tags: list[str]

    document_title: str
    source: str
    source_path: str
    kind: DocumentKind
    category: str | None
    sub_category: str | None


def _select_hits(
    embedding: Sequence[float],
    *,
    k: int,
    kinds: Collection[DocumentKind] | None,
    topic_tags: Collection[str] | None,
    exclude_document_ids: Collection[uuid.UUID] | None,
    exclude_chunk_ids: Collection[uuid.UUID] | None,
    include_chunk_ids: Collection[uuid.UUID] | None,
) -> Select[tuple[Chunk, Document, float]]:
    """The query, built once and shared by the single and batch entrypoints.

    **There is no ANN index on `chunk.embedding`, deliberately** — only `pk_chunk`, the
    ordinal index and a GIN on `topic_tags`. At this corpus size a sequential scan is
    both fast and *exact*, and pgvector's HNSW is approximate: adding one before the
    eval harness has run would make retrieval numbers reflect index recall rather than
    embedding quality, and a bad number would be unattributable. Measure first, index
    second, and re-run the eval to price the index when one is added
    (rag-design-space §3.6, and task 0038 Phase 3).
    """

    distance = Chunk.embedding.cosine_distance(embedding)
    statement = (
        select(Chunk, Document, (1.0 - distance).label("score"))
        .join(Document, Document.id == Chunk.document_id)
        .order_by(distance)
        .limit(k)
    )

    #: Every filter below is available and NONE is applied by default (ADR-0088):
    #: retrieval is cross-topic, because a PostgreSQL card may legitimately ground
    #: itself in distributed-systems material.
    if kinds is not None:
        statement = statement.where(Document.kind.in_(list(kinds)))
    if topic_tags is not None:
        statement = statement.where(Chunk.topic_tags.overlap(list(topic_tags)))
    if include_chunk_ids is not None:
        #: The mirror of `exclude_chunk_ids`, and the mechanism behind an authored
        #: curriculum's declared scope (authored-curriculum.md §10): rank WITHIN the
        #: sections the author said teach this tier, instead of guessing corpus-wide.
        #:
        #: An EMPTY collection means an empty scope and returns nothing -- distinct
        #: from `None`, which means unscoped. Collapsing the two would turn a
        #: curriculum whose refs all failed to resolve into a silent open query,
        #: which is the one outcome the caller most needs to be able to see.
        statement = statement.where(Chunk.id.in_(list(include_chunk_ids)))
    if exclude_document_ids:
        statement = statement.where(Document.id.not_in(list(exclude_document_ids)))
    if exclude_chunk_ids:
        statement = statement.where(Chunk.id.not_in(list(exclude_chunk_ids)))
    return statement


def _hit(chunk: Chunk, document: Document, score: float) -> Hit:
    return Hit(
        chunk_id=chunk.id,
        document_id=document.id,
        score=float(score),
        text=chunk.text,
        ordinal=chunk.ordinal,
        topic_tags=list(chunk.topic_tags),
        document_title=document.title,
        source=document.source,
        source_path=document.source_path,
        kind=document.kind,
        category=document.category,
        sub_category=document.sub_category,
    )


async def search(
    session: AsyncSession,
    embedder: Embedder,
    query: str,
    *,
    k: int = DEFAULT_K,
    kinds: Collection[DocumentKind] | None = None,
    topic_tags: Collection[str] | None = None,
    min_score: float | None = None,
    exclude_document_ids: Collection[uuid.UUID] | None = None,
    exclude_chunk_ids: Collection[uuid.UUID] | None = None,
    include_chunk_ids: Collection[uuid.UUID] | None = None,
) -> list[Hit]:
    """Top-`k` chunks for one query string, most similar first.

    `min_score` is applied after the database returns its `k`, so it shortens the
    result rather than widening the search — a floor is a quality bar on what came
    back, not a request for more candidates. Task 0040's "top-1 above a floor" is
    `k=1` with a `min_score`, and an empty list is the honest answer when nothing
    clears it.
    """

    hits = await search_many(
        session,
        embedder,
        [query],
        k=k,
        kinds=kinds,
        topic_tags=topic_tags,
        min_score=min_score,
        exclude_document_ids=exclude_document_ids,
        exclude_chunk_ids=exclude_chunk_ids,
        include_chunk_ids=include_chunk_ids,
    )
    return hits[0]


async def search_many(
    session: AsyncSession,
    embedder: Embedder,
    queries: Sequence[str],
    *,
    k: int = DEFAULT_K,
    kinds: Collection[DocumentKind] | None = None,
    topic_tags: Collection[str] | None = None,
    min_score: float | None = None,
    exclude_document_ids: Collection[uuid.UUID] | None = None,
    exclude_chunk_ids: Collection[uuid.UUID] | None = None,
    include_chunk_ids: Collection[uuid.UUID] | None = None,
) -> list[list[Hit]]:
    """`search` for several queries, one embedding call for all of them.

    Returned in the order the queries were given, so a caller can zip them back.
    The batching is about the model, not about a quota — the embedder is local and
    never metered (hard rule 5) — but a single `encode` over N strings is one GPU
    round trip instead of N, and the eval harness runs dozens of queries at once.

    The database is still queried once per query: a top-k per vector is not one
    statement, and at this corpus size the scan is cheap enough that batching it
    would be machinery bought for nothing.
    """

    if not queries:
        return []

    #: `aembed_query`, not `aembed_passage`. See the module docstring — this is the
    #: silent-failure side of ADR-0092, and it is the reason the interface has two
    #: methods rather than one.
    embeddings = await embedder.aembed_query(list(queries))

    results: list[list[Hit]] = []
    for embedding in embeddings:
        rows = await session.execute(
            _select_hits(
                embedding,
                k=k,
                kinds=kinds,
                topic_tags=topic_tags,
                exclude_document_ids=exclude_document_ids,
                exclude_chunk_ids=exclude_chunk_ids,
                include_chunk_ids=include_chunk_ids,
            )
        )
        hits = [_hit(chunk, document, score) for chunk, document, score in rows.all()]
        if min_score is not None:
            hits = [hit for hit in hits if hit.score >= min_score]
        results.append(hits)
    return results


async def corpus_version(session: AsyncSession) -> str:
    """A token that changes whenever the corpus does, for a caller's cache key.

    The consumer is `spoin.generation.grounding`, which retrieves once per subtopic
    group and reuses the result across every card draft in it (rag-design-space §3.7).
    That cache lives in a **long-running worker**, and the owner re-ingests the corpus
    on the same machine while it runs — so "the process started before the corpus
    changed" is a real state, and a cache keyed on the subtopic alone would serve
    context from a document that has since been revised or retracted.

    Cheap deliberately: a count and a max over a table of hundreds of rows, read once
    per subtopic rather than per call. `ingested_at` moves whenever a document's
    content hash changed (task 0038 Phase 2), and the count moves when one is added or
    deleted — between them, every edit the ingester can make is visible. It is NOT a
    content hash of the corpus: a revision that somehow left both unchanged would be
    missed, and that is an accepted trade for not hashing the corpus on every subtopic.
    """

    documents, ingested = (
        await session.execute(select(func.count(Document.id), func.max(Document.ingested_at)))
    ).one()
    return f"{documents}@{ingested.isoformat() if ingested is not None else 'empty'}"
