"""Walking the authored curricula: validating them, and ingesting the valid ones.

Two halves, deliberately separable:

- `validate_curricula` is pure -- no database -- and adds the one check
  `parse_curriculum` cannot do alone: **every `grounding` reference must name a real
  `##` section of a real corpus document**. This is what `make curriculum-check` runs.
- `ingest_curricula` writes the valid ones into `the_spoin_universe`, idempotent by
  content hash exactly as the corpus ingester is (ADR-0088). This is what
  `make curriculum-ingest` runs.

A failing file never stops the others: the curricula are authored by a track still
writing them, and a failure is a work item to hand back, not a crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import get_close_matches
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from frog.curriculum.contract import (
    CurriculumErrors,
    ParsedCurriculum,
    parse_curriculum,
    split_grounding_ref,
)
from frog.curriculum.models import Curriculum, CurriculumSubtopic
from frog.ingest.contract import parse_document

#: One file per topic: `docs/the_spoin_universe/curricula/<topic>/curriculum.md`. The
#: directory name is the author's slug for the topic; the canonical name is the
#: front-matter `topic` field.
_CURRICULUM_GLOB = "*/curriculum.md"


def source_path_of(curricula_root: Path, path: Path) -> str:
    """The curriculum's identity: its path within the curricula tree, POSIX-separated.

    Forward slashes because this becomes a database key in task 2 and the tree is
    authored on one OS and ingested on another (same reasoning as
    `frog.ingest.runner.source_path_of`).
    """

    return path.relative_to(curricula_root).as_posix()


def validate_curricula(
    curricula_root: Path, corpus_root: Path
) -> tuple[list[ParsedCurriculum], list[CurriculumErrors]]:
    """Validate every curriculum without touching a database.

    Returns the ones that passed and, separately, the failures -- one
    `CurriculumErrors` per failing file, carrying every problem in it. A failing file
    never stops the others: the corpus is authored by a track still writing it, and a
    failure is a work item to hand back, not a crash.
    """

    passed: list[ParsedCurriculum] = []
    failures: list[CurriculumErrors] = []
    #: Shared across every file in the run -- see `_document_headings`.
    heading_cache: dict[str, list[str] | None] = {}

    for path in sorted(curricula_root.glob(_CURRICULUM_GLOB)):
        source_path = source_path_of(curricula_root, path)
        curriculum, errors = parse_curriculum(source_path, path.read_bytes())

        if curriculum is not None:
            _check_grounding_exists(curriculum, corpus_root, errors, heading_cache)

        if curriculum is None or errors:
            failures.append(errors)
        else:
            passed.append(curriculum)

    return passed, failures


def _check_grounding_exists(
    curriculum: ParsedCurriculum,
    corpus_root: Path,
    errors: CurriculumErrors,
    cache: dict[str, list[str] | None],
) -> None:
    """Every `grounding` reference must name a real `##` section of a real document.

    Checked against `frog.ingest.contract.parse_document` -- the SAME parser the
    ingester chunks with -- rather than by searching the file for the heading text.
    That matters twice: a substring search passes `#Foo` against a document whose only
    heading is `## Foobar`, and it would happily match a `##` line inside a fenced code
    block that never becomes a chunk. Agreeing with the chunker is the whole point: a
    reference that validates here must resolve to a row after ingestion.

    A document that does not satisfy the corpus contract is reported as exactly that,
    not as a missing heading -- the author's next move is different in each case.
    """

    for subtopic in curriculum.subtopics:
        for tier in subtopic.tiers:
            where = f"subtopic {subtopic.title!r}, tier {tier.tier!r}"
            for ref in tier.grounding:
                split = split_grounding_ref(ref)
                if split is None:  # pragma: no cover - shape is checked in the contract
                    continue
                path, heading = split
                headings = _document_headings(corpus_root, path, cache)
                if headings is None:
                    errors.add(
                        f"{where}: grounding document {path!r} does not exist under "
                        f"{corpus_root.as_posix()}, or does not satisfy the corpus "
                        "contract (run `make corpus-check`)"
                    )
                    continue
                if heading not in headings:
                    errors.add(
                        f"{where}: {path} has no `## {heading}` section"
                        + _did_you_mean(heading, headings)
                    )


def _document_headings(
    corpus_root: Path, path: str, cache: dict[str, list[str] | None]
) -> list[str] | None:
    """Section headings of one corpus document, or None if it cannot be read.

    Cached across the whole run: a tier names several sections of one document and
    several tiers name the same document, so without this a ten-subtopic curriculum
    re-parses the same files a hundred times.
    """

    if path in cache:
        return cache[path]
    document_path = corpus_root / path
    headings: list[str] | None = None
    if document_path.is_file():
        parsed, _errors = parse_document(path, document_path.read_bytes())
        if parsed is not None:
            headings = [section.heading for section in parsed.sections]
    cache[path] = headings
    return headings


def _did_you_mean(heading: str, candidates: list[str]) -> str:
    """The closest real heading, when there is one close enough to be the intent.

    These references are long, exact strings copied by hand out of a document -- the
    overwhelmingly likely failure is a truncation or a typo, not an invented section.
    Naming the near miss turns a delivery round-trip into a one-line fix.
    """

    match = get_close_matches(heading, candidates, n=1, cutoff=0.6)
    return f" -- did you mean {match[0]!r}?" if match else ""


@dataclass
class CurriculumIngestReport:
    """What one ingestion run did, in counts a human can check against the tree.

    `failed` and `unchanged` are separate fields and neither is folded into the other
    (CLAUDE.md): a clean idempotent re-run and a validation failure are different
    facts, and reporting them as one number makes the first look like the second.
    """

    scanned: int = 0
    ingested: int = 0
    unchanged: int = 0
    failed: int = 0
    errors: list[CurriculumErrors] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return self.failed > 0

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} ingested={self.ingested} "
            f"unchanged={self.unchanged} failed={self.failed}"
        )


async def ingest_curriculum(session: AsyncSession, parsed: ParsedCurriculum) -> bool:
    """Write one curriculum and its subtopics. Returns True if it changed anything.

    Returns False and touches nothing when the hash is unchanged -- the idempotency
    requirement (ADR-0088), a hash comparison rather than a delete-and-reinsert that
    only comes out even by row count. The caller owns the transaction.
    """

    existing = (
        await session.execute(
            select(Curriculum).where(Curriculum.source_path == parsed.source_path)
        )
    ).scalar_one_or_none()

    if existing is not None and existing.content_hash == parsed.content_hash:
        return False

    if existing is None:
        curriculum = Curriculum(source_path=parsed.source_path)
        session.add(curriculum)
    else:
        curriculum = existing
        #: A revision keeps the curriculum row (and its id) and replaces only its
        #: subtopics, exactly as a document revision replaces only its chunks.
        await session.execute(
            delete(CurriculumSubtopic).where(CurriculumSubtopic.curriculum_id == curriculum.id)
        )

    curriculum.content_hash = parsed.content_hash
    curriculum.topic_name = parsed.topic
    curriculum.description = parsed.description
    curriculum.is_survey = parsed.is_survey
    curriculum.ingested_at = datetime.now(UTC)
    await session.flush()

    for ordinal, subtopic in enumerate(parsed.subtopics):
        session.add(
            CurriculumSubtopic(
                curriculum_id=curriculum.id,
                ordinal=ordinal,
                title=subtopic.title,
                description=subtopic.description,
                prerequisites=list(subtopic.prerequisites),
                source_paths=list(subtopic.source_paths),
                tiers={
                    tier.tier: {
                        "target_cards": tier.target_cards,
                        "card_types": dict(tier.card_types),
                        "grounding": list(tier.grounding),
                    }
                    for tier in subtopic.tiers
                },
            )
        )
    return True


async def ingest_curricula(
    session: AsyncSession, curricula_root: Path, corpus_root: Path
) -> CurriculumIngestReport:
    """Validate every curriculum, then ingest the ones that passed.

    Validation runs over everything before anything is written, and a failing file is
    a list item to hand back rather than a stop -- the same posture the corpus
    ingester takes for a corpus its authoring track is still writing.
    """

    passed, failures = validate_curricula(curricula_root, corpus_root)
    report = CurriculumIngestReport(
        scanned=len(passed) + len(failures),
        failed=len(failures),
        errors=failures,
    )

    for curriculum in passed:
        if await ingest_curriculum(session, curriculum):
            report.ingested += 1
        else:
            report.unchanged += 1

    return report
