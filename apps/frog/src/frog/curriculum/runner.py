"""Walking the authored curricula: validating them, and ingesting the valid ones.

Two halves, deliberately separable:

- `validate_curricula` is pure -- no database -- and adds the one check
  `parse_curriculum` cannot do alone: **every `sources` path in every subtopic must
  exist under the corpus tree**. This is what `make curriculum-check` runs.
- `ingest_curricula` writes the valid ones into `the_spoin_universe`, idempotent by
  content hash exactly as the corpus ingester is (ADR-0088). This is what
  `make curriculum-ingest` runs.

A failing file never stops the others: the curricula are authored by a track still
writing them, and a failure is a work item to hand back, not a crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from frog.curriculum.contract import CurriculumErrors, ParsedCurriculum, parse_curriculum
from frog.curriculum.models import Curriculum, CurriculumSubtopic

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

    for path in sorted(curricula_root.glob(_CURRICULUM_GLOB)):
        source_path = source_path_of(curricula_root, path)
        curriculum, errors = parse_curriculum(source_path, path.read_bytes())

        if curriculum is not None:
            _check_sources_exist(curriculum, corpus_root, errors)

        if curriculum is None or errors:
            failures.append(errors)
        else:
            passed.append(curriculum)

    return passed, failures


def _check_sources_exist(
    curriculum: ParsedCurriculum, corpus_root: Path, errors: CurriculumErrors
) -> None:
    """Every `sources` path must resolve to a file under `corpus_root`.

    A path listed because it merely mentions the term makes card grounding worse, not
    better (the contract), so a typo pointing at nothing is worth catching here rather
    than discovering it as an empty retrieval during a generation run.
    """

    for subtopic in curriculum.subtopics:
        for source in subtopic.sources:
            if not (corpus_root / source).is_file():
                errors.add(
                    f"subtopic {subtopic.title!r}: source {source!r} does not exist under "
                    f"{corpus_root.as_posix()}"
                )


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
                source_paths=list(subtopic.sources),
                tiers={
                    tier.tier: {
                        "target_cards": tier.target_cards,
                        "card_types": dict(tier.card_types),
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
