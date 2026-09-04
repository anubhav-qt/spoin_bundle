"""The corpus database's connection settings refuse to guess.

This is the executable half of ADR-0088's central safety claim. The ADR says a
universe migration cannot land on `spoin_db_2` because frog's environment never reads
`SPOIN_DATABASE_URL`. That is only true for as long as nobody adds a helpful fallback,
and "helpful fallback" is exactly the shape of change that looks harmless in review.
"""

from __future__ import annotations

import pytest

from frog.universe.config import UniverseSettings, get_universe_settings, universe_url


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_universe_settings.cache_clear()


def test_it_reads_its_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SPOIN_UNIVERSE_DATABASE_URL",
        "postgresql+asyncpg://spoin:spoin@db:5432/the_spoin_universe",
    )
    assert universe_url().endswith("/the_spoin_universe")


def test_it_does_not_fall_back_to_the_production_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole decision, as a test.

    `SPOIN_DATABASE_URL` is set here and points at production, exactly as it does in
    every container this code runs in. Nothing may reach for it.
    """

    monkeypatch.delenv("SPOIN_UNIVERSE_DATABASE_URL", raising=False)
    monkeypatch.setenv("SPOIN_DATABASE_URL", "postgresql+asyncpg://spoin:spoin@db:5432/spoin_db_2")

    with pytest.raises(RuntimeError, match="SPOIN_UNIVERSE_DATABASE_URL"):
        universe_url()


def test_the_settings_object_has_no_field_that_could_hold_the_production_url() -> None:
    """Belt and braces: `extra="ignore"` means an unexpected `SPOIN_*` variable is
    dropped rather than bound, but a future field named `database_url` would bind
    `SPOIN_DATABASE_URL` under the `SPOIN_` prefix and reintroduce the fallback
    without anyone writing the word "fallback".
    """

    assert set(UniverseSettings.model_fields) == {"universe_database_url"}
