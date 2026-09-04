"""Parsing and validating one corpus document against the ingestion contract.

The contract itself is `docs/handoff/antigravity-corpus-authoring.md`; this module is
the machine half of it. Everything here exists because a corpus authored by one track
and consumed by another drifts — it already has, four ways, between two authoring runs
(see the Phase 2 section of docs/tasks/0038-frog-rag-and-hybrid-generation.md).

**Validation reports every problem in every document rather than dying on the first.**
A corpus this size drifts in batches, not one file at a time: the first real audit found
18 documents missing `title` and 26 with an unparseable `source_date`, and a
fail-fast validator would have surfaced those as eighteen and twenty-six separate runs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import yaml

from frog.embeddings import normalize_topic_text
from frog.universe.models import DocumentKind, DocumentScope

#: Front matter is a leading `---` line, a YAML block, and a closing `---` line.
#: Anchored at the start of the file: a `---` appearing later is a horizontal rule in
#: the prose, not a delimiter.
_FRONT_MATTER = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---[ \t]*\r?\n?(?P<body>.*)\Z", re.S)

#: `## ` at the start of a line. One section, one chunk — there is deliberately **no
#: sub-splitter**. A section is the author's own judgment about where one idea ends, and
#: a recursive splitter would overrule it with machinery that has read less of the
#: material than they have.
#:
#: That choice only holds if sections stay chunk-sized, which is why the size limit
#: below is enforced rather than suggested. Measured over 358 sections of the real
#: corpus with the actual `Qwen3-Embedding-0.6B` tokenizer: median 339 tokens, max 1385,
#: and 17% over 512 — so the guideline was NOT holding on its own (task 0038, Phase 2).
_SECTION = re.compile(r"^## +(?P<heading>.+?)[ \t]*$", re.M)

#: A section over this fails the document (owner's decision, 2026-09-05: 512 tokens,
#: enforced the same way the preamble rule is).
#:
#: **Characters, not tokens, and that is deliberate.** Counting real tokens means either
#: `tiktoken` — which fetches its BPE table over the network on first use, unacceptable
#: in a validator that must run offline — or the Qwen3 tokenizer, which would make
#: `--check` need a model download and stop it being the cheap, pure, GPU-free thing the
#: authoring track runs. Characters are exact, offline, zero-dependency, and something an
#: author can actually count.
#:
#: 2200 is calibrated, not guessed: this corpus measures 4.58 chars/token under Qwen3's
#: own tokenizer, so 2200 chars ≈ 512 tokens. Checked against every section in the
#: corpus, the proxy disagrees with a true 512-token cut on 6 of 358 (4 slightly over
#: that it lets through, 2 slightly under that it fails). Both errors land on sections
#: that are borderline anyway.
MAX_SECTION_CHARS = 2200

#: Accepted `source_date` forms, widened to the first instant of the period. A bare year
#: is honest for material whose source is "practitioner experience, Stack Overflow,
#: postmortems" — there is no single date to record, and demanding one would make the
#: authoring track invent a precision the source does not have. Full dates are still
#: preferred; the contract says so.
_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m", "%Y")


@dataclass(frozen=True)
class ParsedSection:
    """One `##` section: the chunk-to-be."""

    heading: str
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    """A corpus file that satisfied the contract, ready to become rows.

    Note what is *not* here: an embedding. Parsing is pure and testable without a
    model; embedding is the runner's job and needs a GPU.
    """

    source_path: str
    content_hash: str
    title: str
    kind: DocumentKind
    source: str
    category: str | None
    sub_category: str | None
    scope: DocumentScope | None
    source_date: datetime | None
    topic_tags: list[str]
    sections: list[ParsedSection]


@dataclass
class DocumentErrors:
    """Every contract violation in one document, collected rather than raised.

    `source_path` rather than an absolute path: it is the document's identity in the
    database (ADR-0088), so an error message and a `document` row name the same thing.
    """

    source_path: str
    problems: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.problems)


def content_hash(raw: bytes) -> str:
    """sha256 of the file as delivered.

    Hashed as **bytes, before decoding**, so a re-encoding that changes no characters
    still reads as a change. ADR-0088 chose a hash over a front-matter version field
    because a version bump can be forgotten and its failure mode — stale chunks
    silently surviving a revision — is invisible.
    """

    return hashlib.sha256(raw).hexdigest()


def parse_document(source_path: str, raw: bytes) -> tuple[ParsedDocument | None, DocumentErrors]:
    """Parse and validate one document. Returns the document, or the reasons it failed.

    Never raises for bad content. A malformed document is data about the corpus, and
    the caller wants all of it at once.
    """

    errors = DocumentErrors(source_path=source_path)

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
    body = match.group("body")

    kind = _kind(front, errors)
    title = _required_str(front, "title", errors)
    source = _required_str(front, "source", errors)
    source_date = _source_date(front, errors)
    sections = _sections(body, errors)

    #: The hierarchy fields are required for subject matter and forbidden-in-practice
    #: for canon. This mirrors the CHECK constraint on `document` (ADR-0091) rather
    #: than replacing it: the database is the guarantee, and this is the half that can
    #: name the file and the field when it fails.
    category = sub_category = None
    scope: DocumentScope | None = None
    if kind is DocumentKind.TOPIC_SOURCE:
        category = _normalized(front, "category", errors, required=True)
        sub_category = _normalized(front, "sub_category", errors, required=False)
        scope = _scope(front, errors)
    elif "category" in front or "scope" in front:
        errors.problems.append(
            "spoin_canon must not carry `category` or `scope` — canon sits outside the "
            "subject hierarchy (ADR-0091)"
        )

    topic_tags = _topic_tags(front, errors, required=kind is DocumentKind.TOPIC_SOURCE)

    if errors or kind is None or title is None or source is None:
        return None, errors

    return (
        ParsedDocument(
            source_path=source_path,
            content_hash=content_hash(raw),
            title=title,
            kind=kind,
            source=source,
            category=category,
            sub_category=sub_category,
            scope=scope,
            source_date=source_date,
            topic_tags=topic_tags,
            sections=sections,
        ),
        errors,
    )


def _required_str(front: dict[str, Any], key: str, errors: DocumentErrors) -> str | None:
    value = front.get(key)
    if value is None:
        errors.problems.append(
            f"`{key}` is missing (required by the contract, NOT NULL in the schema)"
        )
        return None
    if not isinstance(value, str) or not value.strip():
        errors.problems.append(f"`{key}` must be a non-empty string, got {value!r}")
        return None
    return value.strip()


def _normalized(
    front: dict[str, Any], key: str, errors: DocumentErrors, *, required: bool
) -> str | None:
    """Read a hierarchy field and normalize it the way `topic_tags` are normalized.

    One normalizer across tags, `category` and `sub_category` (ADR-0091) is what stops
    "Computer Science" and "computer-science" becoming two categories in the column the
    authoring procedure reads back to offer the owner real options.
    """

    if key not in front:
        if required:
            errors.problems.append(f"`{key}` is required for topic_source documents (ADR-0091)")
        return None
    value = front[key]
    if not isinstance(value, str) or not value.strip():
        errors.problems.append(f"`{key}` must be a non-empty string, got {value!r}")
        return None
    return normalize_topic_text(value)


def _kind(front: dict[str, Any], errors: DocumentErrors) -> DocumentKind | None:
    raw = front.get("kind")
    if raw is None:
        errors.problems.append(
            "`kind` is missing (must be exactly `spoin_canon` or `topic_source`)"
        )
        return None
    try:
        return DocumentKind(raw)
    except ValueError:
        errors.problems.append(
            f"`kind` must be exactly `spoin_canon` or `topic_source`, got {raw!r} — "
            "a typo here would otherwise be a silent third kind nothing retrieves (ADR-0088)"
        )
        return None


def _scope(front: dict[str, Any], errors: DocumentErrors) -> DocumentScope | None:
    raw = front.get("scope")
    if raw is None:
        errors.problems.append(
            "`scope` is required for topic_source documents (`survey` or `topic`)"
        )
        return None
    try:
        return DocumentScope(raw)
    except ValueError:
        errors.problems.append(f"`scope` must be `survey` or `topic`, got {raw!r}")
        return None


def _source_date(front: dict[str, Any], errors: DocumentErrors) -> datetime | None:
    raw = front.get("source_date")
    if raw is None:
        return None

    #: PyYAML resolves an unquoted `2026-08-01` to a `date` and `2024` to an `int`
    #: before we see it, so all three accepted forms arrive as different Python types.
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, int):
        raw = str(raw)
    if not isinstance(raw, str):
        # `datetime.date`, the common case for a full `YYYY-MM-DD`.
        raw = str(raw)

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    errors.problems.append(f"`source_date` must be YYYY-MM-DD, YYYY-MM or YYYY, got {raw!r}")
    return None


def _topic_tags(front: dict[str, Any], errors: DocumentErrors, *, required: bool) -> list[str]:
    raw = front.get("topic_tags")
    if raw is None:
        if required:
            errors.problems.append("`topic_tags` is required for topic_source documents")
        return []
    if not isinstance(raw, list):
        errors.problems.append(f"`topic_tags` must be a list, got {type(raw).__name__}")
        return []

    tags: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            errors.problems.append(f"`topic_tags` entries must be strings, got {entry!r}")
            continue
        normalized = normalize_topic_text(entry)
        if normalized and normalized not in tags:
            tags.append(normalized)
    return tags


def _sections(body: str, errors: DocumentErrors) -> list[ParsedSection]:
    """Split the body on `##` headings.

    **Text before the first `##` fails the document.** That is a deliberate hard error
    rather than a warning or a silent drop (owner's decision, 2026-09-05): a chunk is
    retrieved and shown to a model without its neighbours, so an opening paragraph that
    belongs to no section is either lost silently or smuggled into a chunk it does not
    describe. An H1 title line is the one exception — it duplicates front-matter
    `title`, which the contextual header already puts on every chunk.
    """

    matches = list(_SECTION.finditer(body))
    if not matches:
        errors.problems.append("no `##` sections — the ingester chunks on `##` headings")
        return []

    preamble = body[: matches[0].start()]
    stripped = "\n".join(
        line for line in preamble.splitlines() if not line.lstrip().startswith("# ")
    ).strip()
    if stripped:
        preview = stripped[:80].replace("\n", " ")
        errors.problems.append(
            f"{len(stripped)} characters of prose before the first `##` heading "
            f"({preview!r}...) — every chunk must belong to a section, so move this "
            "into a section or delete it"
        )

    sections: list[ParsedSection] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        heading = match.group("heading").strip()
        text = body[match.end() : end].strip()
        if not text:
            errors.problems.append(f"section {heading!r} has no body")
            continue
        if len(text) > MAX_SECTION_CHARS:
            #: Nothing splits this for the author. A 1385-token section becomes one
            #: 1385-token chunk that wins a retrieval slot and then spends a third of
            #: the prompt budget (ADR-0089) on material only partly about the query.
            errors.problems.append(
                f"section {heading!r} is {len(text)} characters, over the "
                f"{MAX_SECTION_CHARS} limit (~512 tokens) — one section is one chunk and "
                "nothing splits it for you, so break this into two or more `##` sections, "
                "each self-contained"
            )
            continue
        sections.append(ParsedSection(heading=heading, text=text))
    return sections
