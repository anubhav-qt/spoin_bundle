"""Parsing and validating one image manifest against the delivery contract.

The contract itself is § 10 of `docs/handoff/antigravity-corpus-authoring.md` and
Phase 1 of `docs/tasks/0040-open-licensed-image-catalog.md`; this module is the machine
half of it, exactly as `frog/ingest/contract.py` is for prose.

**Purity is the point.** Nothing here opens a database, loads a model, or touches the
network — not even to check that a `source_url` resolves. That is what makes
`make image-check` runnable by the authoring track while it works, and it is easy to
destroy: a URL liveness probe belongs behind a separate flag, never in `--check`
(task 0040, Phase 2).

**Every problem in every manifest is reported, never the first.** Same reasoning as the
prose contract: a manifest is a list of 76 entries authored in one pass, so its mistakes
arrive in batches and a fail-fast validator would surface them one run at a time.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from frog.embeddings import normalize_topic_text
from frog.universe.models import ImageLicence

#: Same anchored front-matter shape as the prose contract. A manifest is front matter
#: and nothing else — there is no body, and a body is an error rather than ignored
#: content, because prose in a manifest is prose nothing will ever read.
_FRONT_MATTER = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---[ \t]*\r?\n?(?P<body>.*)\Z", re.S)

#: The only `kind` a manifest may declare, mirroring `document.kind`'s closed
#: vocabulary. Present so a corpus document accidentally saved under `images/` fails
#: loudly instead of being parsed as an empty manifest.
MANIFEST_KIND = "image_manifest"

#: Manifests live here, mirroring the corpus hierarchy so an image sits beside the
#: subject it illustrates.
DEFAULT_IMAGES_ROOT = Path("docs/the_spoin_universe/images")

#: A description shorter than this is almost certainly a caption or alt text rather
#: than the retrieval surface the contract asks for.
#:
#: **This bound is real but deliberately loose.** `description` is what gets embedded
#: and matched against a card's body, so "Saturn" retrieves nothing in particular while
#: "Saturn's rings backlit by the sun, photographed by Cassini from within the planet's
#: shadow" retrieves a card about ring composition. No length can tell those apart —
#: the check catches the entry nobody wrote, not the entry written badly. Measured
#: against the delivered astronomy manifest, whose 76 descriptions run 397-730
#: characters, so this fails none of them and is not a ceiling in disguise.
MIN_DESCRIPTION_CHARS = 120

#: Required on every entry. Listed once, here, so the error message and the schema's
#: NOT NULLs cannot drift apart.
_REQUIRED_ENTRY_FIELDS = (
    "title",
    "description",
    "source_url",
    "source_page",
    "licence",
    "attribution",
)


@dataclass(frozen=True)
class ParsedImage:
    """One manifest entry that satisfied the contract, ready to become a row.

    No embedding, for `ParsedDocument`'s reason: parsing is pure and testable without a
    model, and embedding is the runner's job.
    """

    source_url: str
    content_hash: str
    title: str
    description: str
    source_page: str
    licence: ImageLicence
    attribution: str
    topic_tags: list[str]


@dataclass(frozen=True)
class ParsedManifest:
    """One `images.md` that satisfied the contract."""

    manifest_path: str
    category: str
    sub_category: str | None
    images: list[ParsedImage]


@dataclass
class ManifestErrors:
    """Every contract violation in one manifest, collected rather than raised."""

    manifest_path: str
    problems: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.problems)


def entry_hash(entry: ParsedImage) -> str:
    """sha256 of the fields that decide what this row means.

    **Per entry, not per file**, which is the one place this contract deliberately
    departs from the prose one. A manifest is a list: hashing the whole file would
    rebuild all 76 rows because one description was reworded, and every rebuilt row
    costs a GPU embedding. Hashing the entry makes re-ingestion cost exactly what
    changed.

    `topic_tags` is included because it is a retrieval filter — changing it changes
    which cards can reach the image — and the embedding-bearing `description` is
    included for the obvious reason. `title` and `attribution` are included because
    they are displayed; a corrected attribution must actually reach the database.
    """

    payload = json.dumps(
        {
            "title": entry.title,
            "description": entry.description,
            "source_url": entry.source_url,
            "source_page": entry.source_page,
            "licence": entry.licence.value,
            "attribution": entry.attribution,
            "topic_tags": entry.topic_tags,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_manifest(manifest_path: str, raw: bytes) -> tuple[ParsedManifest | None, ManifestErrors]:
    """Parse and validate one manifest. Returns it, or the reasons it failed.

    Never raises for bad content: a malformed manifest is data about the delivery, and
    the caller wants all of it at once.
    """

    errors = ManifestErrors(manifest_path=manifest_path)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.problems.append(f"not valid UTF-8: {exc}")
        return None, errors

    match = _FRONT_MATTER.match(text)
    if match is None:
        errors.problems.append("no YAML front matter (file must open with a `---` line)")
        return None, errors

    try:
        loaded = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        errors.problems.append(f"front matter is not valid YAML: {exc}")
        return None, errors

    if not isinstance(loaded, dict):
        errors.problems.append("front matter is not a mapping")
        return None, errors

    front: dict[str, Any] = loaded

    if match.group("body").strip():
        errors.problems.append(
            "a manifest is front matter only — the text after the closing `---` would "
            "never be read, so it is an error rather than a comment"
        )

    kind = front.get("kind")
    if kind != MANIFEST_KIND:
        errors.problems.append(f"`kind` must be exactly `{MANIFEST_KIND}`, got {kind!r}")

    category = _normalized(front, "category", errors, required=True)
    sub_category = _normalized(front, "sub_category", errors, required=False)

    images = _images(front, errors)

    if errors or category is None:
        return None, errors

    return (
        ParsedManifest(
            manifest_path=manifest_path,
            category=category,
            sub_category=sub_category,
            images=images,
        ),
        errors,
    )


def parse_images(root: Path) -> tuple[list[ParsedManifest], list[ManifestErrors]]:
    """Walk `root`, parse every manifest, and report everything at once.

    A missing directory is an empty delivery rather than an error: a topic with no
    sourceable imagery is a normal outcome the contract explicitly asks the authoring
    track to report (task 0040, Phase 1), and so is a repository that has none yet.
    """

    parsed: list[ParsedManifest] = []
    failures: list[ManifestErrors] = []
    if not root.is_dir():
        return parsed, failures

    #: Sorted so two runs over the same tree report in the same order — a diffable
    #: report is worth more to the authoring track than filesystem order.
    for path in sorted(root.rglob("*.md")):
        manifest_path = path.relative_to(root).as_posix()
        manifest, errors = parse_manifest(manifest_path, path.read_bytes())
        if manifest is not None:
            parsed.append(manifest)
        if errors:
            failures.append(errors)

    _reject_cross_manifest_duplicates(parsed, failures)
    return parsed, failures


def _reject_cross_manifest_duplicates(
    parsed: list[ParsedManifest], failures: list[ManifestErrors]
) -> None:
    """Fail a `source_url` delivered in more than one manifest.

    `image.source_url` is globally unique, so this would otherwise surface as an
    integrity error mid-ingest, naming a constraint rather than the two files that
    disagree. Checked across manifests because within one it is already caught, and
    because the same photograph turning up under two subjects is exactly the mistake a
    per-file check cannot see.
    """

    seen: dict[str, str] = {}
    for manifest in parsed:
        for image in manifest.images:
            first = seen.setdefault(image.source_url, manifest.manifest_path)
            if first != manifest.manifest_path:
                failures.append(
                    ManifestErrors(
                        manifest_path=manifest.manifest_path,
                        problems=[
                            f"`source_url` {image.source_url} was already delivered in "
                            f"{first} — an image is one catalog entry, so pick the "
                            f"manifest it belongs in and remove the other"
                        ],
                    )
                )


def _images(front: dict[str, Any], errors: ManifestErrors) -> list[ParsedImage]:
    raw = front.get("images")
    if raw is None:
        errors.problems.append("`images` is missing (a manifest with no entries is not a manifest)")
        return []
    if not isinstance(raw, list) or not raw:
        errors.problems.append(f"`images` must be a non-empty list, got {raw!r}")
        return []

    images: list[ParsedImage] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        image = _image(entry, index, errors)
        if image is None:
            continue
        if image.source_url in seen:
            errors.problems.append(
                f"images[{index}] ({image.title!r}): duplicate `source_url` within this "
                f"manifest — {image.source_url}"
            )
            continue
        seen.add(image.source_url)
        images.append(image)
    return images


def _image(entry: Any, index: int, errors: ManifestErrors) -> ParsedImage | None:
    """One entry. `index` is in every message: a manifest has no other way to say where."""

    where = f"images[{index}]"
    if not isinstance(entry, dict):
        errors.problems.append(f"{where}: must be a mapping, got {entry!r}")
        return None

    values: dict[str, str] = {}
    for key in _REQUIRED_ENTRY_FIELDS:
        value = entry.get(key)
        if value is None:
            errors.problems.append(
                f"{where}: `{key}` is missing (required by the contract, NOT NULL in the schema)"
            )
            continue
        if not isinstance(value, str) or not value.strip():
            errors.problems.append(f"{where}: `{key}` must be a non-empty string, got {value!r}")
            continue
        values[key] = value.strip()

    licence = _licence(values.get("licence"), where, errors)
    description = values.get("description")
    if description is not None and len(description) < MIN_DESCRIPTION_CHARS:
        errors.problems.append(
            f"{where}: `description` is {len(description)} characters, under the "
            f"{MIN_DESCRIPTION_CHARS} minimum — it is the text a card's body is matched "
            f"against, not alt text, so it needs to say what is IN the image and what it "
            f"illustrates"
        )

    topic_tags = _topic_tags(entry, where, errors)

    if len(values) != len(_REQUIRED_ENTRY_FIELDS) or licence is None or description is None:
        return None

    image = ParsedImage(
        source_url=values["source_url"],
        #: Filled by the `replace` below — `entry_hash` hashes the finished entry, so
        #: it cannot be computed before one exists.
        content_hash="",
        title=values["title"],
        description=description,
        source_page=values["source_page"],
        licence=licence,
        attribution=values["attribution"],
        topic_tags=topic_tags,
    )
    return replace(image, content_hash=entry_hash(image))


def _licence(raw: str | None, where: str, errors: ManifestErrors) -> ImageLicence | None:
    if raw is None:
        return None
    try:
        return ImageLicence(raw)
    except ValueError:
        allowed = ", ".join(member.value for member in ImageLicence)
        errors.problems.append(
            f"{where}: `licence` {raw!r} is not in the allowlist ({allowed}). NonCommercial "
            f"is excluded because Spoin is commercial, and NoDerivatives because serving at "
            f"card width crops and resizes — a derivative work (task 0040)"
        )
        return None


def _topic_tags(entry: dict[str, Any], where: str, errors: ManifestErrors) -> list[str]:
    raw = entry.get("topic_tags")
    if raw is None:
        errors.problems.append(f"{where}: `topic_tags` is missing")
        return []
    if not isinstance(raw, list) or not raw:
        errors.problems.append(f"{where}: `topic_tags` must be a non-empty list, got {raw!r}")
        return []
    tags: list[str] = []
    for tag in raw:
        if not isinstance(tag, str) or not tag.strip():
            errors.problems.append(f"{where}: every `topic_tags` entry must be a non-empty string")
            continue
        #: The same normalizer prose tags go through (ADR-0093), so a tag written here
        #: and a topic name written in a curriculum cannot become two vocabularies.
        normalized = normalize_topic_text(tag)
        if normalized not in tags:
            tags.append(normalized)
    return tags


def _normalized(
    front: dict[str, Any], key: str, errors: ManifestErrors, *, required: bool
) -> str | None:
    """A hierarchy field from the manifest header, normalized as `document`'s are.

    Read at the manifest level rather than per entry because that is where the delivered
    manifests carry it, and because repeating a category on 76 entries is 76 chances to
    typo one of them into its own category.
    """

    if key not in front:
        if required:
            errors.problems.append(f"`{key}` is required on the manifest header (ADR-0091)")
        return None
    value = front[key]
    if not isinstance(value, str) or not value.strip():
        errors.problems.append(f"`{key}` must be a non-empty string, got {value!r}")
        return None
    return normalize_topic_text(value)
