"""Register measurement for card bodies — how hard the prose is to read.

Exists because the register rule could not be enforced any other way. The canon
has told the writer "do not inherit your grounding material's register" for as
long as grounding has existed, and on 2026-09-07 the corpus measured like this:

    topic       tier          n   FK grade   "you" per 1k words
    Astronomy   beginner    162      12.8            0.5
    Astronomy   advanced    179      14.5            0.4
    Rust        beginner     28      11.4           37.8
    Rust        advanced     31      15.4            4.4

Two separate failures in one table. Astronomy sits at college register at
*every* tier and never addresses the reader at all -- it inherited the academic
voice of the papers it was grounded in, exactly as the canon said not to. And
both topics climb steeply with tier, because the canon ALSO said "at advanced,
compress what the source explains", which is an instruction to write denser
prose for a harder idea. ADR-0104 separates those two axes; this module is what
makes the separation checkable instead of merely stated.

Pure stdlib on purpose. It runs in the api image, which stays minimal
(ADR-0094), and a syllable counter is not worth a dependency.
"""

from __future__ import annotations

import re

#: Fenced blocks, inline code, math and markdown punctuation are not prose and
#: would wreck both counts -- a LaTeX formula reads as a run of one-letter
#: "words", and a code fence's identifiers read as polysyllables.
_FENCE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_MATH_RE = re.compile(r"\$\$[\s\S]*?\$\$|\$[^$\n]*\$")
_MARKUP_RE = re.compile(r"[*#>|_~\[\]()]+")
_URL_RE = re.compile(r"https?://\S+")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
#: Both apostrophes: the corpus is full of typographic ones, and splitting
#: "star's" into two words would inflate the word count and deflate the grade.
_WORD_RE = re.compile("[A-Za-z][A-Za-z'’-]*")  # noqa: RUF001
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")

#: Second-person address. The single strongest signal that a card is teaching a
#: reader rather than describing a subject, and the one that separated Rust's
#: beginner cards (37.8 per 1k) from Astronomy's (0.5).
_SECOND_PERSON_RE = re.compile(r"\b(you|your|yours|you're|youre|yourself)\b", re.IGNORECASE)


def prose_only(body: str) -> str:
    """The part of a card body that is actually sentences a reader reads."""

    text = _FENCE_RE.sub(" ", body)
    text = _MATH_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _MARKUP_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def count_syllables(word: str) -> int:
    """Vowel-group heuristic. Wrong on individual words, reliable in aggregate,
    and the standard basis for every Flesch-family score."""

    cleaned = re.sub(r"[^a-z]", "", word.lower())
    if not cleaned:
        return 0
    groups = len(_VOWEL_GROUP_RE.findall(cleaned))
    if cleaned.endswith("e") and groups > 1:
        groups -= 1
    return max(groups, 1)


def flesch_kincaid_grade(body: str) -> float | None:
    """US grade level of the card's prose, or `None` when there is too little.

    `None` rather than a number for a card whose body is mostly a code block or
    a formula: a two-sentence sample produces a grade with no meaning, and a
    check that treats noise as a verdict rejects good cards at random.

    For calibration: general-audience science writing sits around grade 9-11,
    and a microlearning card should read easier than a magazine article, not
    harder.
    """

    text = prose_only(body)
    words = _WORD_RE.findall(text)
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if len(_WORD_RE.findall(s)) > 2]
    if len(words) < 40 or not sentences:
        return None
    syllables = sum(count_syllables(word) for word in words)
    return 0.39 * (len(words) / len(sentences)) + 11.8 * (syllables / len(words)) - 15.59


def second_person_per_1k(body: str) -> float | None:
    """How often the card addresses its reader, per 1,000 words of prose."""

    text = prose_only(body)
    words = _WORD_RE.findall(text)
    if len(words) < 40:
        return None
    return len(_SECOND_PERSON_RE.findall(text)) / len(words) * 1000
