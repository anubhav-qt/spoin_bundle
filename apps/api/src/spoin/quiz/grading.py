"""Grading arithmetic and the prompt-injection guard.

Pure functions, no session, no settings lookup, no I/O. They were inline in
`api/routers/quiz.py`'s 148-line `submit_free_text`, which meant the scoring
formula and the injection defence could only be exercised through an HTTP call
that also needed a database and a live LLM. Both are exactly the kind of logic
that wants a table of inputs and expected outputs.
"""

from __future__ import annotations

import re

#: Words of 4+ letters, used by `references_question`.
_TOKEN_RE = re.compile(r"[a-zA-Z]{4,}")


def tokens(text: str) -> set[str]:
    return {match.lower() for match in _TOKEN_RE.findall(text)}


def references_question(justification: str, *contexts: str) -> bool:
    """Independent, code-level check that the grader's justification is
    actually about THIS question (ADR-0009's prompt-injection defence: the
    system prompt tells the model to grade the answer as data, but this
    re-checks the model's own output rather than trusting it outright).

    A cheap heuristic, not a second LLM call: any shared 4+-letter word
    between the justification and the question's own stem/reference-answer/
    submitted-answer is enough. A justification sharing NO vocabulary with any
    of them is a strong signal something went wrong (an injected instruction
    got echoed back, or a degenerate/templated response), so it is treated as
    untrustworthy rather than graded at face value.
    """

    justification_tokens = tokens(justification)
    if not justification_tokens:
        return False
    context_tokens: set[str] = set()
    for context in contexts:
        context_tokens |= tokens(context)
    return bool(justification_tokens & context_tokens)


def combined_score(
    *,
    mcq_fraction: float,
    rubric_level: int,
    mcq_weight: float,
    free_text_weight: float,
) -> float:
    """ADR-0009's weighted split, rounded before any threshold comparison.

    The rounding is load-bearing, not cosmetic: 0.7 + 0.3 * (1 / 3) evaluates
    to 0.7999999999999999 in binary floating point, which fails an exact
    `>= 0.80` pass mark the user genuinely earned.
    """

    free_text_fraction = rubric_level / 3
    return round(mcq_weight * mcq_fraction + free_text_weight * free_text_fraction, 6)
