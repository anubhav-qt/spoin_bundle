"""Connection settings for `the_spoin_universe`.

ADR-0088: this reads **`SPOIN_UNIVERSE_DATABASE_URL` and nothing else**. That is the
structural half of the decision, not a stylistic one — a universe migration cannot
land on `spoin_db_2` because the environment that runs it never reads the variable
that names `spoin_db_2`.

Do not add a fallback to `SPOIN_DATABASE_URL` here. A convenience default is exactly
how a migration ends up on the wrong database, and this project has paid for that
class of mistake four times in a neighbouring form (CLAUDE.md).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class UniverseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPOIN_", extra="ignore")

    #: Async URL for `the_spoin_universe`. Optional at construction so that
    #: importing frog in an environment that has no corpus database — the API's
    #: own test suite, for one — does not explode at import time. Read it through
    #: `universe_url()`, which fails loudly at the point of actual use.
    universe_database_url: str | None = None


@lru_cache
def get_universe_settings() -> UniverseSettings:
    return UniverseSettings()


def universe_url() -> str:
    """The universe connection string, or a loud failure naming the variable.

    Deliberately not a silent fallback to `SPOIN_DATABASE_URL` — see the module
    docstring. An unset corpus database should stop the caller, not redirect it at
    production.
    """

    url = get_universe_settings().universe_database_url
    if not url:
        raise RuntimeError(
            "SPOIN_UNIVERSE_DATABASE_URL is not set. frog talks to "
            "`the_spoin_universe` only (ADR-0088); it will not fall back to "
            "SPOIN_DATABASE_URL."
        )
    return url
