"""Ingesting validated image manifests into `the_spoin_universe`.

The prose counterpart is `frog/ingest/runner.py`, and the posture is deliberately the
same: validate everything before writing anything, let a failing manifest not stop the
others, and skip what has not changed.

**What is NOT here: the Cloudinary upload.** Task 0040's Phase 2 puts it at this point
in the flow, and it is left out on purpose — the constraint Cloudinary exists to solve
is bandwidth at user scale, and there are no users. `image.cloudinary_url` is created
nullable so the upload lands later as a backfill over existing rows rather than as a
migration plus a re-ingest that would re-embed the whole catalog on a GPU to write one
URL per row. Until then the renderer serves `source_url`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from frog.embeddings import Embedder
from frog.images.contract import ManifestErrors, ParsedImage, ParsedManifest, parse_images
from frog.universe.models import Image

logger = logging.getLogger(__name__)

#: Same batch size the prose ingester uses. A description is far shorter than a corpus
#: section, so this is comfortable rather than tuned.
_EMBED_BATCH = 64


@dataclass
class ImageIngestReport:
    """What one run did, in the terms the authoring track asks about."""

    scanned_manifests: int = 0
    failed_manifests: int = 0
    #: Entries written for the first time.
    created: int = 0
    #: Entries whose hash changed and were rewritten (and re-embedded).
    updated: int = 0
    #: Entries whose hash matched — no embedding, no write.
    unchanged: int = 0
    #: Rows whose manifest no longer lists them. Removed, because a manifest is the
    #: truth and the database follows it (the projection's posture, not the corpus's:
    #: an image the author withdrew must stop being assignable).
    removed: int = 0
    errors: list[ManifestErrors] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"manifests={self.scanned_manifests} failed={self.failed_manifests} "
            f"created={self.created} updated={self.updated} "
            f"unchanged={self.unchanged} removed={self.removed}"
        )


async def ingest_manifest(
    session: AsyncSession,
    manifest: ParsedManifest,
    embedder: Embedder,
    *,
    force: bool = False,
) -> tuple[int, int, int, int]:
    """Reconcile one manifest's entries against the catalog.

    Returns `(created, updated, unchanged, removed)`.

    **Embedding is batched across everything that changed**, not done per entry: the
    embedder is a GPU model whose per-call overhead dominates a single short
    description, which is the same reason `ingest_document` embeds a document's sections
    in one call.
    """

    existing = {
        image.source_url: image
        for image in (
            await session.execute(
                select(Image).where(Image.manifest_path == manifest.manifest_path)
            )
        )
        .scalars()
        .all()
    }

    delivered = {image.source_url: image for image in manifest.images}

    stale = [stale_row for url, stale_row in existing.items() if url not in delivered]
    for stale_row in stale:
        await session.delete(stale_row)

    changed: list[ParsedImage] = []
    unchanged = 0
    for entry in manifest.images:
        existing_row = existing.get(entry.source_url)
        if (
            existing_row is not None
            and existing_row.content_hash == entry.content_hash
            and not force
        ):
            unchanged += 1
            continue
        changed.append(entry)

    if not changed:
        return 0, 0, unchanged, len(stale)

    #: Embedded before any write, so a model failure cannot leave rows whose hash
    #: claims they are current. On the PASSAGE side: a catalog description is what is
    #: being searched, not what is searching (ADR-0092) — getting that backwards is a
    #: silent recall loss rather than an error.
    vectors: list[list[float]] = []
    descriptions = [entry.description for entry in changed]
    for start in range(0, len(descriptions), _EMBED_BATCH):
        vectors.extend(await embedder.aembed_passage(descriptions[start : start + _EMBED_BATCH]))
    model_name = embedder.model_name

    created = updated = 0
    now = datetime.now(UTC)
    for entry, vector in zip(changed, vectors, strict=True):
        row = existing.get(entry.source_url)
        if row is None:
            #: A `source_url` already claimed by ANOTHER manifest is caught in the
            #: contract, before anything is written — the unique constraint here is the
            #: backstop, not the check.
            row = Image(source_url=entry.source_url)
            session.add(row)
            created += 1
        else:
            updated += 1

        row.manifest_path = manifest.manifest_path
        row.content_hash = entry.content_hash
        row.title = entry.title
        row.description = entry.description
        row.source_page = entry.source_page
        row.licence = entry.licence
        row.attribution = entry.attribution
        row.category = manifest.category
        row.sub_category = manifest.sub_category
        row.topic_tags = list(entry.topic_tags)
        row.embedding = list(vector)
        row.embedding_model = model_name
        row.ingested_at = now
        #: `cloudinary_url` is deliberately NOT touched. Re-ingesting a reworded
        #: description must not discard an upload that already happened — that is the
        #: whole point of keeping the column out of the entry hash.

    return created, updated, unchanged, len(stale)


async def ingest_images(
    session: AsyncSession,
    root: Path,
    embedder: Embedder,
    *,
    force: bool = False,
) -> ImageIngestReport:
    """Validate every manifest under `root`, then ingest the ones that passed."""

    parsed, failures = parse_images(root)
    report = ImageIngestReport(
        scanned_manifests=len(parsed) + len(failures),
        failed_manifests=len(failures),
        errors=failures,
    )

    for manifest in parsed:
        created, updated, unchanged, removed = await ingest_manifest(
            session, manifest, embedder, force=force
        )
        report.created += created
        report.updated += updated
        report.unchanged += unchanged
        report.removed += removed
        logger.info(
            "ingested %s (+%d ~%d =%d -%d)",
            manifest.manifest_path,
            created,
            updated,
            unchanged,
            removed,
        )

    return report
