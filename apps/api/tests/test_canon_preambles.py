"""The drift guard for the pinned canon preambles.

`generation/prompts/canon.py` condenses five `_canon` corpus documents into a preamble
per call type. That makes the preambles a DERIVED artifact whose source is authored by
another track and revised without reference to this repository's prompt code — so the
preambles can go stale, and staleness in a prompt is invisible: the cards keep coming,
they are just written against a rule the product no longer holds.

CLAUDE.md: a hard rule gets enforced, never merely documented. This is the enforcement.
It needs no database, no GPU and no network — the same purity that makes
`make corpus-check` the thing the authoring track can actually run.
"""

from __future__ import annotations

import pytest

from spoin.generation.prompts import canon

#: Every pinned preamble, by the call type it is pinned to. Named individually rather
#: than discovered by a `_CANON` suffix scan: a preamble that stops being exported
#: should break this list loudly, not silently drop out of the coverage.
ALL_PREAMBLES: dict[str, str] = {
    # `generate_curriculum` / `CURRICULUM_CANON` went with ADR-0007 -- curricula are
    # authored, not generated, so there is no curriculum prompt to pin a preamble to.
    "plan_cards": canon.PLAN_CANON,
    "generate_cards": canon.CARDS_CANON,
    "generate_cards:diagram": canon.CARDS_DIAGRAM_CANON,
    "generate_cards:ascii": canon.CARDS_ASCII_CANON,
    "fetch_ascii_scenes": canon.ASCII_FETCH_CANON,
    "verify_cards": canon.VERIFICATION_CANON,
    "correct_cards": canon.CORRECTION_CANON,
    "repair_card_structure": canon.REPAIR_CANON,
    "generate_questions": canon.QUESTIONS_CANON,
}


def test_canon_source_has_not_drifted() -> None:
    """The condensed preambles still match the corpus documents they condense.

    **If this fails, do not just update the hash.** Read what changed in the named
    document and decide whether the preamble that condenses it needs to change too —
    the hash is a prompt to think, not a checksum to appease. Updating it blind is the
    same failure as having no guard, with extra steps.
    """

    drifted = canon.canon_source_drift()
    assert not drifted, (
        "canon corpus documents changed since the pinned preambles were written: "
        + ", ".join(drifted)
        + ". Re-read them, revise generation/prompts/canon.py where the rules moved, "
        "then update CANON_SOURCE_HASHES."
    )


def test_canon_corpus_is_reachable() -> None:
    """The guard above can only pass honestly if it found the corpus.

    Separated from the drift assertion so a missing mount reads as "the guard could not
    run" rather than as "nothing drifted" — those are different facts, and CLAUDE.md is
    specific that folding a could-not-check into a passed is how a check stops being one.
    """

    assert canon.CANON_CORPUS_DIR is not None, (
        "canon corpus not reachable. In the test container this comes from the "
        "docs/the_spoin_universe read-only mount on the `test` compose service."
    )


@pytest.mark.parametrize("call_type", sorted(ALL_PREAMBLES))
def test_preamble_fits_the_prompt_budget(call_type: str) -> None:
    """No preamble runs away with the prompt.

    ADR-0089's table is the reason this is a test and not a guideline: sustainable
    throughput is `min(TPM / prompt_tokens, RPM)`, and `ministral-8b` drops below the
    target rate above ~18k prompt tokens. A preamble is paid on EVERY call of its type,
    before a single retrieved fact is added, so growth here comes straight out of the
    grounding budget.

    The ceiling is deliberately loose — it catches a preamble that doubled, not one that
    gained a clause. `chars // 4` is ADR-0085's estimator, kept here so this number and
    the load balancer's are the same kind of number.
    """

    estimated_tokens = len(ALL_PREAMBLES[call_type]) // 4
    assert estimated_tokens <= 1200, (
        f"{call_type} canon preamble is ~{estimated_tokens} tokens, over the 1200 "
        "ceiling. Condense it, or split the rule onto the call types that need it."
    )


def test_no_preamble_reports_a_derived_field() -> None:
    """A preamble must never teach the model to emit a field it must not emit.

    `archetype`, `difficulty` and `is_hero` are derived or pipeline-assigned
    (ADR-0017, and the quality gate's independent re-rating). The canon document
    explaining WHY archetypes are derived is deliberately pinned nowhere: describing the
    field's derivation to a model that must never touch it spends tokens introducing a
    field and invites exactly the self-report the rule forbids. This asserts the
    instruction stayed negative — the fields may be named, but only under a prohibition.
    """

    for call_type, text in ALL_PREAMBLES.items():
        lowered = text.lower()
        for field in ("`archetype`", "`is_hero`"):
            if field in lowered:
                assert "never report" in lowered, (
                    f"{call_type} names {field} without the prohibition that has to "
                    "accompany it. A preamble that introduces a derived field without "
                    "forbidding it is an invitation to self-report."
                )
