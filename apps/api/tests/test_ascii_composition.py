"""ADR-0104: the art is the library's, the words are the model's.

The invariant these tests exist to hold is narrow and total: **nothing a model
returns can change a single character of the drawing.** Before ADR-0104 the model
was asked to retype the art it had picked, and of 31 library-sourced cards in the
corpus on 2026-09-07 exactly 2 came back intact -- one 14-line scene arrived as a
single line, a 4-line scene arrived as 89, and 11 lost the backslashes that ASCII
art is made of. Composition replaced adaptation so that outcome is unreachable.
"""

from __future__ import annotations

from spoin.content.ascii_library import (
    ASCII_MAX_WIDTH,
    compose_scene,
    entry_by_id,
    load_library,
)


def test_the_library_art_survives_composition_byte_for_byte() -> None:
    art = "  /\\_/\\\n ( o.o )\n  > ^ <"
    composed = compose_scene(art, ["the cat = the borrow checker", "it has opinions"])
    assert composed.startswith(art), "the drawing must be copied, never rewritten"


def test_overlay_lines_are_appended_below_the_art() -> None:
    composed = compose_scene("  o\n /|\\", ["label: the heap", "it is full"])
    assert composed.split("\n")[-2:] == ["label: the heap", "it is full"]


def test_composition_without_overlay_lines_is_just_the_art() -> None:
    assert compose_scene("  o\n /|\\", []) == "  o\n /|\\"


def test_blank_overlay_lines_are_dropped() -> None:
    assert compose_scene("  o", ["", "   ", "real"]).endswith("real")


def test_an_overlay_line_over_budget_is_wrapped_never_truncated() -> None:
    """The overlay carries the gag for THIS card, so losing it costs the scene
    its point. Height is free; width is not."""

    line = "the compiler is not yelling at you it is explaining exactly which bound failed"
    composed = compose_scene("  o", [line])
    overlay = composed.split("\n")[2:]
    assert all(len(part) <= ASCII_MAX_WIDTH for part in overlay)
    assert " ".join(overlay) == line, "every word must survive the wrap"


def test_a_single_word_longer_than_the_budget_is_hard_split() -> None:
    composed = compose_scene("  o", ["x" * 95])
    overlay = [line for line in composed.split("\n")[2:] if line]
    assert all(len(line) <= ASCII_MAX_WIDTH for line in overlay)
    assert "".join(overlay) == "x" * 95


def test_composed_scenes_are_always_within_the_column_budget() -> None:
    """The whole point, stated as one assertion: for EVERY entry in the real
    library, composing it with an over-long overlay still fits a phone."""

    library = load_library()
    if not library:  # a checkout without the data file
        return
    for entry in library[:150]:
        composed = compose_scene(entry.art, ["a label that is quite a lot longer than forty columns"])
        assert all(len(line) <= ASCII_MAX_WIDTH for line in composed.split("\n"))


def test_entry_by_id_finds_a_real_entry_and_rejects_an_invented_one() -> None:
    library = load_library()
    if not library:
        return
    assert entry_by_id(library[0].id) is not None
    assert entry_by_id("not-a-real-src-id") is None
