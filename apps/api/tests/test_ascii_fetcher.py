"""ADR-0080: the ASCII fetcher -- retrieval exclusion, the fake's pick behaviour,
the writer-brief disposition line, and src_id landing on the draft.

No database: `top_candidates` reads the packaged gag library, the fake generator
is deterministic, and `_format_plans` / `_finalize_ascii_fields` are pure. The
per-topic persistence half (`topic_used_ascii_ids`, the `_Runtime` used-set) is
exercised by the DB-backed pipeline tests.
"""

from __future__ import annotations

from spoin.content.ascii_library import load_library, top_candidates
from spoin.domain.enums import CardType, Difficulty
from spoin.generation.base import CardPlan, FetchedAsciiScene
from spoin.generation.fake import FakeContentGenerator
from spoin.generation.langchain_impl import _finalize_ascii_fields, _format_plans


async def test_top_candidates_excludes_given_ids() -> None:
    baseline = await top_candidates("a person standing", k=5)
    assert len(baseline) == 5
    drop = frozenset({baseline[0].id, baseline[2].id})

    after = await top_candidates("a person standing", k=5, exclude_ids=drop)
    got = {e.id for e in after}
    assert drop.isdisjoint(got)
    # Still a full page -- the next-best entries slid up to fill the gap.
    assert len(after) == 5


async def test_top_candidates_exclude_all_returns_nothing() -> None:
    every_id = frozenset(e.id for e in load_library())
    assert await top_candidates("anything", k=10, exclude_ids=every_id) == []


async def test_fake_fetch_matches_and_honours_exclude() -> None:
    gen = FakeContentGenerator()
    from spoin.generation.base import AsciiFetchQuery

    queries = [
        AsciiFetchQuery(
            index=0,
            canonical_title="Progressive overload",
            asset_direction="a bored barbell",
            content_direction="the joke is in the captions",
        ),
        AsciiFetchQuery(
            index=1,
            canonical_title="Progressive overload",  # same title -> same fake src_id
            asset_direction="",
            content_direction="",
        ),
    ]
    first = await gen.fetch_ascii_scenes(
        queries[:1],
        topic_name="Gym",
        subtopic_title="Training",
        difficulty=Difficulty.BEGINNER,
        exclude_ids=frozenset(),
    )
    assert first.items[0].matched
    used = first.items[0].src_id
    assert used and first.items[0].art.strip()

    # Same concept, now excluded -> the fake refuses rather than repeating art.
    again = await gen.fetch_ascii_scenes(
        queries[1:],
        topic_name="Gym",
        subtopic_title="Training",
        difficulty=Difficulty.BEGINNER,
        exclude_ids=frozenset({used}),
    )
    assert not again.items[0].matched


def _ascii_plan(fetched: FetchedAsciiScene | None) -> CardPlan:
    return CardPlan(
        canonical_title="Progressive overload",
        card_type=CardType.ASCII.value,
        asset_direction="a bored barbell",
        content_direction="captions carry the gag",
        fetched_scene=fetched,
    )


def test_format_plans_marks_provided_vs_draw() -> None:
    provided = _format_plans(
        [_ascii_plan(FetchedAsciiScene(src_id="art_1", label="l", art="  o", alt="a"))]
    )
    assert "art: PROVIDED" in provided
    assert "leave ascii_label / ascii_art / ascii_alt EMPTY" in provided

    free = _format_plans([_ascii_plan(None)])
    assert "art: draw one" in free


def test_finalize_ascii_fields_carries_src_id() -> None:
    _label, slots = _finalize_ascii_fields("scene", "  o\n /|\\", "alt text", src_id="art_52_5")
    assert slots["src_id"] == "art_52_5"
    assert slots["art"].startswith("  o")

    _label2, slots2 = _finalize_ascii_fields("scene", "  o", "alt")
    assert "src_id" not in slots2


async def test_fake_generate_cards_attaches_fetched_scene() -> None:
    gen = FakeContentGenerator()
    plan = _ascii_plan(
        FetchedAsciiScene(
            src_id="art_99", label="barbell-nap", art="  o  zzz", alt="a napping barbell"
        )
    )
    result = await gen.generate_cards(
        topic_name="Gym",
        subtopic_title="Training",
        subtopic_description="",
        difficulty=Difficulty.BEGINNER,
        count=1,
        existing_titles=[],
        builds_on=[],
        difficulty_examples={},
        avoid_bodies=[],
        rejection_feedback=[],
        card_type=CardType.ASCII.value,
        plans=[plan],
    )
    draft = result.items[0]
    assert draft.visual_slots is not None
    assert draft.visual_slots["src_id"] == "art_99"
    assert draft.visual_slots["art"] == "  o  zzz"
    assert draft.visual_id == "barbell-nap"
