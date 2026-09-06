"""Which `ContentGenerator` backs a given run — settings-driven, per ADR-0002/0008."""

from __future__ import annotations

from functools import lru_cache

from spoin.core.config import get_settings
from spoin.generation.base import ContentGenerator
from spoin.generation.fake import FakeContentGenerator


@lru_cache
def get_content_generator() -> ContentGenerator:
    settings = get_settings()
    if settings.generator == "fake":
        return FakeContentGenerator()
    if settings.generator == "gemini":
        # Imported lazily, INSIDE this branch, not at module top-level: langchain*
        # is an optional extra (ADR-0002), and this module is imported by anything
        # that touches generation at all. A top-level import here would mean
        # `import spoin.generation` fails without the `generation` extra
        # installed even when someone only wants SPOIN_GENERATOR=fake — breaking
        # the "clone and run in under 10 minutes, no API key" promise.
        from spoin.generation.langchain_impl import GeminiContentGenerator

        return GeminiContentGenerator(settings)
    if settings.generator == "hybrid":
        # ADR-0090: prose on Mistral, verdicts on Gemini. Lazily imported inside the
        # branch for the same reason `gemini` is -- it subclasses the LangChain impl,
        # so importing it at module top-level would make `import spoin.generation`
        # require the `generation` extra even for SPOIN_GENERATOR=fake.
        from spoin.generation.hybrid import HybridContentGenerator

        return HybridContentGenerator(settings)
    if settings.generator == "local":
        raise NotImplementedError(
            "SPOIN_GENERATOR=local has no implementation yet (ADR-0008). "
            "Use SPOIN_GENERATOR=fake until it lands."
        )
    raise ValueError(f"Unknown generator backend: {settings.generator!r}")


__all__ = ["get_content_generator"]
