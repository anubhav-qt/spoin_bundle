"""Author-declared scope, per-card retrieval, and the open-query allowance.

The change generation-pipeline-v2 calls for: the curriculum declares which corpus
sections a tier's cards may be written from, retrieval ranks WITHIN that scope once per
card, and a scope that cannot fill `k` is topped up from the open corpus and counted.

Real corpus database, because what is under test is the join that resolves
`<path>#<heading>` to chunks and the SQL filter that scopes the search. Skipped when
`SPOIN_UNIVERSE_TEST_DATABASE_URL` is unset; see conftest.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from frog.embeddings import Embedder, HashEmbedder
from frog.universe.models import EMBEDDING_DIM, Chunk, Document, DocumentKind, DocumentScope
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import spoin.generation.grounding as grounding_module
from spoin.core.config import Settings
from spoin.generation.base import CardPlan
from spoin.generation.grounding import Grounding, GroundingOutcome
from spoin.generation.pipeline.nodes import _fit_round
from spoin.generation.pipeline.state import _Runtime

#: Two documents, each with several `##` sections. Enough that a declared scope is a
#: real restriction rather than "everything there is".
_DOCS: dict[str, list[tuple[str, str]]] = {
    "astro/stellar.md": [
        ("Hydrostatic Equilibrium", "Gravity inward balances the pressure gradient outward."),
        ("The Four Structure Equations", "Mass, pressure, luminosity and temperature, coupled."),
        ("Equations of State", "Gas, radiation and degeneracy pressure add together."),
    ],
    "astro/cosmology.md": [
        ("The Distance Ladder", "Parallax, then Cepheids, then Type Ia supernovae."),
        ("The Hubble Tension", "Early-universe and late-universe measurements disagree."),
    ],
}


def _plan(title: str, direction: str) -> CardPlan:
    return CardPlan(
        canonical_title=title,
        card_type="prose",
        asset_direction="",
        content_direction=direction,
    )


async def _seed_corpus(session: AsyncSession, embedder: Embedder) -> dict[str, uuid.UUID]:
    """Write `_DOCS`, and hand back each section's chunk id keyed by its ref."""

    now = datetime.now(UTC)
    by_ref: dict[str, uuid.UUID] = {}
    for path, sections in _DOCS.items():
        document = Document(
            title=f"Document {path}",
            source=f"https://example.invalid/{path}",
            source_path=path,
            kind=DocumentKind.TOPIC_SOURCE,
            category="astronomy",
            sub_category=None,
            scope=DocumentScope.SURVEY,
            content_hash=path,
            ingested_at=now,
        )
        session.add(document)
        await session.flush()
        for ordinal, (heading, body) in enumerate(sections):
            #: Mirrors what `contextual_text` stores: the header is part of the text AND
            #: `heading` is its own column, which is what a `<path>#<heading>` ref joins on.
            text = f"Document {path} — {heading}\n\n{body}"
            chunk = Chunk(
                document_id=document.id,
                ordinal=ordinal,
                text=text,
                heading=heading,
                embedding=embedder.embed_one_passage(text),
                embedding_model=embedder.model_name,
                topic_tags=["astronomy"],
            )
            session.add(chunk)
            await session.flush()
            by_ref[f"{path}#{heading}"] = chunk.id
    await session.commit()
    return by_ref


@pytest_asyncio.fixture
async def corpus_refs(
    universe_sessions: async_sessionmaker[AsyncSession],
    universe_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, uuid.UUID]]:
    """Seeded corpus, with `Grounding`'s session scope pointed at the test database."""

    refs = await _seed_corpus(universe_session, HashEmbedder(EMBEDDING_DIM))

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        async with universe_sessions() as session:
            yield session

    monkeypatch.setattr(grounding_module, "universe_session_scope", scope)
    yield refs


def _grounding(chunks: int = 2) -> Grounding:
    return Grounding(HashEmbedder(EMBEDDING_DIM), chunks=chunks)


# ----------------------------------------------------------------- scoping --


@pytest.mark.asyncio
async def test_retrieval_stays_inside_the_declared_scope(
    corpus_refs: dict[str, uuid.UUID],
) -> None:
    """The whole point: the author says which sections teach this tier, and ranking
    happens within them. A passage the curriculum did not name cannot reach a card."""

    scope = [
        "astro/stellar.md#Hydrostatic Equilibrium",
        "astro/stellar.md#The Four Structure Equations",
    ]
    context = await _grounding().for_cards(
        topic_name="Astronomy",
        subtopic_title="Stellar Structure",
        plans=[_plan("Hydrostatic equilibrium", "why a star does not collapse")],
        grounding_refs=scope,
    )

    assert context.outcome is GroundingOutcome.GROUNDED
    allowed = {corpus_refs[ref] for ref in scope}
    assert set(context.chunk_ids_by_index[0]) <= allowed
    assert context.allowance_used == 0
    #: Nothing from the document the tier did not name.
    assert corpus_refs["astro/cosmology.md#The Hubble Tension"] not in context.union


@pytest.mark.asyncio
async def test_no_declared_scope_falls_back_to_the_open_corpus(
    corpus_refs: dict[str, uuid.UUID],
) -> None:
    """`None` means "no declaration", which is the pre-existing open query -- distinct
    from a declaration that resolved to nothing."""

    context = await _grounding().for_cards(
        topic_name="Astronomy",
        subtopic_title="Cosmology",
        plans=[_plan("The Hubble tension", "why the two measurements disagree")],
        grounding_refs=None,
    )
    assert context.outcome is GroundingOutcome.GROUNDED
    assert context.allowance_used == 0
    assert context.union


@pytest.mark.asyncio
async def test_a_scope_too_small_to_fill_k_uses_the_allowance_and_counts_it(
    corpus_refs: dict[str, uuid.UUID],
) -> None:
    """The safety net, and the reason it is counted rather than silent: a tier that
    keeps falling back is reporting that its declaration is too narrow."""

    context = await _grounding(chunks=3).for_cards(
        topic_name="Astronomy",
        subtopic_title="Stellar Structure",
        plans=[_plan("Hydrostatic equilibrium", "why a star does not collapse")],
        grounding_refs=["astro/stellar.md#Hydrostatic Equilibrium"],
    )

    assert context.allowance_used == 1
    ids = context.chunk_ids_by_index[0]
    #: The declared section still comes first -- the allowance tops up, it does not
    #: replace.
    assert ids[0] == corpus_refs["astro/stellar.md#Hydrostatic Equilibrium"]
    assert len(ids) == 3


@pytest.mark.asyncio
async def test_a_scope_whose_refs_all_miss_degrades_to_the_open_query(
    corpus_refs: dict[str, uuid.UUID],
) -> None:
    """A renamed heading, or a corpus not re-ingested. The cards look the same as an
    undeclared tier's, which is exactly why `_scope_for` logs it at ERROR."""

    context = await _grounding().for_cards(
        topic_name="Astronomy",
        subtopic_title="Stellar Structure",
        plans=[_plan("Hydrostatic equilibrium", "why a star does not collapse")],
        grounding_refs=["astro/stellar.md#A Heading Nobody Wrote"],
    )
    assert context.outcome is GroundingOutcome.GROUNDED
    assert context.union


@pytest.mark.asyncio
async def test_a_prefix_of_a_real_heading_does_not_resolve(
    corpus_refs: dict[str, uuid.UUID],
) -> None:
    """`#Equations of State` must not be satisfied by `## The Four Structure Equations`,
    and `#The Four Structure` must not be satisfied by the section it is a prefix of.
    A join on the heading column, not a match against the front of `chunk.text`."""

    async with grounding_module.universe_session_scope() as session:
        resolved, missing = await grounding_module._resolve_scope(
            session, ["astro/stellar.md#The Four Structure"]
        )
    assert resolved == []
    assert missing == ["astro/stellar.md#The Four Structure"]


@pytest.mark.asyncio
async def test_resolution_reports_the_refs_that_missed(
    corpus_refs: dict[str, uuid.UUID],
) -> None:
    """Returned rather than logged and dropped: "the author scoped this narrowly" and
    "the scope evaporated" are different facts about a run."""

    async with grounding_module.universe_session_scope() as session:
        resolved, missing = await grounding_module._resolve_scope(
            session,
            [
                "astro/stellar.md#Equations of State",
                "astro/stellar.md#Gone",
                "not-a-ref-at-all",
            ],
        )
    assert resolved == [corpus_refs["astro/stellar.md#Equations of State"]]
    assert missing == ["astro/stellar.md#Gone", "not-a-ref-at-all"]


# ------------------------------------------------------------- per-card ids --


@pytest.mark.asyncio
async def test_each_card_cites_what_was_retrieved_for_it(
    corpus_refs: dict[str, uuid.UUID],
) -> None:
    """The citation ADR-0089 wanted: not "the passages this card's subtopic got", but
    the ones retrieved for THIS card. The prompt still carries one deduplicated block."""

    plans = [
        _plan("Hydrostatic equilibrium", "gravity against the pressure gradient"),
        _plan("The Hubble tension", "early and late universe measurements disagree"),
    ]
    context = await _grounding(chunks=1).for_cards(
        topic_name="Astronomy",
        subtopic_title="A survey tier",
        plans=plans,
        grounding_refs=None,
    )

    assert set(context.chunk_ids_by_index) == {0, 1}
    #: The union is what the prompt shows, and it is deduplicated -- so it is never
    #: larger than the sum of the per-card lists and usually smaller.
    total = sum(len(ids) for ids in context.chunk_ids_by_index.values())
    assert context.retrieved <= total
    assert set(context.union) == {
        chunk_id for ids in context.chunk_ids_by_index.values() for chunk_id in ids
    }


@pytest.mark.asyncio
async def test_a_card_with_no_brief_of_its_own_cites_the_block_it_read(
    corpus_refs: dict[str, uuid.UUID],
) -> None:
    """The writer is trusted for taste, never for constraints -- it can return more
    cards than briefs. An extra card cites the round's union rather than nothing, which
    is the honest answer: that block is what it was written from."""

    context = await _grounding().for_cards(
        topic_name="Astronomy",
        subtopic_title="Stellar Structure",
        plans=[_plan("Hydrostatic equilibrium", "gravity against pressure")],
        grounding_refs=None,
    )
    citations = context.chunk_ids_for(3)
    assert len(citations) == 3
    assert citations[0] == context.chunk_ids_by_index[0]
    assert citations[1] == context.union
    assert citations[2] == context.union


# -------------------------------------------------------------- batch size --


def _runtime(settings: Settings) -> _Runtime:
    """Only `settings` is read by `_fit_round`; the rest of the runtime is irrelevant."""

    return _Runtime.__new__(_Runtime)  # type: ignore[call-overload]


def test_a_round_is_capped_by_the_output_budget_not_the_count(settings: Settings) -> None:
    """The gotcha this exists for: a drafting response carries whole card bodies, and
    one truncated at the model's output cap fails to parse -- losing every card in the
    batch, not the overflow. Packing on the prompt side alone would not catch it."""

    tight = settings.model_copy(
        update={
            "generation_batch_size": 15,
            "mistral_max_output_tokens": 3600,
            "card_output_tokens_estimate": 900,
        }
    )
    runtime = _runtime(tight)
    object.__setattr__(runtime, "settings", tight)

    plans = [_plan(f"Concept {n}", f"angle {n}") for n in range(10)]
    first, deferred = _fit_round(runtime, plans)

    assert len(first) == 4  # 3600 // 900
    assert len(deferred) == 6
    #: Nothing is lost -- the overflow becomes the next round (ADR-0085's spillover).
    assert first + deferred == plans


def test_an_empty_round_is_left_alone(settings: Settings) -> None:
    runtime = _runtime(settings)
    object.__setattr__(runtime, "settings", settings)
    assert _fit_round(runtime, []) == ([], [])
