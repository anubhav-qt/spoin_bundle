"""Alembic environment for `the_spoin_universe`.

**This environment reads `SPOIN_UNIVERSE_DATABASE_URL` and nothing else.** That is
the point of ADR-0088's choice to put a second alembic environment here rather than
alongside the API's: a universe migration cannot land on `spoin_db_2`, because the
code that runs it never reads the variable that names `spoin_db_2`. This is a
structural guarantee, not a convention — do not add a fallback.

Structurally the same as `apps/api/alembic/env.py`: async engine, URL from settings
rather than from alembic.ini so there is exactly one place a connection string lives.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from frog.universe.base import Base
from frog.universe.config import universe_url

# Importing the package registers every model on Base.metadata. Without this,
# autogenerate produces an empty migration and nobody notices until deploy.
import frog.universe.models  # noqa: F401  isort:skip

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", universe_url())
target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=universe_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_run)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
