"""`python -m frog.curriculum` -- validate authored curricula, or ingest them.

    python -m frog.curriculum --check     # validate against the contract; writes nothing,
                                          # no database, no model. `make curriculum-check`.
    python -m frog.curriculum             # validate, then ingest the valid ones into
                                          # the_spoin_universe. `make curriculum-ingest`.

`--check` is the half the curriculum-authoring track runs while writing -- pure, and it
mirrors `python -m frog.ingest --check`. The bare form additionally writes the
`curriculum` / `curriculum_subtopic` tables, idempotent by content hash (ADR-0088).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from frog.curriculum.contract import CurriculumErrors
from frog.curriculum.runner import ingest_curricula, validate_curricula
from frog.universe.config import universe_url

#: Both relative to the repository root -- the working directory of the `frog` compose
#: service, which is where `make curriculum-check` / `make curriculum-ingest` run this.
DEFAULT_CURRICULA = Path("docs/the_spoin_universe/curricula")
DEFAULT_CORPUS = Path("docs/the_spoin_universe/corpus")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="frog.curriculum", description=__doc__)
    parser.add_argument("--curricula", type=Path, default=DEFAULT_CURRICULA)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate against the contract and exit; writes nothing, loads no database",
    )
    return parser


def _print_failures(failures: list[CurriculumErrors]) -> None:
    """Every problem in every failing file, named by path. A failure is a work item
    handed back to a person, so "validation failed" is not one; the field is."""

    for failure in failures:
        print(f"\nFAIL {failure.source_path}", file=sys.stderr)
        for problem in failure.problems:
            print(f"  - {problem}", file=sys.stderr)


def _check(curricula: Path, corpus: Path) -> int:
    passed, failures = validate_curricula(curricula, corpus)
    _print_failures(failures)
    print(
        f"checked {len(passed) + len(failures)} curricula: "
        f"{len(passed)} ok, {len(failures)} failing"
    )
    return 1 if failures else 0


async def _ingest(curricula: Path, corpus: Path) -> int:
    engine = create_async_engine(universe_url())
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            #: One transaction for the whole run, like the corpus ingester: a
            #: curriculum's subtopics are deleted and rebuilt, and a crash mid-run
            #: must not leave a curriculum whose hash claims it is current while its
            #: subtopics are gone.
            report = await ingest_curricula(session, curricula, corpus)
            await session.commit()
    finally:
        await engine.dispose()

    _print_failures(report.errors)
    print(report.summary())
    return 1 if report.has_failures else 0


def main() -> int:
    args = build_parser().parse_args()

    curricula: Path = args.curricula
    if not curricula.is_dir():
        #: No curricula authored yet is a valid state, not an error.
        print(f"no curricula directory at {curricula}: nothing to do")
        return 0

    corpus: Path = args.corpus
    if not corpus.is_dir():
        print(f"corpus not found: {corpus} (needed to check `sources` paths)", file=sys.stderr)
        return 2

    if args.check:
        return _check(curricula, corpus)
    return asyncio.run(_ingest(curricula, corpus))


if __name__ == "__main__":
    raise SystemExit(main())
