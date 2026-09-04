"""Contract validation: what the ingester accepts, and what it hands back as a work item.

No database and no model — parsing is pure by design, which is what makes
`python -m frog.ingest --check` runnable by the corpus-authoring track and by CI.

These tests are shaped by real drift. Every failing case below has actually occurred in
the delivered corpus between two authoring runs (task 0038, Phase 2), which is the
argument for validating at all rather than trusting the contract document.
"""

from __future__ import annotations

from datetime import UTC, datetime

from frog.ingest.contract import MAX_SECTION_CHARS, parse_document
from frog.universe.models import DocumentKind, DocumentScope

VALID = b"""---
title: MVCC and transaction isolation in PostgreSQL
kind: topic_source
category: Computer Science
sub_category: Databases
scope: topic
source: https://www.postgresql.org/docs/17/mvcc.html
source_date: 2026-08-01
topic_tags:
  - PostgreSQL
  - Distributed Systems
---

## Snapshot isolation

Each transaction sees a snapshot taken at its start.

## What REPEATABLE READ guarantees

Postgres also prevents phantom reads.
"""

CANON = b"""---
title: Card anatomy
kind: spoin_canon
source: Spoin docs/architecture/content-model.md
topic_tags:
  - spoin canon
---

## The card as the atomic unit

A card is a self-contained explanation of one idea.
"""


def test_valid_topic_source_parses() -> None:
    document, errors = parse_document("cs/pg/mvcc.md", VALID)

    assert not errors
    assert document is not None
    assert document.kind is DocumentKind.TOPIC_SOURCE
    assert document.scope is DocumentScope.TOPIC
    assert document.source_path == "cs/pg/mvcc.md"
    assert len(document.sections) == 2
    assert document.sections[0].heading == "Snapshot isolation"


def test_hierarchy_and_tags_share_one_normalizer() -> None:
    """ADR-0091: `category`, `sub_category` and `topic_tags` all go through
    `normalize_topic_text`, so "Computer Science" and "computer-science" cannot become
    two categories in the column the authoring procedure reads back as options."""

    document, _ = parse_document("x.md", VALID)

    assert document is not None
    assert document.category == "computer science"
    assert document.sub_category == "databases"
    assert document.topic_tags == ["postgresql", "distributed systems"]


def test_canon_needs_no_hierarchy() -> None:
    """The CHECK on `document` exempts canon (ADR-0091), so validation must too — a
    canon document with no category is correct, not incomplete."""

    document, errors = parse_document("_canon/card-anatomy.md", CANON)

    assert not errors
    assert document is not None
    assert document.category is None
    assert document.scope is None
    assert document.source_date is None


def test_canon_carrying_a_category_is_an_error() -> None:
    """The exemption runs both ways. Canon that invents a category puts junk in the
    exact column the intake step offers the owner as real options."""

    raw = CANON.replace(b"kind: spoin_canon", b"kind: spoin_canon\ncategory: computer science")
    document, errors = parse_document("x.md", raw)

    assert document is None
    assert any("outside the subject hierarchy" in problem for problem in errors.problems)


def test_missing_title_fails_with_the_field_named() -> None:
    """18 documents arrived without `title` between two authoring runs. The message is
    a work item handed to a person, so it names the file and the field."""

    raw = VALID.replace(b"title: MVCC and transaction isolation in PostgreSQL\n", b"")
    document, errors = parse_document("cs/pg/mvcc.md", raw)

    assert document is None
    assert errors.source_path == "cs/pg/mvcc.md"
    assert any("`title` is missing" in problem for problem in errors.problems)


def test_every_problem_is_reported_not_just_the_first() -> None:
    """The corpus drifts in batches, not one file at a time. A fail-fast validator
    turns one audit into a dozen sequential runs."""

    raw = VALID.replace(b"title: MVCC and transaction isolation in PostgreSQL\n", b"")
    raw = raw.replace(b"scope: topic\n", b"")
    _, errors = parse_document("x.md", raw)

    assert len(errors.problems) >= 2
    assert any("title" in p for p in errors.problems)
    assert any("scope" in p for p in errors.problems)


def test_a_bad_kind_is_an_error_not_a_third_kind() -> None:
    """ADR-0088 made `kind` a real enum precisely so a front-matter typo cannot create
    a silent third kind that nothing ever retrieves."""

    raw = VALID.replace(b"kind: topic_source", b"kind: topic-source")
    document, errors = parse_document("x.md", raw)

    assert document is None
    assert any("spoin_canon" in problem for problem in errors.problems)


def test_source_date_accepts_year_month_and_full_date() -> None:
    """A bare year is honest for material sourced from practitioner experience and
    postmortems — there is no single date. Shorter forms widen to the first instant of
    the period rather than being rejected (owner's decision, 2026-09-05); the contract
    still asks for a full date where one exists."""

    for written, expected in (
        (b"2026-08-01", datetime(2026, 8, 1, tzinfo=UTC)),
        (b"2026-08", datetime(2026, 8, 1, tzinfo=UTC)),
        (b"2024", datetime(2024, 1, 1, tzinfo=UTC)),
    ):
        raw = VALID.replace(b"source_date: 2026-08-01", b"source_date: " + written)
        document, errors = parse_document("x.md", raw)

        assert not errors, (written, errors.problems)
        assert document is not None
        assert document.source_date == expected


def test_source_date_rejects_an_unparseable_value() -> None:
    raw = VALID.replace(b"source_date: 2026-08-01", b"source_date: last summer")
    document, errors = parse_document("x.md", raw)

    assert document is None
    assert any("source_date" in problem for problem in errors.problems)


def test_prose_before_the_first_heading_fails_the_document() -> None:
    """Owner's decision, 2026-09-05: a hard error, not a warning and not a silent drop.

    A chunk is retrieved and shown to a model without its neighbours, so an opening
    paragraph belonging to no section is either lost or smuggled into a chunk it does
    not describe. 26 documents arrived this way.
    """

    raw = VALID.replace(
        b"\n## Snapshot isolation", b"\nThis document surveys isolation.\n\n## Snapshot isolation"
    )
    document, errors = parse_document("x.md", raw)

    assert document is None
    assert any("before the first `##`" in problem for problem in errors.problems)


def test_an_h1_line_is_not_prose() -> None:
    """The one exception: an H1 duplicates front-matter `title`, which the contextual
    header already puts on every chunk. Failing a document over it would be noise."""

    raw = VALID.replace(
        b"\n## Snapshot isolation", b"\n# MVCC in PostgreSQL\n\n## Snapshot isolation"
    )
    document, errors = parse_document("x.md", raw)

    assert not errors, errors.problems
    assert document is not None


def test_a_document_with_no_sections_fails() -> None:
    raw = VALID.replace(b"## ", b"Not a heading: ")
    document, errors = parse_document("x.md", raw)

    assert document is None
    assert any("`##` sections" in problem for problem in errors.problems)


def test_missing_front_matter_fails() -> None:
    document, errors = parse_document("x.md", b"## Just a heading\n\nBody.\n")

    assert document is None
    assert any("front matter" in problem for problem in errors.problems)


def test_content_hash_changes_with_the_file() -> None:
    """Identity is the path; change is the hash (ADR-0088). A version field in front
    matter can be forgotten — a hash cannot."""

    first, _ = parse_document("x.md", VALID)
    second, _ = parse_document("x.md", VALID.replace(b"Postgres also", b"PostgreSQL also"))

    assert first is not None and second is not None
    assert first.content_hash != second.content_hash


def test_an_oversized_section_fails_the_document() -> None:
    """Owner's decision, 2026-09-05: a hard error at ~512 tokens, enforced the same way
    the preamble rule is.

    There is no sub-splitter, deliberately — a section is the author's judgment about
    where one idea ends. That only works if sections stay chunk-sized, and measured over
    358 real sections with Qwen3's own tokenizer, 17% were over 512 tokens. A guideline
    was not holding it (CLAUDE.md: a rule stated only in a doc is a wish).
    """

    fat = b"word " * 500  # 2500 characters, over the 2200 limit
    raw = VALID.replace(b"Each transaction sees a snapshot taken at its start.", fat)
    document, errors = parse_document("x.md", raw)

    assert document is None
    assert any("over the 2200 limit" in problem for problem in errors.problems)
    assert any("Snapshot isolation" in problem for problem in errors.problems)


def test_a_section_at_the_limit_is_accepted() -> None:
    """The boundary is inclusive: 2200 characters passes, 2201 does not. Asserted so a
    later refactor cannot quietly move a hard-fail threshold by one."""

    at_limit = b"a" * MAX_SECTION_CHARS
    raw = VALID.replace(b"Each transaction sees a snapshot taken at its start.", at_limit)
    document, errors = parse_document("x.md", raw)
    assert document is not None, errors.problems

    raw = VALID.replace(b"Each transaction sees a snapshot taken at its start.", at_limit + b"a")
    document, _ = parse_document("x.md", raw)
    assert document is None
