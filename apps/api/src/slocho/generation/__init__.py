"""Which `ContentGenerator` backs a given run — settings-driven, per ADR-0002/0008."""

from __future__ import annotations

from functools import lru_cache

from slocho.core.config import get_settings
from slocho.generation.base import ContentGenerator
from slocho.generation.fake import FakeContentGenerator


@lru_cache
def get_content_generator() -> ContentGenerator:
    settings = get_settings()
    if settings.generator == "fake":
        return FakeContentGenerator()
    if settings.generator == "gemini":
        # Imported lazily, INSIDE this branch, not at module top-level: langchain*
        # is an optional extra (ADR-0002), and this module is imported by anything
        # that touches generation at all. A top-level import here would mean
        # `import slocho.generation` fails without the `generation` extra
        # installed even when someone only wants SLOCHO_GENERATOR=fake — breaking
        # the "clone and run in under 10 minutes, no API key" promise.
        from slocho.generation.langchain_impl import GeminiContentGenerator

        return GeminiContentGenerator(settings)
    if settings.generator == "local":
        raise NotImplementedError(
            "SLOCHO_GENERATOR=local has no implementation yet (ADR-0008). "
            "Use SLOCHO_GENERATOR=fake until it lands."
        )
    raise ValueError(f"Unknown generator backend: {settings.generator!r}")


__all__ = ["get_content_generator"]
