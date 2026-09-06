"""`python -m spoin.curriculum` -- project authored curricula into `spoin_db_2`.

Deterministic, no model (docs/architecture/authored-curriculum.md §8). Run after
`make curriculum-ingest` has written the `curriculum` tables in `the_spoin_universe`.
`make curriculum-project` wraps this.

Needs both `SPOIN_DATABASE_URL` and `SPOIN_UNIVERSE_DATABASE_URL`.
"""

from __future__ import annotations

import asyncio
import logging

from spoin.core.db import UniverseNotConfiguredError
from spoin.curriculum.projection import project_curricula


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        report = asyncio.run(project_curricula())
    except UniverseNotConfiguredError as exc:
        print(f"error: {exc}")
        return 2
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
