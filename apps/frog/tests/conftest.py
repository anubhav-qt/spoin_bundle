"""Fixtures for frog's database-backed tests.

**Most of frog's suite needs no database** — the embedder, the schema shape and the
whole contract parser are pure. Only ingestion's idempotency does, because what is
under test there is the database's own behaviour: `source_path`'s UNIQUE constraint and
`chunk`'s `ondelete=CASCADE`. CLAUDE.md is explicit that this is the case where the real
Postgres fixture beats a mock, so these tests skip rather than fake when there is no
database to talk to.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from frog.universe.base import Base

#: Its own variable, never `SPOIN_UNIVERSE_DATABASE_URL`. The corpus database is
#: rebuildable, but "rebuildable" is not "safe to drop tables in from a test run" — and
#: reading the production variable here is exactly how a suite ends up recreating the
#: database someone is mid-ingestion into.
TEST_URL_VAR = "SPOIN_UNIVERSE_TEST_DATABASE_URL"


def _test_url() -> str | None:
    """The test database URL, or None when there is no database to test against.

    Hard-errors rather than skips when the name does not end in `_test`, mirroring
    `apps/api/tests/conftest.py`. A skip is the wrong response to a misconfiguration
    that could drop tables in a real database: it stays silent and green.
    """

    url = os.environ.get(TEST_URL_VAR)
    if not url:
        return None
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not name.endswith("_test"):
        raise RuntimeError(
            f"{TEST_URL_VAR} must name a database ending in `_test`, got {name!r}. "
            "This fixture drops and recreates every table it points at."
        )
    return url


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    url = _test_url()
    if url is None:
        pytest.skip(f"{TEST_URL_VAR} is not set")

    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db_session:
            yield db_session
    finally:
        await engine.dispose()
