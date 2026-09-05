"""Walking the delivered corpus and writing it into `the_spoin_universe`.

The whole file is organised around one requirement: **re-ingesting an unchanged corpus
must be a no-op** (ADR-0088). The corpus is re-delivered many times as it is supervised
and revised, so an ingester that duplicates chunks on the second run is not an ingester.

Identity is `source_path`; change is a sha256 of the raw file. Both were chosen over a
hand-maintained version field in front matter, because a version bump can be forgotten
and its failure mode — stale chunks silently surviving a revision — is invisible.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from frog.embeddings import Embedder
from frog.ingest.chunking import chunk_texts
from frog.ingest.contract import DocumentErrors, ParsedDocument, parse_document
from frog.universe.models import Chunk, Document

logger = logging.getLogger(__name__)

#: Documents per embedding call. The passage side is bulk, offline and GPU-bound, so
#: this is about VRAM rather than about an API's rate limit — nothing here is metered.
#: ADR-0005's "always a collection, never a single item" rule is an LLM-quota rule and
#: does not apply, but batching is right here for the ordinary reason.
_EMBED_BATCH = 64

#: Not corpus content. The contract puts the layout's documentation in the tree itself.
_SKIP_NAMES = frozenset({"README.md"})


@dataclass
class IngestReport:
    """What one run did, in counts a human can check against the corpus.

    `failed` and `skipped` are separate fields on purpose, and neither is folded into
    the other. CLAUDE.md's rule — a document that was judged and rejected is not the
    same fact as one that was correct and simply unchanged — and reporting them as one
    number would make a clean idempotent re-run look like a validation catastrophe.
    """

    scanned: int = 0
    ingested: int = 0
    unchanged: int = 0
    failed: int = 0
    chunks_written: int = 0
    errors: list[DocumentErrors] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} ingested={self.ingested} unchanged={self.unchanged} "
            f"failed={self.failed} chunks_written={self.chunks_written}"
        )


def walk_corpus(root: Path) -> Iterator[Path]:
    """Every corpus document under `root`, in a stable order.

    Sorted so a run's log is diffable against the previous run's.
    """

    for path in sorted(root.rglob("*.md")):
        if path.name in _SKIP_NAMES:
            continue
        yield path


def source_path_of(root: Path, path: Path) -> str:
    """The document's identity: its path within the delivery, POSIX-separated.

    Forced to forward slashes because this value is a database key and the corpus is
    authored on one OS and ingested on another — a Windows-authored `a\\b.md` and a
    Linux-ingested `a/b.md` must not become two documents.
    """

    return path.relative_to(root).as_posix()


def parse_corpus(root: Path) -> tuple[list[ParsedDocument], list[DocumentErrors]]:
    """Parse and validate the whole corpus without touching the database.

    Separated from writing so validation is runnable on its own (`--check`), and so a
    corpus that is failing the contract can be reported in full before a single row is
    written.
    """

    parsed: list[ParsedDocument] = []
    failures: list[DocumentErrors] = []
    for path in walk_corpus(root):
        document, errors = parse_document(source_path_of(root, path), path.read_bytes())
        if document is None or errors:
            failures.append(errors)
            continue
        parsed.append(document)
    return parsed, failures


async def ingest_document(
    session: AsyncSession,
    parsed: ParsedDocument,
    embedder: Embedder,
    *,
    force: bool = False,
) -> int:
    """Write one document and its chunks. Returns the number of chunks written.

    Returns 0 and touches nothing when the hash is unchanged — that is the idempotency
    requirement, and it is why this is a hash comparison rather than a delete-and-insert
    that would be "idempotent" only in the sense that the row counts come out the same.

    The caller owns the transaction. A changed document's chunks are deleted and
    rebuilt, and a crash between those two must not leave a document with no chunks
    still claiming a current hash.
    """

    existing = (
        await session.execute(select(Document).where(Document.source_path == parsed.source_path))
    ).scalar_one_or_none()

    if existing is not None and existing.content_hash == parsed.content_hash and not force:
        return 0

    texts = chunk_texts(parsed)
    #: Embedded before the write so a model failure cannot leave a half-replaced
    #: document behind, and on the PASSAGE side — corpus material is what is being
    #: searched, not what is searching (ADR-0092). Getting this backwards is a silent
    #: recall loss, not an error.
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH):
        vectors.extend(await embedder.aembed_passage(texts[start : start + _EMBED_BATCH]))

    if existing is None:
        document = Document(source_path=parsed.source_path)
        session.add(document)
    else:
        document = existing
        #: CASCADE handles this when the document itself goes; a *revision* keeps the
        #: document row (and its id, which cards may cite) and replaces only its chunks.
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id))

    document.title = parsed.title
    document.kind = parsed.kind
    document.source = parsed.source
    document.category = parsed.category
    document.sub_category = parsed.sub_category
    document.scope = parsed.scope
    document.source_date = parsed.source_date
    document.content_hash = parsed.content_hash
    document.ingested_at = datetime.now(UTC)
    await session.flush()

    for ordinal, (text, vector) in enumerate(zip(texts, vectors, strict=True)):
        session.add(
            Chunk(
                document_id=document.id,
                ordinal=ordinal,
                text=text,
                embedding=vector,
                #: From the embedder that just produced `vector`, never from config —
                #: a stamp read from somewhere other than the thing that did the work
                #: is a stamp that can lie.
                embedding_model=embedder.model_name,
                #: Tags sit on `chunk` rather than `document` (ADR-0088) so a broad
                #: source can have differently-tagged sections. The contract has no
                #: per-section tagging yet, so every chunk inherits the document's —
                #: the column is where the capability lives, not where it is used.
                topic_tags=list(parsed.topic_tags),
            )
        )
    return len(texts)


async def ingest_corpus(
    session: AsyncSession,
    root: Path,
    embedder: Embedder,
    *,
    force: bool = False,
) -> IngestReport:
    """Validate the whole corpus, then ingest every document that passed.

    **Validation runs over everything before anything is written.** A corpus this size
    drifts in batches — the first real audit found 18 documents missing `title` and 26
    with an unparseable `source_date` — so an ingester that died on the first bad file
    would surface that as dozens of separate runs.

    A failing document does not stop the others. Partial ingestion is the right posture
    for a corpus authored by a track that is still writing it: the good documents are
    usable now, and the failures are a list to hand back.
    """

    parsed, failures = parse_corpus(root)
    report = IngestReport(
        scanned=len(parsed) + len(failures),
        failed=len(failures),
        errors=failures,
    )

    for document in parsed:
        written = await ingest_document(session, document, embedder, force=force)
        if written:
            report.ingested += 1
            report.chunks_written += written
            logger.info("ingested %s (%d chunks)", document.source_path, written)
        else:
            report.unchanged += 1
            logger.debug("unchanged %s", document.source_path)

    return report
