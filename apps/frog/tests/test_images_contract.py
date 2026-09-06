"""Contract validation for authored image manifests (ADR-0095, Task 0040).

Pure parser tests -- no database and no model.
"""

from __future__ import annotations

from pathlib import Path

from frog.images.contract import (
    MIN_DESCRIPTION_CHARS,
    ParsedImage,
    ParsedManifest,
    entry_hash,
    parse_images,
    parse_manifest,
)
from frog.universe.models import ImageLicence


def _find_delivered_astronomy_path() -> Path:
    candidates = [
        Path("docs/the_spoin_universe/images/astronomy/physics/astronomy/images.md"),
        Path("/app/docs/the_spoin_universe/images/astronomy/physics/astronomy/images.md"),
        Path(__file__).parents[2]
        / "docs"
        / "the_spoin_universe"
        / "images"
        / "astronomy"
        / "physics"
        / "astronomy"
        / "images.md",
        Path(__file__).parents[3]
        / "docs"
        / "the_spoin_universe"
        / "images"
        / "astronomy"
        / "physics"
        / "astronomy"
        / "images.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


SAMPLE_VALID = b"""---
kind: image_manifest
category: astronomy
sub_category: physics astronomy
images:
  - title: "Ring Galaxy AM 0644-741"
    description: "Hubble Space Telescope image of the ring galaxy AM 0644-741, showing a brilliant blue ring of newborn star clusters surrounding a yellowish nucleus. The ring formed from a collision with another galaxy."
    source_url: "https://images-assets.nasa.gov/image/ring_galaxy/ring_galaxy~orig.jpg"
    source_page: "https://images.nasa.gov/details/ring_galaxy"
    licence: public-domain
    attribution: "NASA, ESA, and the Hubble Heritage Team (STScI/AURA)"
    topic_tags:
      - galaxies
      - cosmology
---
"""


def _parse(
    raw: bytes, path: str = "astronomy/images.md"
) -> tuple[ParsedManifest | None, list[str]]:
    manifest, errors = parse_manifest(path, raw)
    return manifest, errors.problems


def test_delivered_astronomy_manifest_parses_clean() -> None:
    path = _find_delivered_astronomy_path()
    assert path.exists(), f"missing delivered manifest at {path}"
    raw = path.read_bytes()
    manifest, problems = _parse(raw, str(path))
    assert problems == []
    assert manifest is not None
    assert manifest.category == "astronomy"
    assert manifest.sub_category == "physics"
    assert len(manifest.images) == 76
    assert all(len(img.description) >= MIN_DESCRIPTION_CHARS for img in manifest.images)
    assert all(img.content_hash for img in manifest.images)


def test_valid_manifest_parses_clean() -> None:
    manifest, problems = _parse(SAMPLE_VALID)
    assert problems == []
    assert manifest is not None
    assert manifest.category == "astronomy"
    assert manifest.sub_category == "physics astronomy"
    assert len(manifest.images) == 1
    img = manifest.images[0]
    assert img.title == "Ring Galaxy AM 0644-741"
    assert img.licence == ImageLicence.PUBLIC_DOMAIN
    assert img.attribution == "NASA, ESA, and the Hubble Heritage Team (STScI/AURA)"
    assert img.topic_tags == ["galaxies", "cosmology"]
    assert img.content_hash == entry_hash(img)


def test_licence_allowlist_rejection() -> None:
    invalid = SAMPLE_VALID.replace(b"licence: public-domain", b"licence: cc-by-nc-4.0")
    manifest, problems = _parse(invalid)
    assert manifest is None
    assert any("not in the allowlist" in p for p in problems)


def test_short_description_rejection() -> None:
    short = SAMPLE_VALID.replace(
        b'description: "Hubble Space Telescope image of the ring galaxy AM 0644-741, '
        b"showing a brilliant blue ring of newborn star clusters surrounding a yellowish "
        b'nucleus. The ring formed from a collision with another galaxy."',
        b'description: "Short caption of a galaxy."',
    )
    manifest, problems = _parse(short)
    assert manifest is None
    assert any("under the 120 minimum" in p for p in problems)


def test_duplicate_source_url_within_manifest_rejected() -> None:
    duplicate = b"""---
kind: image_manifest
category: astronomy
images:
  - title: "Galaxy One"
    description: "Hubble Space Telescope image of the ring galaxy AM 0644-741, showing a brilliant blue ring of newborn star clusters surrounding a yellowish nucleus. The ring formed from a collision with another galaxy."
    source_url: "https://images-assets.nasa.gov/image/shared/img.jpg"
    source_page: "https://images.nasa.gov/details/one"
    licence: public-domain
    attribution: "NASA"
    topic_tags: [galaxies]
  - title: "Galaxy Two"
    description: "Another wide view of the ring galaxy AM 0644-741, showing detailed tidal tails and ionized gas structures surrounding the collision zone between the two interacting galaxies in deep space."
    source_url: "https://images-assets.nasa.gov/image/shared/img.jpg"
    source_page: "https://images.nasa.gov/details/two"
    licence: public-domain
    attribution: "NASA"
    topic_tags: [galaxies]
---
"""
    manifest, problems = _parse(duplicate)
    assert manifest is None
    assert any("duplicate `source_url` within this manifest" in p for p in problems)


def test_duplicate_source_url_across_manifests(tmp_path: Path) -> None:
    m1 = tmp_path / "cat1" / "images.md"
    m1.parent.mkdir(parents=True)
    m1.write_bytes(SAMPLE_VALID.replace(b"category: astronomy", b"category: cat1"))

    m2 = tmp_path / "cat2" / "images.md"
    m2.parent.mkdir(parents=True)
    m2.write_bytes(SAMPLE_VALID.replace(b"category: astronomy", b"category: cat2"))

    parsed, failures = parse_images(tmp_path)
    assert len(parsed) == 2
    assert len(failures) == 1
    assert "was already delivered in" in failures[0].problems[0]


def test_entry_hash_stability() -> None:
    img1 = ParsedImage(
        source_url="https://example.com/img.jpg",
        content_hash="",
        title="Title",
        description="A sufficiently detailed description that spans well over the required minimum length of one hundred and twenty characters for catalog indexing.",
        source_page="https://example.com/page",
        licence=ImageLicence.PUBLIC_DOMAIN,
        attribution="NASA",
        topic_tags=["astronomy"],
    )
    img2 = ParsedImage(
        source_url="https://example.com/img.jpg",
        content_hash="",
        title="Title",
        description="A sufficiently detailed description that spans well over the required minimum length of one hundred and twenty characters for catalog indexing.",
        source_page="https://example.com/page",
        licence=ImageLicence.PUBLIC_DOMAIN,
        attribution="NASA",
        topic_tags=["astronomy"],
    )
    h1 = entry_hash(img1)
    h2 = entry_hash(img2)
    assert h1 == h2
    assert len(h1) == 64

    # Changing any field changes the hash
    img_modified = ParsedImage(
        source_url="https://example.com/img.jpg",
        content_hash="",
        title="Different Title",
        description=img1.description,
        source_page=img1.source_page,
        licence=img1.licence,
        attribution=img1.attribution,
        topic_tags=img1.topic_tags,
    )
    assert entry_hash(img_modified) != h1


def test_body_after_closing_frontmatter_rejected() -> None:
    trailing = SAMPLE_VALID + b"\nExtra trailing body text that should cause a validation error.\n"
    manifest, problems = _parse(trailing)
    assert manifest is None
    assert any("a manifest is front matter only" in p for p in problems)
