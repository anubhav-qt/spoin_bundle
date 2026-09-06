"""Parsing and validating one authored curriculum against the delivery contract.

The contract itself is `docs/handoff/antigravity-curriculum-authoring.md`; this module
is the machine half of it, and the architecture is
`docs/architecture/authored-curriculum.md`. A curriculum is authored by one track
(Antigravity, supervised by the owner) and consumed by a deterministic projection into
`Topic`/`Subtopic`. Nothing here calls a model or opens a database, which is what lets
the authoring track run `make curriculum-check` while writing.

**Validation reports every problem in every file rather than dying on the first**, the
same discipline `frog.ingest.contract` follows and for the same reason: an authored
artifact drifts in batches, and a fail-fast validator surfaces ten problems as ten
runs.

frog must not import spoin (ADR-0087), so the two vocabularies and the `target_cards`
band below are mirrored from `spoin` **by value**, the way `frog.universe.models`'
`DocumentScope` mirrors `topic.is_survey`:

- the tiers mirror `spoin.domain.enums.Difficulty`;
- the card types mirror `spoin.domain.enums.CardType`;
- ``MIN_TARGET_CARDS`` / ``MAX_TARGET_CARDS`` mirror the CHECK constraint
  ``target_cards BETWEEN 5 AND 25`` on ``subtopic`` (``spoin/domain/models/topic.py``),
  so a value outside the band fails here rather than at the projection's INSERT.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

#: Front matter is a leading `---` line, a YAML block, and a closing `---` line, with
#: nothing but whitespace after it -- a curriculum file is data, not prose. Same anchor
#: as `frog.ingest.contract._FRONT_MATTER`.
_FRONT_MATTER = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---[ \t]*\r?\n?(?P<body>.*)\Z", re.S)

#: Mirrors `spoin.domain.enums.Difficulty` by value (ADR-0087: no import).
TIERS: tuple[str, ...] = ("beginner", "intermediate", "advanced")

#: Mirrors `spoin.domain.enums.CardType` by value (ADR-0087: no import).
CARD_TYPES: tuple[str, ...] = ("prose", "code", "diagram", "comparison", "ascii")

#: The band the database enforces on `subtopic.target_cards`.
MIN_TARGET_CARDS = 5
MAX_TARGET_CARDS = 25


@dataclass(frozen=True)
class ParsedTier:
    """One tier's plan for a subtopic: how many cards, and the mix."""

    tier: str
    target_cards: int
    #: Only the types the author named; a missing type is zero. Keys are a subset of
    #: ``CARD_TYPES`` and the values sum to ``target_cards`` -- both checked here.
    card_types: dict[str, int]


@dataclass(frozen=True)
class ParsedSubtopic:
    """One curriculum unit -- becomes a subtopic group spanning its tiers."""

    title: str
    description: str
    prerequisites: list[str]
    sources: list[str]
    tiers: list[ParsedTier]


@dataclass(frozen=True)
class ParsedCurriculum:
    """A curriculum file that satisfied the contract, ready to project.

    ``content_hash`` is carried now, unused by the validator, because task 2's
    ingestion is idempotent by it exactly as the corpus ingester is -- computing it
    here keeps that dataclass from being reshaped later.
    """

    source_path: str
    content_hash: str
    topic: str
    description: str
    is_survey: bool
    subtopics: list[ParsedSubtopic]


@dataclass
class CurriculumErrors:
    """Every contract violation in one file, collected rather than raised.

    ``source_path`` is the file's identity relative to the curricula root
    (``rust/curriculum.md``), so an error line and a future ``curriculum`` row name the
    same thing.
    """

    source_path: str
    problems: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.problems)

    def add(self, message: str) -> None:
        self.problems.append(message)


def content_hash(raw: bytes) -> str:
    """sha256 of the file as delivered -- bytes, before decoding (ADR-0088's rationale)."""

    return hashlib.sha256(raw).hexdigest()


def parse_curriculum(
    source_path: str, raw: bytes
) -> tuple[ParsedCurriculum | None, CurriculumErrors]:
    """Parse and validate one curriculum. Returns it, or the reasons it failed.

    Never raises for bad content. Everything checkable from the file alone is checked
    here: fields, the tier and card-type vocabularies, the ``target_cards`` band,
    ``card_types`` summing, ``prerequisites`` resolving within the file, and the
    prerequisite graph being acyclic. The one cross-file check -- every ``sources``
    path existing in the corpus -- is the runner's, because only it has the corpus
    tree.
    """

    errors = CurriculumErrors(source_path=source_path)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.add(f"not valid UTF-8: {exc}")
        return None, errors

    match = _FRONT_MATTER.match(text)
    if match is None:
        errors.add("no YAML front matter (file must open with a `---` line)")
        return None, errors

    if match.group("body").strip():
        errors.add(
            "content after the closing `---` -- a curriculum is data and has no prose "
            "body; move any notes into a comment or delete them"
        )

    try:
        loaded = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        errors.add(f"front matter is not valid YAML: {exc}")
        return None, errors

    if not isinstance(loaded, dict):
        errors.add("front matter is not a mapping")
        return None, errors

    front: dict[str, Any] = loaded

    topic = _required_str(front, "topic", "", errors)
    description = _required_str(front, "description", "", errors)
    is_survey = _required_bool(front, "is_survey", errors)
    subtopics = _subtopics(front, errors)

    if errors or topic is None or description is None or is_survey is None or subtopics is None:
        return None, errors

    return (
        ParsedCurriculum(
            source_path=source_path,
            content_hash=content_hash(raw),
            topic=topic,
            description=description,
            is_survey=is_survey,
            subtopics=subtopics,
        ),
        errors,
    )


def _at(where: str, message: str) -> str:
    return f"{where}: {message}" if where else message


def _required_str(
    mapping: dict[str, Any], key: str, where: str, errors: CurriculumErrors
) -> str | None:
    value = mapping.get(key)
    if value is None:
        errors.add(_at(where, f"`{key}` is missing (required by the contract)"))
        return None
    if not isinstance(value, str) or not value.strip():
        errors.add(_at(where, f"`{key}` must be a non-empty string, got {value!r}"))
        return None
    return value.strip()


def _required_bool(mapping: dict[str, Any], key: str, errors: CurriculumErrors) -> bool | None:
    value = mapping.get(key)
    if value is None:
        errors.add(f"`{key}` is missing (required: `true` or `false`)")
        return None
    if not isinstance(value, bool):
        errors.add(f"`{key}` must be `true` or `false`, got {value!r}")
        return None
    return value


def _subtopics(front: dict[str, Any], errors: CurriculumErrors) -> list[ParsedSubtopic] | None:
    raw = front.get("subtopics")
    if raw is None:
        errors.add("`subtopics` is missing (required: a non-empty list)")
        return None
    if not isinstance(raw, list) or not raw:
        errors.add(f"`subtopics` must be a non-empty list, got {raw!r}")
        return None

    parsed: list[ParsedSubtopic] = []
    seen_titles: set[str] = set()
    for index, entry in enumerate(raw):
        subtopic = _subtopic(entry, index, errors)
        if subtopic is None:
            continue
        if subtopic.title in seen_titles:
            #: The projection matches a subtopic on (topic, title, tier), so two rows
            #: with one title collapse into one and silently drop a unit.
            errors.add(
                f"subtopic {index}: duplicate title {subtopic.title!r} -- titles are the "
                "projection's match key and must be unique within a curriculum"
            )
            continue
        seen_titles.add(subtopic.title)
        parsed.append(subtopic)

    if not parsed:
        return None

    _check_prerequisites(parsed, errors)
    return parsed


def _subtopic(entry: Any, index: int, errors: CurriculumErrors) -> ParsedSubtopic | None:
    fallback = f"subtopic {index}"
    if not isinstance(entry, dict):
        errors.add(f"{fallback}: must be a mapping, got {type(entry).__name__}")
        return None

    title = _required_str(entry, "title", fallback, errors)
    where = f"subtopic {title!r}" if title else fallback
    description = _required_str(entry, "description", where, errors)

    prerequisites = _str_list(entry, "prerequisites", where, errors, allow_empty=True)
    sources = _str_list(entry, "sources", where, errors, allow_empty=False)
    tiers = _tiers(entry, where, errors)

    if (
        title is None
        or description is None
        or prerequisites is None
        or sources is None
        or tiers is None
    ):
        return None

    return ParsedSubtopic(
        title=title,
        description=description,
        prerequisites=prerequisites,
        sources=sources,
        tiers=tiers,
    )


def _str_list(
    entry: dict[str, Any],
    key: str,
    where: str,
    errors: CurriculumErrors,
    *,
    allow_empty: bool,
) -> list[str] | None:
    if key not in entry:
        errors.add(_at(where, f"`{key}` is missing (required by the contract)"))
        return None
    raw = entry[key]
    if not isinstance(raw, list):
        errors.add(_at(where, f"`{key}` must be a list, got {type(raw).__name__}"))
        return None
    if not raw and not allow_empty:
        errors.add(_at(where, f"`{key}` must not be empty"))
        return None
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            errors.add(_at(where, f"`{key}` entries must be non-empty strings, got {item!r}"))
            continue
        values.append(item.strip())
    return values


def _tiers(entry: dict[str, Any], where: str, errors: CurriculumErrors) -> list[ParsedTier] | None:
    raw = entry.get("tiers")
    if raw is None:
        errors.add(_at(where, "`tiers` is missing (a map of tier -> plan)"))
        return None
    if not isinstance(raw, dict) or not raw:
        errors.add(_at(where, f"`tiers` must be a non-empty mapping, got {raw!r}"))
        return None

    tiers: list[ParsedTier] = []
    for tier_name, plan in raw.items():
        if tier_name not in TIERS:
            errors.add(
                _at(where, f"unknown tier {tier_name!r} -- must be one of {', '.join(TIERS)}")
            )
            continue
        parsed = _tier_plan(str(tier_name), plan, where, errors)
        if parsed is not None:
            tiers.append(parsed)

    if not tiers:
        return None
    return tiers


def _tier_plan(
    tier_name: str, plan: Any, where: str, errors: CurriculumErrors
) -> ParsedTier | None:
    at = f"{where}, tier {tier_name!r}"
    if not isinstance(plan, dict):
        errors.add(f"{at}: must be a mapping with `target_cards` and `card_types`")
        return None

    raw_target = plan.get("target_cards")
    target: int | None = None
    if not isinstance(raw_target, int) or isinstance(raw_target, bool):
        errors.add(f"{at}: `target_cards` must be an integer, got {raw_target!r}")
    elif not MIN_TARGET_CARDS <= raw_target <= MAX_TARGET_CARDS:
        errors.add(
            f"{at}: `target_cards` is {raw_target}, outside the {MIN_TARGET_CARDS}-"
            f"{MAX_TARGET_CARDS} band the database enforces"
        )
    else:
        target = raw_target

    card_types = _card_types(plan, at, errors)

    if target is None or card_types is None:
        return None

    total = sum(card_types.values())
    if total != target:
        errors.add(f"{at}: `card_types` sums to {total}, not `target_cards` ({target})")
        return None

    return ParsedTier(tier=tier_name, target_cards=target, card_types=card_types)


def _card_types(plan: dict[str, Any], at: str, errors: CurriculumErrors) -> dict[str, int] | None:
    raw = plan.get("card_types")
    if not isinstance(raw, dict) or not raw:
        errors.add(f"{at}: `card_types` must be a non-empty mapping")
        return None

    quotas: dict[str, int] = {}
    ok = True
    for name, count in raw.items():
        if name not in CARD_TYPES:
            errors.add(
                f"{at}: unknown card type {name!r} -- must be one of {', '.join(CARD_TYPES)}"
            )
            ok = False
            continue
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.add(f"{at}: card type {name!r} must be a non-negative integer, got {count!r}")
            ok = False
            continue
        quotas[str(name)] = count

    return quotas if ok else None


def _check_prerequisites(subtopics: list[ParsedSubtopic], errors: CurriculumErrors) -> None:
    """`prerequisites` must name titles in this file, and the graph must be acyclic."""

    titles = {s.title for s in subtopics}
    edges: dict[str, list[str]] = {}
    for subtopic in subtopics:
        resolved: list[str] = []
        for prerequisite in subtopic.prerequisites:
            if prerequisite == subtopic.title:
                errors.add(f"subtopic {subtopic.title!r}: lists itself as a prerequisite")
                continue
            if prerequisite not in titles:
                errors.add(
                    f"subtopic {subtopic.title!r}: prerequisite {prerequisite!r} is not a "
                    "subtopic in this curriculum"
                )
                continue
            resolved.append(prerequisite)
        edges[subtopic.title] = resolved

    cycle = _first_cycle(edges)
    if cycle is not None:
        errors.add("prerequisite cycle: " + " -> ".join(cycle) + " -- the graph must be a DAG")


def _first_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle as an ordered path, or None. DFS with a three-colour marking."""

    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(edges, white)

    def visit(node: str, path: list[str]) -> list[str] | None:
        colour[node] = grey
        path.append(node)
        for nxt in edges.get(node, ()):
            if colour[nxt] == grey:
                return [*path[path.index(nxt) :], nxt]
            if colour[nxt] == white:
                found = visit(nxt, path)
                if found is not None:
                    return found
        path.pop()
        colour[node] = black
        return None

    for start in edges:
        if colour[start] == white:
            found = visit(start, [])
            if found is not None:
                return found
    return None
