"""content/ascii_library.py -- the curated-library retrieval behind Task 0029.

No mocking needed: `load_library` reads the real packaged copy of the curated
files, and the default test settings resolve `get_embedder()` to `HashEmbedder`
(deterministic, no network, no model download) -- see core/config.py's
`embedder: EmbedderBackend = "hash"` default. Similarity here is NOT
semantically meaningful with the hash embedder (see its own docstring); these
tests check the plumbing -- parsing, shape, ranking is a real ordering, empty-
input handling -- not "does this specific query return this specific art".
Semantic quality is a fastembed-backend question, exercised manually per
Task 0029's own note, not something to assert against in CI.
"""

from __future__ import annotations

from spoin.content.ascii_library import AsciiLibraryEntry, load_library, top_candidates


def test_library_loads_real_curated_entries() -> None:
    library = load_library()
    # Matches the counts documented in ADR-0068 / apps/helpers/README.md
    # (888 + 1599 = 2,487) -- a large drop here would mean the packaged copy
    # under content/ascii_library_data/ has drifted from the curation source.
    assert len(library) > 2000
    assert all(isinstance(e, AsciiLibraryEntry) for e in library)


def test_every_entry_has_a_title_and_art() -> None:
    for entry in load_library():
        assert entry.title.strip() != ""
        assert entry.art.strip() != ""


def test_every_entry_respects_the_40_column_budget() -> None:
    # The same invariant _ASCII_MAX_WIDTH enforces on generated art -- the
    # curated library is supposed to already satisfy it (ADR-0068), and this
    # is the check that would catch a bad sync from apps/helpers/ silently
    # violating it.
    over_budget = [
        (entry.id, line)
        for entry in load_library()
        for line in entry.art.split("\n")
        if len(line) > 40
    ]
    assert over_budget == []


def test_library_is_cached_across_calls() -> None:
    assert load_library() is load_library()


async def test_top_candidates_returns_requested_count() -> None:
    results = await top_candidates("a person standing", k=5)
    assert len(results) == 5


async def test_top_candidates_returns_fewer_if_k_exceeds_library_size() -> None:
    total = len(load_library())
    results = await top_candidates("anything", k=total + 1000)
    assert len(results) == total


async def test_top_candidates_empty_query_returns_nothing() -> None:
    assert await top_candidates("", k=10) == []
    assert await top_candidates("   ", k=10) == []


async def test_top_candidates_ranking_is_a_real_ordering_not_arbitrary() -> None:
    # Not a semantic-quality assertion (see module docstring) -- just that the
    # same query deterministically returns the same order twice, which is what
    # "ranking by score" actually requires of the plumbing.
    first = await top_candidates("a small robot", k=10)
    second = await top_candidates("a small robot", k=10)
    assert [e.id for e in first] == [e.id for e in second]


async def test_top_candidates_zero_k_returns_empty() -> None:
    assert await top_candidates("anything", k=0) == []
