"""Re-ingesting the corpus must not duplicate it.

This is the requirement Phase 2 exists to satisfy (ADR-0088): the corpus is
**re-delivered many times** as it is supervised and revised, so an ingester that adds
rows on the second run is not an ingester. The failure is silent — retrieval simply
starts returning the same passage twice and spending the prompt budget on it — which is
why this is tested against a real database rather than against the control flow.

Skipped when `SPOIN_UNIVERSE_TEST_DATABASE_URL` is unset; see conftest.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from frog.embeddings import HashEmbedder
from frog.ingest.contract import parse_document
from frog.ingest.runner import ingest_corpus, ingest_document
from frog.universe.models import EMBEDDING_DIM, Chunk, Document

DOC = b"""---
title: MVCC and transaction isolation
kind: topic_source
category: computer science
scope: topic
source: https://www.postgresql.org/docs/17/mvcc.html
topic_tags:
  - postgresql
---

## Snapshot isolation

Each transaction sees a snapshot taken at its start.

## Phantom reads

Postgres also prevents them at REPEATABLE READ.
"""

#: Semantically meaningless and that is fine here: what is under test is row identity,
#: not retrieval. Nothing in this file draws a conclusion from a vector's contents.
EMBEDDER = HashEmbedder(EMBEDDING_DIM)


async def _counts(session: AsyncSession) -> tuple[int, int]:
    documents = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
    chunks = (await session.execute(select(func.count()).select_from(Chunk))).scalar_one()
    return documents, chunks


async def _ingest(session: AsyncSession, raw: bytes, *, force: bool = False) -> int:
    parsed, errors = parse_document("cs/pg/mvcc.md", raw)
    assert parsed is not None, errors.problems
    written = await ingest_document(session, parsed, EMBEDDER, force=force)
    await session.commit()
    return written


async def test_first_ingestion_writes_document_and_chunks(session: AsyncSession) -> None:
    written = await _ingest(session, DOC)

    assert written == 2
    assert await _counts(session) == (1, 2)


async def test_reingesting_an_unchanged_document_is_a_no_op(session: AsyncSession) -> None:
    """The hash matched, so nothing is read, embedded or written.

    Asserted on `ingested_at` as well as on the counts: a delete-and-reinsert that
    happened to produce the same row count would pass a count-only test while paying
    the embedding cost of a full re-ingest on every delivery.
    """

    await _ingest(session, DOC)
    before = (await session.execute(select(Document.ingested_at))).scalar_one()

    assert await _ingest(session, DOC) == 0
    assert await _counts(session) == (1, 2)
    assert (await session.execute(select(Document.ingested_at))).scalar_one() == before


async def test_a_changed_document_replaces_its_chunks_rather_than_adding_them(
    session: AsyncSession,
) -> None:
    """The document row survives — cards cite chunk IDs against it (ADR-0089) — and its
    chunks are rebuilt wholesale."""

    await _ingest(session, DOC)
    document_id = (await session.execute(select(Document.id))).scalar_one()

    revised = DOC.replace(b"## Phantom reads", b"## Phantom reads\n\nExtra.\n\n## Write skew")
    assert await _ingest(session, revised) == 3

    assert await _counts(session) == (1, 3)
    assert (await session.execute(select(Document.id))).scalar_one() == document_id
    ordinals = (
        (await session.execute(select(Chunk.ordinal).order_by(Chunk.ordinal))).scalars().all()
    )
    assert list(ordinals) == [0, 1, 2]


async def test_a_revision_updates_the_stored_metadata(session: AsyncSession) -> None:
    await _ingest(session, DOC)
    revised = DOC.replace(b"title: MVCC and transaction isolation", b"title: MVCC, revised")
    await _ingest(session, revised)

    document = (await session.execute(select(Document))).scalar_one()
    assert document.title == "MVCC, revised"
    #: The header is part of the stored chunk text, so a title change must reach the
    #: chunks too. It only does because a changed hash rebuilds them.
    chunk = (await session.execute(select(Chunk).order_by(Chunk.ordinal))).scalars().first()
    assert chunk is not None
    assert chunk.text.startswith("MVCC, revised — ")


async def test_force_re_embeds_an_unchanged_document(session: AsyncSession) -> None:
    """`--force` exists for the case a hash cannot see: the file is identical but what
    we embed from it changed — a new chunking rule, a different header format."""

    await _ingest(session, DOC)
    assert await _ingest(session, DOC, force=True) == 2
    assert await _counts(session) == (1, 2)


async def test_deleting_a_document_cascades_to_its_chunks(session: AsyncSession) -> None:
    """`ondelete=CASCADE` is the schema's guarantee, not the ingester's. Asserted here
    because the replace path above relies on chunks having no independent lifetime."""

    await _ingest(session, DOC)
    document = (await session.execute(select(Document))).scalar_one()
    await session.delete(document)
    await session.commit()

    assert await _counts(session) == (0, 0)


async def test_ingest_corpus_reports_failures_separately_from_unchanged(
    session: AsyncSession, tmp_path: Path
) -> None:
    """CLAUDE.md: a document judged and rejected is not the same fact as one that was
    correct and simply unchanged. Folding them into one number makes a clean idempotent
    re-run read as a validation catastrophe.
    """

    (tmp_path / "good.md").write_bytes(DOC)
    (tmp_path / "bad.md").write_bytes(DOC.replace(b"title: MVCC and transaction isolation\n", b""))
    (tmp_path / "README.md").write_bytes(b"not corpus content")

    first = await ingest_corpus(session, tmp_path, EMBEDDER)
    await session.commit()

    assert (first.scanned, first.ingested, first.unchanged, first.failed) == (2, 1, 0, 1)
    assert first.chunks_written == 2
    assert first.errors[0].source_path == "bad.md"

    second = await ingest_corpus(session, tmp_path, EMBEDDER)
    await session.commit()

    assert (second.scanned, second.ingested, second.unchanged, second.failed) == (2, 0, 1, 1)
    assert second.chunks_written == 0
    assert await _counts(session) == (1, 2)
