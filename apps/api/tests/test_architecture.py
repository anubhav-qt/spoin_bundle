"""Executable versions of the hard rules in docs/architecture/overview.md.

Documented rules rot silently; a failing CI check does not. That asymmetry is the
whole argument for this file — it is the enforcement half of the DX section in the
repo README, applied to architecture rather than to style.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "slocho"

#: Hard rule 3 / ADR-0002. The one module allowed to import LangChain.
LANGCHAIN_MODULE = SRC / "generation" / "langchain_impl.py"

#: Hard rule 1. Nothing these modules import may reach a model.
READ_PATH = [SRC / "feed", SRC / "api" / "routers" / "feed.py"]

LLM_MARKERS = (
    "langchain",
    "google.generativeai",
    "google_genai",
    "openai",
    "anthropic",
    "slocho.generation",
)


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _python_files(*roots: pathlib.Path) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in roots:
        files.extend([root] if root.is_file() else sorted(root.rglob("*.py")))
    return files


@pytest.mark.parametrize("path", _python_files(SRC), ids=lambda p: p.name)
def test_only_one_module_imports_langchain(path: pathlib.Path) -> None:
    """ADR-0002: swapping LangChain out later must stay a one-module rewrite.

    It also keeps the "is this a LangChain bug or our bug?" question answerable.
    """

    if path == LANGCHAIN_MODULE:
        return

    offenders = {name for name in _imports(path) if name.split(".")[0].startswith("langchain")}
    assert not offenders, (
        f"{path.relative_to(SRC)} imports {offenders}. "
        "Only generation/langchain_impl.py may import LangChain (ADR-0002)."
    )


@pytest.mark.parametrize("path", _python_files(*READ_PATH), ids=lambda p: p.name)
def test_no_llm_anywhere_in_the_feed_read_path(path: pathlib.Path) -> None:
    """Hard rule 1, the one that determines the whole design.

    A swipe is ~50ms; an LLM call is 2-10 seconds. If this test ever fails, the
    fix is a batch job that precomputes a column — never a faster model.
    """

    offenders = {
        name for name in _imports(path) if any(name.startswith(marker) for marker in LLM_MARKERS)
    }
    assert not offenders, (
        f"{path.relative_to(SRC)} reaches {offenders}. "
        "The feed read path must never touch an LLM (hard rule 1)."
    )


def test_generation_interfaces_take_collections() -> None:
    """ADR-0005: every LLM interface takes a collection, never a single item.

    The free tier meters requests, not tokens. A single-item entrypoint is the
    specific failure that killed the previous attempt at this product, so there is
    no `generate_card` to retrofit later.
    """

    from slocho.generation.base import ContentGenerator

    assert not hasattr(ContentGenerator, "generate_card")
    assert hasattr(ContentGenerator, "generate_cards")
    assert hasattr(ContentGenerator, "judge_difficulty")


def test_difficulty_mix_is_config_not_code() -> None:
    """content-model.md: the percentages will be tuned against engagement data,
    and tuning must not require a deploy."""

    from slocho.core.config import DIFFICULTY_MIX
    from slocho.domain.enums import Difficulty

    for tier, mix in DIFFICULTY_MIX.items():
        assert abs(sum(mix.values()) - 1.0) < 1e-9, f"{tier} mix must sum to 1"

    # Every non-advanced tier keeps an upward slice — it is the promotion signal.
    assert DIFFICULTY_MIX[Difficulty.BEGINNER][Difficulty.INTERMEDIATE] > 0
    assert DIFFICULTY_MIX[Difficulty.INTERMEDIATE][Difficulty.ADVANCED] > 0


def test_pool_thresholds_have_a_gap() -> None:
    """ADR-0006 §3: one threshold flaps. The gap is what makes the state stable."""

    from slocho.core.config import Settings

    assert Settings().pool_thresholds_are_sane
