"""`spoin.content.normalize` — the deterministic body repairs.

Every case here is drawn from a real defect measured in the live corpus on
2026-09-07, not invented: the module exists because 36 cards carried a
JSON-eaten backslash, 9 carried an unparseable fence, and roughly 28 of 49
mermaid diagrams failed to render. The "leaves this alone" tests matter as much
as the repairs -- the first draft of the label quoter fixed the broken diagrams
and silently corrupted four working ones.
"""

from __future__ import annotations

import pytest

from spoin.content.normalize import (
    humanize_canonical_title,
    normalize_card_body,
    normalize_fences,
    quote_mermaid_labels,
    repair_control_escapes,
    strip_editorial_notes,
)

# -- control-character escapes ------------------------------------------------


@pytest.mark.parametrize(
    ("corrupted", "expected"),
    [
        ("$\x0crac{a}{b}$", r"$\frac{a}{b}$"),
        ("$\tan(\theta)$", r"$\tan(\theta)$"),
        ("$M_{\x08eta}$", r"$M_{\beta}$"),
        ("$\rho_{crit}$", r"$\rho_{crit}$"),
        # longest match wins: \textbf, not \text + "bf"
        ("$\textbf{x}$", r"$\textbf{x}$"),
    ],
)
def test_repairs_backslashes_the_json_decoder_ate(corrupted: str, expected: str) -> None:
    assert repair_control_escapes(corrupted) == expected


def test_real_corpus_formula_round_trips() -> None:
    """Verbatim from the card 'Measuring the Universe's Angular Size'."""

    corrupted = "$$d_A = \x0crac{r_s}{\tan(\theta/2)} \text{ (small angles)}$$"
    assert repair_control_escapes(corrupted) == (
        r"$$d_A = \frac{r_s}{\tan(\theta/2)} \text{ (small angles)}$$"
    )


def test_leaves_indentation_inside_a_code_fence_alone() -> None:
    """A tab in a ```python fence is real indentation, not a lost backslash."""

    source = "text\n\n```python\ndef f():\n\treturn 1\n```\n"
    assert "\treturn 1" in repair_control_escapes(source)


def test_unrecognised_control_char_becomes_a_space_not_a_guess() -> None:
    assert repair_control_escapes("a\x0czzz b") == "a zzz b"


# -- fences -------------------------------------------------------------------


def test_four_backtick_opener_collapses_to_three() -> None:
    out = normalize_fences("````mermaid\ngraph TD\n  A --> B\n```")
    assert out.startswith("```mermaid\n")
    assert "````" not in out


def test_info_string_carrying_content_is_split_onto_its_own_line() -> None:
    """```mermaid graph TD puts the declaration where the renderer reads it as
    part of the language tag, so the whole block matches nothing."""

    out = normalize_fences("```mermaid graph TD\n  A --> B\n```")
    assert out == "```mermaid\ngraph TD\n  A --> B\n```"


def test_a_well_formed_fence_is_untouched() -> None:
    source = "```python\nx = 1\n```"
    assert normalize_fences(source) == source


# -- mermaid labels -----------------------------------------------------------


def test_quotes_a_label_containing_parentheses() -> None:
    out = quote_mermaid_labels("```mermaid\nflowchart TD\n  D --> E[Moons (Prometheus)]\n```")
    assert 'E["Moons (Prometheus)"]' in out


def test_quotes_a_label_containing_angle_brackets() -> None:
    out = quote_mermaid_labels("```mermaid\ngraph TD\n  A[fn print<T>] --> B[Call]\n```")
    assert 'A["fn print<T>"]' in out
    assert "B[Call]" in out, "a clean label must not be quoted"


def test_quotes_a_subgraph_title_as_a_whole() -> None:
    """A subgraph takes a title, not a label -- the quotes wrap everything."""

    out = quote_mermaid_labels("```mermaid\nflowchart TD\n  subgraph Reads (&str)\n  end\n```")
    assert 'subgraph "Reads (&str)"' in out


@pytest.mark.parametrize(
    "line",
    [
        "  M[(Shared Cache Line)]",  # cylinder -- label is `Shared Cache Line`
        "  M((Raw Memory))",  # circle
        "  M([Stadium Node])",  # stadium
        "  M{{Hexagon}}",  # hexagon
    ],
)
def test_compound_node_shapes_are_left_intact(line: str) -> None:
    """Matching a bare `[` before `[(` would read the cylinder's own parens as
    part of the label, quote them, and silently change the node's SHAPE."""

    source = f"```mermaid\nflowchart TD\n{line}\n```"
    assert quote_mermaid_labels(source) == source


def test_an_already_quoted_label_is_not_quoted_again() -> None:
    """The regression that motivated the scanner: a second pass finding the
    parens inside `B["fn x(&self) -> &T"]` and quoting them again."""

    source = '```mermaid\nflowchart TD\n  A --> B["fn x(&self) -> &T"]\n```'
    assert quote_mermaid_labels(source) == source


def test_sequence_diagrams_are_left_entirely_alone() -> None:
    """`A->>B: text` is free prose after the colon; flowchart rules corrupt it."""

    source = (
        "```mermaid\nsequenceDiagram\n"
        "  Main->>Comp: std::thread::spawn(move || { data })\n```"
    )
    assert quote_mermaid_labels(source) == source


def test_style_lines_keep_their_css_colours() -> None:
    source = "```mermaid\nflowchart TD\n  A[Node]\n  style A fill:#511,stroke:#faa\n```"
    assert quote_mermaid_labels(source) == source


def test_a_non_diagram_fence_is_never_touched() -> None:
    source = "```python\nx = foo(bar)  # [not a label]\n```"
    assert quote_mermaid_labels(source) == source


# -- editorial leakage --------------------------------------------------------


def test_strips_a_trailing_source_note() -> None:
    body = "The sound horizon shrinks.\n\n*Source: Source 3 (Hubble tension).*"
    assert strip_editorial_notes(body) == "The sound horizon shrinks."


def test_strips_a_correction_note_line() -> None:
    body = "Real content here.\n**Key Correction:** the earlier draft said otherwise."
    assert strip_editorial_notes(body) == "Real content here."


def test_leaves_the_word_source_in_ordinary_prose() -> None:
    body = "The source of the radiation is a quasar."
    assert strip_editorial_notes(body) == body


# -- composition and titles ---------------------------------------------------


def test_normalize_card_body_runs_escapes_before_fences() -> None:
    """A formfeed inside the opener would make the fence unrecognisable, so the
    escape pass has to come first for the fence pass to see anything."""

    body = "````mermaid graph TD\n  A[Foo (bar)] --> B\n```\n\n$\x0crac{a}{b}$"
    out = normalize_card_body(body)
    assert out.startswith("```mermaid\ngraph TD")
    assert 'A["Foo (bar)"]' in out
    assert r"\frac{a}{b}" in out


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("error_propagation_in_distance_ladder", "Error Propagation in Distance Ladder"),
        ("standard_ruler_vs_standard_candle", "Standard Ruler vs Standard Candle"),
        ("cmb_power_spectrum", "CMB Power Spectrum"),
    ],
)
def test_humanizes_a_snake_case_canonical_title(raw: str, expected: str) -> None:
    assert humanize_canonical_title(raw) == expected


@pytest.mark.parametrize(
    "title",
    [
        "PostgreSQL MVCC Snapshot Isolation",
        "Rust String and String Slice Differences",
        "single",
    ],
)
def test_a_real_title_is_returned_untouched(title: str) -> None:
    assert humanize_canonical_title(title) == title
