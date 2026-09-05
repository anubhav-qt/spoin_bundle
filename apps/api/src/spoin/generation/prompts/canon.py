"""Spoin canon, condensed into a pinned preamble per call type.

`spoin_canon` — what a card is, dual titles (ADR-0022), archetypes (ADR-0017),
quiz-gated progression (ADR-0009), the ASCII box rule (ADR-0021/0068/0079), CLAUDE.md's
silliness-in-the-hook-layer rule — is relevant to nearly every generation call
regardless of subject, because a small model does not know our conventions.

**It is pinned, never retrieved** (rag-design-space §3.9, amending ADR-0088). Making
canon compete for retrieval slots against topic material fails in both directions at
once: it displaces facts the card needs, *and* it sometimes fails to be retrieved at
all for a call that needed it. Neither failure announces itself.

Pinned **per call type**, not wholesale. The five canon documents are 21,213 characters
— roughly 5,300 prompt tokens — and ADR-0089's table puts `ministral-8b` below target
throughput above ~18k. Most of it is irrelevant to any one call: the ASCII box rule
means nothing to a prose card, curriculum decomposition means nothing to a card writer.
So relevance is decided here, at design time, by a static map. That is still "pinned"
in §3.9's sense — canon never competes for a slot and never fails to appear — it is
only the *selection* that stops being an embedding's guess.

**Condensed, not quoted.** The corpus states each rule with the reasoning that earned
it, which is what a human reading the corpus needs and roughly three times what a model
following the rule needs. The fragments below keep a rule's *why* only where the why is
what makes the rule followable — "a joke in the body becomes the thing the quiz tests"
changes behaviour, "ADR-0079 repealed the informative half" does not.

⚠️ **These are a derived artifact and can rot.** The corpus is authored by another
track and revised without reference to this file. `CANON_SOURCE_HASHES` below and
`test_canon_preambles.py` are the guard: revise a canon document and the test fails,
naming the file, so the preamble is revisited rather than silently going stale. That is
CLAUDE.md's rule that a hard constraint gets enforced, not documented.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: sha256 of each `_canon` document these preambles condense, as of the revision they
#: were written against. The test that recomputes these reads the files from disk and
#: needs no database, no GPU and no network — the same purity that makes
#: `make corpus-check` worth having.
CANON_SOURCE_HASHES: dict[str, str] = {
    "ascii-box-rule-and-gag-scenes.md": (
        "fab943a78e62c364d4d533db62870de03d7161bff5d50d44fc607239a298bd82"
    ),
    "card-anatomy-and-fields.md": (
        "84a696bd04c3e35e28f7553df90c8c1317de8eb8fb9a5337467b7e32c514f10c"
    ),
    "card-archetypes-and-content-shapes.md": (
        "4e344c2ee9e09f045bd877acc756c3cc39b06bc41d9b6770e6c31cd5e5d7a2a9"
    ),
    "curriculum-progression-and-quizzes.md": (
        "3e84db863a02edb577e8ce1c81ce84147387bceac7de6f69f5514f9a1025ece5"
    ),
    "dual-titles-and-hook-discipline.md": (
        "69b2a583f43dc0c09013d8cbfb1800a7d7c923091cf6a9d3384e88aa06017fcd"
    ),
}

#: Where those files live, found by walking up from this module rather than by counting
#: `parents[n]`. The count differs between the working tree (`apps/api/src/spoin/...`,
#: six levels below the repository root) and the container (`/app/src/spoin/...`, four),
#: so a fixed index is correct in exactly one of the two places and silently wrong in
#: the other — which for a drift guard means it reports drift that is not there.
_CANON_RELATIVE = Path("docs") / "the_spoin_universe" / "corpus" / "_canon"


def _find_canon_dir() -> Path | None:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / _CANON_RELATIVE
        if candidate.is_dir():
            return candidate
    return None


CANON_CORPUS_DIR = _find_canon_dir()


def canon_source_drift() -> list[str]:
    """Canon documents whose content no longer matches what the preambles condense.

    Returns the offending filenames, or an empty list. A missing file counts as drift:
    a preamble condensing a document that no longer exists is exactly as stale as one
    condensing a document that changed.

    Raises if the corpus is not reachable at all, rather than reporting "no drift" —
    a guard that passes because it could not find what it guards is the failure mode
    CLAUDE.md means by a rule that is only a wish.
    """

    if CANON_CORPUS_DIR is None:
        raise RuntimeError(
            f"canon corpus not found: no ancestor of {Path(__file__).resolve()} contains "
            f"{_CANON_RELATIVE}. The drift guard cannot run. In a container, mount "
            "docs/the_spoin_universe read-only under the application root."
        )

    drifted: list[str] = []
    for name, expected in CANON_SOURCE_HASHES.items():
        path = CANON_CORPUS_DIR / name
        if not path.is_file():
            drifted.append(name)
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            drifted.append(name)
    return drifted


# ---------------------------------------------------------------------------
# Fragments. Each rule is stated ONCE here and composed into the preambles below,
# for the same reason the rules are pinned rather than retrieved: two phrasings of
# one rule is a drift surface, and prompts are where drift is least visible.
# ---------------------------------------------------------------------------

_CARD_UNIT = """\
A Spoin card is one atomic, self-contained explanation of a single concept, read in a \
few seconds and swiped past in an endless vertical feed. Cards are written once and \
served to every user; nothing is generated per reader. A card is four written fields: \
`title` (the display title on the card face), `canonical_title` (the literal name of \
the concept), `summary` (a standalone hook shown while the card is collapsed), and \
`body` (the full Markdown explanation that scrolls when the reader expands it)."""

_FIELD_BOUNDARIES = """\
You are trusted for taste, never for constraints. Emit only the written fields you are \
asked for. Never report `archetype`, `difficulty`, `is_hero`, `status`, `version`, or \
any embedding: those are derived deterministically from your text or assigned by the \
pipeline, and a self-reported value is discarded unread. Anything that must be *true* \
— a column budget, a character limit, a difficulty rating — is checked in server code \
outside you, so write for quality and let the checks be the checks."""

_TITLES = """\
Two titles, two jobs, and they are not interchangeable. `title` is what stops a \
scrolling thumb: it may be witty, evocative or framing-oriented ("The Ghost in the \
Database", "Why Your Thread Pool is Lying to You"). `canonical_title` is the literal, \
unembellished name of the concept ("PostgreSQL MVCC Snapshot Isolation") — search, quiz \
stems, remediation links and deduplication all read it, and wit there is noise in every \
one of them. Never write a playful `canonical_title`, and never let `title` be a dry \
restatement of it."""

_SUMMARY = """\
`summary` is written, not extracted. It is not the opening of `body` and not a \
truncation of it: an explanation opens with framing and throat-clearing, and a hook \
with one second to work cannot afford either. Give it a concrete puzzle, an unexpected \
consequence, or a crisp correction of something the reader probably believes."""

_HOOK_DISCIPLINE = """\
Silliness lives in the hook layer — `title`, `summary`, ASCII art. Never in `body`. \
The body is the exact material quiz questions are written from and the verification \
pass reads as ground truth, so a whimsical analogy there makes the reader answer \
questions about the analogy instead of the engineering. A joke in the hook is charm; a \
joke in the explanation is a defect. The opposite failure is a hook that is provocative \
but disconnected from the mechanism — the reader feels misled when the card opens, \
which costs more than a dull hook does."""

_DIFFICULTY_AND_REGISTER = """\
Difficulty is a property of the card, not of the reader: the role of a database index \
is beginner material, B-tree page-split concurrency is advanced, whoever is reading.

Your grounding material is written dense and precise for accuracy, not for a reader at \
this tier. **Do not inherit its register.** At beginner, unpack the vocabulary the \
source takes for granted and earn every term you keep. At intermediate, assume that \
vocabulary and spend the space on mechanism. At advanced, compress what the source \
explains and go past where it stops. Precision is the corpus's job; pitch is yours."""

_MERMAID = """\
Every diagram is Mermaid inside a ```mermaid fence, rendered client-side as an SVG. \
Never draw a flow, a state machine or a sequence as text boxes and arrows — \
`[Client] ---> [Server]` is forbidden, and so is any box-and-arrow figure in an ASCII \
slot. Keep a diagram narrow enough to read on a phone: decompose a complicated flow \
into several simple sequential diagrams rather than one wide canvas."""

_ASCII_GAG = """\
Every ASCII scene is a gag. A comic character reaction, a pop-culture reference, an \
absurd physical metaphor, a scene with a punchline — that is the entire purpose of the \
slot, and the scenes people screenshot are the funny ones. A neutral technical \
illustration is forbidden there: a server rack, a labelled hardware drawing, a \
flowchart. An idea that only wants a plain picture is a `diagram` card or a `prose` \
card instead, never an `ascii` one."""

_ASCII_BOX = """\
The artwork is a rigid, immutable box. Never edit a line inside it, delete an interior \
character, or redraw part of the figure — spatial coordinates are precisely what a \
language model cannot track, and every attempt skews the columns.

- **Nothing to the left of the art, ever.** One character on the left shifts every row \
and destroys the alignment.
- Captions, titles and stage directions (`*CONFUSED LOOK*`) go strictly above or below \
the block. Dialogue appended to the right must not move any existing line.
- **No line may exceed 40 monospace columns** — counting leading whitespace, borders \
and any trailing dialogue. Phone viewports wrap past that.
- **No limit on HEIGHT** — the budget is per line, so a line added above or below \
is free. A label that will not fit beside a figure gets its own line there; never \
shorten it away. Most art uses ~23 of the 40 columns, so short labels fit right too.

A server-side validator measures every line. If one line is over 40 columns, the whole \
card is discarded — not just the art. The title, summary and body you wrote go with \
it, and the card is generated again from scratch."""

_CURRICULUM = """\
A topic is decomposed once into subtopics across three tiers (beginner, intermediate, \
advanced); every generation call targets one subtopic at one tier. A whole topic is \
capped near 750 cards, ~250 per tier. A subtopic targets 5-25 cards: needing more than \
25 means it is too broad and must be split into narrower subtopics. A tier needing more \
than 20 subtopics means the subject is too vast for one course — it becomes a survey \
topic covering the breadth and pointing at narrower specialised topics through flat \
`deep_dive` edges, never a nested tree."""

_PROGRESSION = """\
Progression is earned, not granted. A reader picks their entry tier and is trusted; to \
unlock the next tier's quiz they must have read at least 80% of the cards in every \
subtopic of their current tier, and that unlock latches permanently — later generation \
adding cards never revokes it. Passing at 80% promotes them. Passing the advanced quiz \
is mastery, and mastery is permanent."""

_QUIZ_MECHANICS = """\
A tier quiz is 9 multiple-choice questions and 1 free-text question, weighted 70/30, \
passing at 80%. **Every question is written from one specific existing card and stores \
its id** — never from the topic in the abstract. That is what guarantees a reader is \
tested only on what the corpus actually taught, and it is what lets a wrong answer link \
straight back to the card that teaches the missing idea. A question whose answer is not \
in its card's body is a defect, however true it is."""


def _preamble(*fragments: str) -> str:
    return "\n\n".join(fragments)


# ---------------------------------------------------------------------------
# The pinned preambles, one per call type.
#
# `AR2` — "archetypes are derived post-generation, never requested" — is condensed
# into `_FIELD_BOUNDARIES` as an instruction not to emit the field, rather than
# pinned as canon. Explaining the derivation to a model that must never touch it
# spends tokens describing a field and invites the self-report the rule forbids.
# ---------------------------------------------------------------------------

CURRICULUM_CANON = _preamble(_CURRICULUM, _PROGRESSION)

PLAN_CANON = _preamble(_CARD_UNIT, _CURRICULUM, _ASCII_GAG)

#: The base for every card-writing call: prose, code, comparison and hero.
CARDS_CANON = _preamble(
    _CARD_UNIT, _FIELD_BOUNDARIES, _TITLES, _SUMMARY, _HOOK_DISCIPLINE, _DIFFICULTY_AND_REGISTER
)

CARDS_DIAGRAM_CANON = _preamble(CARDS_CANON, _MERMAID)

CARDS_ASCII_CANON = _preamble(CARDS_CANON, _ASCII_GAG, _ASCII_BOX)

#: The fetch call ADAPTS a library scene rather than drawing one, which is exactly the
#: operation the box rule governs — so it gets `_ASCII_BOX` too. Pinning only the gag
#: rule here would leave the one call that edits existing artwork without the rule
#: about editing existing artwork.
ASCII_FETCH_CANON = _preamble(_ASCII_GAG, _ASCII_BOX)

#: The gate. Deliberately the narrowest card-side preamble: verification runs on the
#: scarcer thinking ladder, and a verifier does not need to know how to write a hook —
#: it needs to know which fields are load-bearing and that `body` is judged as truth.
VERIFICATION_CANON = _preamble(_CARD_UNIT, _FIELD_BOUNDARIES, _HOOK_DISCIPLINE)

#: Pass 1 of the gate REWRITES cards, ASCII art included, so it needs `_ASCII_BOX` for
#: the same reason the fetch call does: it is one of the calls that edits existing
#: artwork, and the box rule is the rule about editing existing artwork. Verification
#: (pass 2) judges without rewriting and so does not need it.
CORRECTION_CANON = _preamble(_CARD_UNIT, _TITLES, _SUMMARY, _HOOK_DISCIPLINE, _ASCII_BOX)

REPAIR_CANON = _preamble(_MERMAID, _ASCII_BOX)

QUESTIONS_CANON = _preamble(_PROGRESSION, _QUIZ_MECHANICS)
