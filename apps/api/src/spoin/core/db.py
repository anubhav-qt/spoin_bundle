"""Async engine and session management.

**Two databases, and they are not peers.** `spoin_db_2` is the application's, read and
written everywhere below. `the_spoin_universe` (ADR-0088) is the corpus, and from this
process it is **read-only** — its writer is the `frog` compose service, which is the
only image carrying a GPU (ADR-0092). The read-only-ness is enforced on the engine
rather than asked for in review; see `get_universe_engine`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from spoin.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        # Neon's free tier caps connections tightly, and the API is IO-bound on
        # Postgres rather than CPU-bound, so a small pool with overflow beats a
        # large one that exhausts the server's limit.
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. One session per request, committed by the caller."""

    async with get_sessionmaker()() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """For workers and scripts, which have no request to hang a session off."""

    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class UniverseNotConfiguredError(RuntimeError):
    """`SPOIN_UNIVERSE_DATABASE_URL` is unset, so there is no corpus to read.

    Its own class because grounding has to tell two outcomes apart that a bare `None`
    would fold together: a corpus that was searched and had nothing relevant, and a
    corpus that was never reachable. CLAUDE.md's rule — a failed outcome and a rejected
    outcome are never the same number — and here it decides whether a run of ungrounded
    cards is a thin corpus or a missing environment variable.
    """


@lru_cache
def get_universe_engine() -> AsyncEngine:
    """The corpus database's engine, opened READ-ONLY.

    `postgresql_readonly` puts every transaction this engine opens into
    `READ ONLY`, so a stray write raises in Postgres rather than depending on nobody
    calling `commit()`. That is deliberate belt-and-braces on a fourth database that
    shares `db-data` with production: this process has no legitimate reason to write
    the corpus, and CLAUDE.md's standing prohibition is worth a guard that does not
    rely on a reviewer noticing.

    A small pool: retrieval is once per subtopic group (`generation.grounding`), not
    once per card, so this is a low-traffic connection.
    """

    settings = get_settings()
    if not settings.universe_database_url:
        raise UniverseNotConfiguredError(
            "SPOIN_UNIVERSE_DATABASE_URL is not set, so `the_spoin_universe` cannot be "
            "read. Generation runs ungrounded without it (ADR-0089)."
        )
    return create_async_engine(
        settings.universe_database_url,
        echo=False,
        pool_size=2,
        max_overflow=3,
        pool_pre_ping=True,
        execution_options={"postgresql_readonly": True},
    )


@lru_cache
def get_universe_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_universe_engine(), expire_on_commit=False)


@asynccontextmanager
async def universe_session_scope() -> AsyncIterator[AsyncSession]:
    """A corpus session. Never commits — there is nothing here to commit."""

    async with get_universe_sessionmaker()() as session:
        try:
            yield session
        finally:
            await session.rollback()
