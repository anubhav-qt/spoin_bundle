"""Executable versions of the hard rules in docs/architecture/overview.md.

Documented rules rot silently; a failing CI check does not. That asymmetry is the
whole argument for this file — it is the enforcement half of the DX section in the
repo README, applied to architecture rather than to style.
"""

from __future__ import annotations

import ast
import pathlib

import frog
import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "spoin"

#: ADR-0087. frog is a sibling package; the dependency runs api -> frog only.
#:
#: Located by importing it rather than by walking up from this file: the suite runs
#: both from the repo (apps/api/tests) and inside the image (/app/tests), and a
#: relative path that is right in one is an IndexError in the other. Importing also
#: means this checks the frog that is actually installed, not a directory that
#: happens to sit nearby.
FROG_SRC = pathlib.Path(frog.__file__).resolve().parent

#: Hard rule 3 / ADR-0002. The one module allowed to import LangChain.
LANGCHAIN_MODULE = SRC / "generation" / "langchain_impl.py"

#: Hard rule 1. Nothing these modules import may reach a model.
READ_PATH = [SRC / "feed", SRC / "api" / "routers" / "feed.py"]

LLM_MARKERS = (
    "langchain",
    "google.generativeai",
    # The old SDK (`google.generativeai`, above) and the current one
    # `langchain-google-genai` actually depends on (`google.genai`, ADR-0002's
    # langchain_impl.py) -- both listed since either could show up depending
    # on which SDK generation is wired to at the time.
    "google.genai",
    "openai",
    "anthropic",
    "spoin.generation",
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

    from spoin.generation.base import ContentGenerator

    assert not hasattr(ContentGenerator, "generate_card")
    assert hasattr(ContentGenerator, "generate_cards")
    assert hasattr(ContentGenerator, "correct_cards")
    assert hasattr(ContentGenerator, "verify_cards")


def test_stream_topic_answer_is_the_only_single_item_generation_method() -> None:
    """ADR-0077: `stream_topic_answer` is a deliberate, documented exception to
    ADR-0005's collection rule -- streaming forces one item, and a streamed
    turn is exactly one request. Every OTHER LLM-facing method still takes a
    collection. This pins the exception so a second single-item method can't
    slip in unnoticed."""

    import inspect

    from spoin.generation.base import ContentGenerator

    # Not LLM calls: the key-claim context manager and the streaming exception.
    allowed_non_collection = {"claimed_key_scope", "stream_topic_answer"}
    offenders: list[str] = []
    for name, member in inspect.getmembers(ContentGenerator):
        if name.startswith("_") or not getattr(member, "__isabstractmethod__", False):
            continue
        if name in allowed_non_collection:
            continue
        params = list(inspect.signature(member).parameters.values())[1:]  # drop self
        takes_list = any(
            "list[" in str(p.annotation) or "Sequence[" in str(p.annotation) for p in params
        )
        if not takes_list:
            offenders.append(name)
    assert not offenders, (
        f"{offenders} take no collection param. ADR-0005: every LLM-facing method takes a "
        "collection; the only sanctioned exception is stream_card_answer (ADR-0077)."
    )


def test_difficulty_mix_is_config_not_code() -> None:
    """content-model.md: the percentages will be tuned against engagement data,
    and tuning must not require a deploy."""

    from spoin.core.config import DIFFICULTY_MIX
    from spoin.domain.enums import Difficulty

    for tier, mix in DIFFICULTY_MIX.items():
        assert abs(sum(mix.values()) - 1.0) < 1e-9, f"{tier} mix must sum to 1"

    # Every non-advanced tier keeps an upward slice — it is the promotion signal.
    assert DIFFICULTY_MIX[Difficulty.BEGINNER][Difficulty.INTERMEDIATE] > 0
    assert DIFFICULTY_MIX[Difficulty.INTERMEDIATE][Difficulty.ADVANCED] > 0


def test_pool_thresholds_have_a_gap() -> None:
    """ADR-0006 §3: one threshold flaps. The gap is what makes the state stable."""

    from spoin.core.config import Settings

    assert Settings().pool_thresholds_are_sane


def test_imported_font_reads_are_scoped_to_the_owner() -> None:
    """ADR-0070: `user_font` is the first per-user binary the API serves. Every
    function in `profile/preferences.py` that touches `UserFont` must also
    constrain it by `UserFont.user_id` — a stranger's font id is a 404, never a
    served blob. Enforced here as well as by the router dependency, the same
    twice-enforced shape as hard rule 1.
    """

    path = SRC / "profile" / "preferences.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def _queries_user_font(node: ast.AST) -> bool:
        """A `select(UserFont ...)` call — a read. Constructing `UserFont(...)`
        to insert a row is not one, and does not need an owner filter."""
        for n in ast.walk(node):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id in {"select", "delete", "update"}
                and any(isinstance(a, ast.Name) and a.id == "UserFont" for a in n.args)
            ):
                return True
        return False

    def _filters_by_owner(node: ast.AST) -> bool:
        return any(
            isinstance(n, ast.Attribute)
            and n.attr == "user_id"
            and isinstance(n.value, ast.Name)
            and n.value.id == "UserFont"
            for n in ast.walk(node)
        )

    offenders = [
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef)
        and _queries_user_font(fn)
        and not _filters_by_owner(fn)
    ]
    assert not offenders, (
        f"{offenders} in profile/preferences.py query UserFont without a "
        "UserFont.user_id filter — an imported font must never be readable by "
        "another user (ADR-0070)."
    )


def test_the_generation_pipeline_holds_no_global_concurrency_cap() -> None:
    """ADR-0047 removed a global `asyncio.Semaphore(5)` that had been throttling
    a 33-key pool down to five calls at a time, and ADR-0074 committed to not
    bringing one back: what bounds concurrency now is key OWNERSHIP -- one
    subtopic group, one key -- which scales with the pool instead of capping it.

    The failure this guards against is not a bad decision, it is an easy
    reflex. A semaphore is the obvious thing to reach for the next time a run
    looks like it is calling too fast, and the last one survived unnoticed for
    long enough to make a three-topic run take 2.8 hours with the keys 90% idle.
    If a future change genuinely needs a cap, it needs an ADR superseding those
    two, and deleting this test is the visible cost of not writing one.
    """

    pipeline = SRC / "generation" / "pipeline"
    offenders = []
    for path in sorted(pipeline.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("Semaphore", "BoundedSemaphore"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "the generation pipeline reintroduced a global concurrency semaphore at "
        f"{', '.join(offenders)} -- see ADR-0047 and ADR-0074"
    )


def test_questions_are_written_by_the_topic_wide_phase_only() -> None:
    """ADR-0074: a subtopic group's branch writes cards and stops. Questions run
    once, at the fan-in, when every group has finished its cards -- so a tier's
    question budget is spent against the card set it actually ended up with
    rather than against whichever cards survived its first gate round.

    Checked structurally rather than by reading, because the drift is silent:
    moving question generation back into the per-group path would still pass
    every other test in the suite and simply produce questions for a partial
    tier, repeatedly, once per redraft round.
    """

    nodes = SRC / "generation" / "pipeline" / "nodes.py"
    tree = ast.parse(nodes.read_text(encoding="utf-8"))
    # Top-level definitions only: the phase's own nested helper is part of it,
    # and walking every scope would report the inner name as a second caller.
    callers = {
        node.name
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        for inner in ast.walk(node)
        if isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "_run_question_phase"
    }
    assert callers == {"_run_topic_question_phase"}, (
        f"_run_question_phase is called from {sorted(callers)} -- ADR-0074 puts it behind the "
        "topic-wide fan-in phase only"
    )


@pytest.mark.parametrize(
    "path",
    _python_files(FROG_SRC) if FROG_SRC.is_dir() else [],
    ids=lambda p: p.name,
)
def test_frog_never_imports_spoin(path: pathlib.Path) -> None:
    """ADR-0087: the dependency runs one way, `api -> frog`.

    frog owns the embedder and the corpus store, and `spoin` depends on it. If frog
    reached back into `spoin` -- `spoin.core.config` is the tempting one, since
    frog's own settings deliberately do not carry `embedding_dim` -- neither package
    could be built, tested or reasoned about alone, and the sibling layout would be
    decorative.

    Enforced here as well as by frog's `ruff` `banned-api` entry, because a lint rule
    can be bypassed locally and this cannot (CLAUDE.md: a hard architectural rule gets
    enforced twice, never documented once -- the same wiring ADR-0002 uses).
    """

    offenders = {name for name in _imports(path) if name.split(".")[0] == "spoin"}
    assert not offenders, (
        f"{path.relative_to(FROG_SRC)} imports {offenders}. "
        "frog must not import spoin -- the dependency runs api -> frog only (ADR-0087)."
    )


def test_the_frog_boundary_check_is_actually_looking_at_something() -> None:
    """The test above is parametrized over discovered files, and a parametrization
    over an empty list passes silently.

    That is the exact failure mode this project has been bitten by elsewhere: a check
    that reports green because it found nothing to check. If frog moves or the path
    arithmetic drifts, fail here rather than pretending the boundary is enforced.
    """

    assert FROG_SRC.is_dir(), f"frog source not found at {FROG_SRC} (ADR-0087)"
    assert _python_files(FROG_SRC), f"no Python files under {FROG_SRC}"
