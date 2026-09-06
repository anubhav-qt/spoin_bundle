"""Tests for ingesting image manifests into `the_spoin_universe` (ADR-0095, Task 0040).

Tests idempotency, removal of withdrawn entries, updates, and force re-embedding.
Requires SPOIN_UNIVERSE_TEST_DATABASE_URL; skips if unset.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from frog.embeddings import HashEmbedder
from frog.images.contract import parse_manifest
from frog.images.runner import ingest_manifest
from frog.universe.models import EMBEDDING_DIM, Image

EMBEDDER = HashEmbedder(EMBEDDING_DIM)

MANIFEST_V1 = b"""---
kind: image_manifest
category: astronomy
sub_category: physics/astronomy
images:
  - title: "Ring Galaxy AM 0644-741"
    description: "Hubble Space Telescope image of the ring galaxy AM 0644-741, showing a brilliant blue ring of newborn star clusters surrounding a yellowish nucleus. The ring formed from a collision with another galaxy."
    source_url: "https://images-assets.nasa.gov/image/ring_galaxy/ring_galaxy~orig.jpg"
    source_page: "https://images.nasa.gov/details/ring_galaxy"
    licence: public-domain
    attribution: "NASA, ESA, and the Hubble Heritage Team (STScI/AURA)"
    topic_tags:
      - galaxies
  - title: "Crab Nebula M1"
    description: "Supernova remnant in Taurus observed by Hubble, displaying filamentary structure and expanding gas clouds ionized by the central pulsar wind nebula in deep space."
    source_url: "https://images-assets.nasa.gov/image/crab_nebula/crab_nebula~orig.jpg"
    source_page: "https://images.nasa.gov/details/crab_nebula"
    licence: public-domain
    attribution: "NASA, ESA, J. Hester and A. Loll (Arizona State University)"
    topic_tags:
      - nebulae
---
"""

MANIFEST_WITHDRAWN = b"""---
kind: image_manifest
category: astronomy
sub_category: physics/astronomy
images:
  - title: "Ring Galaxy AM 0644-741"
    description: "Hubble Space Telescope image of the ring galaxy AM 0644-741, showing a brilliant blue ring of newborn star clusters surrounding a yellowish nucleus. The ring formed from a collision with another galaxy."
    source_url: "https://images-assets.nasa.gov/image/ring_galaxy/ring_galaxy~orig.jpg"
    source_page: "https://images.nasa.gov/details/ring_galaxy"
    licence: public-domain
    attribution: "NASA, ESA, and the Hubble Heritage Team (STScI/AURA)"
    topic_tags:
      - galaxies
---
"""

MANIFEST_UPDATED = b"""---
kind: image_manifest
category: astronomy
sub_category: physics/astronomy
images:
  - title: "Ring Galaxy AM 0644-741 (Updated Description)"
    description: "Hubble Space Telescope image of the ring galaxy AM 0644-741, showing an updated brilliant blue ring of newborn star clusters surrounding a yellowish nucleus after collision."
    source_url: "https://images-assets.nasa.gov/image/ring_galaxy/ring_galaxy~orig.jpg"
    source_page: "https://images.nasa.gov/details/ring_galaxy"
    licence: public-domain
    attribution: "NASA, ESA, and the Hubble Heritage Team (STScI/AURA)"
    topic_tags:
      - galaxies
  - title: "Crab Nebula M1"
    description: "Supernova remnant in Taurus observed by Hubble, displaying filamentary structure and expanding gas clouds ionized by the central pulsar wind nebula in deep space."
    source_url: "https://images-assets.nasa.gov/image/crab_nebula/crab_nebula~orig.jpg"
    source_page: "https://images.nasa.gov/details/crab_nebula"
    licence: public-domain
    attribution: "NASA, ESA, J. Hester and A. Loll (Arizona State University)"
    topic_tags:
      - nebulae
---
"""


async def _count_rows(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(Image))).scalar_one()


async def test_ingest_manifest_idempotency(session: AsyncSession) -> None:
    manifest, errors = parse_manifest("astronomy/images.md", MANIFEST_V1)
    assert manifest is not None and not errors.problems

    # 1. First ingest creates rows
    created, updated, unchanged, removed = await ingest_manifest(session, manifest, EMBEDDER)
    await session.commit()
    assert (created, updated, unchanged, removed) == (2, 0, 0, 0)
    assert await _count_rows(session) == 2

    # 2. Second ingest is clean no-op
    created, updated, unchanged, removed = await ingest_manifest(session, manifest, EMBEDDER)
    await session.commit()
    assert (created, updated, unchanged, removed) == (0, 0, 2, 0)
    assert await _count_rows(session) == 2


async def test_ingest_manifest_removes_withdrawn_entries(session: AsyncSession) -> None:
    m_v1, _ = parse_manifest("astronomy/images.md", MANIFEST_V1)
    assert m_v1 is not None
    await ingest_manifest(session, m_v1, EMBEDDER)
    await session.commit()
    assert await _count_rows(session) == 2

    # Re-ingest with Crab Nebula withdrawn
    m_withdrawn, _ = parse_manifest("astronomy/images.md", MANIFEST_WITHDRAWN)
    assert m_withdrawn is not None
    created, updated, unchanged, removed = await ingest_manifest(session, m_withdrawn, EMBEDDER)
    await session.commit()
    assert (created, updated, unchanged, removed) == (0, 0, 1, 1)
    assert await _count_rows(session) == 1

    remaining = (await session.execute(select(Image))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].title == "Ring Galaxy AM 0644-741"


async def test_ingest_manifest_updates_and_force(session: AsyncSession) -> None:
    m_v1, _ = parse_manifest("astronomy/images.md", MANIFEST_V1)
    assert m_v1 is not None
    await ingest_manifest(session, m_v1, EMBEDDER)
    await session.commit()

    # Ingest updated description
    m_up, _ = parse_manifest("astronomy/images.md", MANIFEST_UPDATED)
    assert m_up is not None
    created, updated, unchanged, removed = await ingest_manifest(session, m_up, EMBEDDER)
    await session.commit()
    assert (created, updated, unchanged, removed) == (0, 1, 1, 0)

    # Force re-embeds all rows
    created, updated, unchanged, removed = await ingest_manifest(
        session, m_up, EMBEDDER, force=True
    )
    await session.commit()
    assert (created, updated, unchanged, removed) == (0, 2, 0, 0)
