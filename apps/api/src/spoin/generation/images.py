"""Open-licensed photographs for IMAGE-type cards.

Two directions live here, and the second one replaced the first.

`reserve_images_for_plans` (ADR-0105) is the CURRENT path: a photograph is claimed
for each planned image card BEFORE the card is written, and its description is
briefed to the writer, so the card is written about the picture.

`assign_images` (ADR-0095, ADR-0102) is the OLD path: draft the card, then search
the catalog with the finished card's own text. It is kept for the repair flow, which
is genuinely retrofitting an image onto a card that already exists, and it is the
wrong shape for generation. Measured on 2026-09-07 it produced a photograph of Venus
for a card about Mercury's atmospheric loss and a nebula for one about elliptical
galaxy classification -- not because the retrieval was broken, but because the
catalog holds 76 photographs and most of what the corpus teaches (the Eddington
limit, the Sachs-Wolfe effect, the photon-to-baryon ratio) has no photograph
anywhere. A top-1 search always returns something; with `image_similarity_floor` at
0.0 that something always shipped.

Lives in `spoin` rather than `frog` because it is product-shaped work -- what a card
gets -- while frog answers only "what is most similar". Modeled on
`spoin.generation.grounding`.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field

from frog.embeddings import Embedder
from frog.retrieval import count_images, search_images
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.db import UniverseNotConfiguredError, session_scope, universe_session_scope
from spoin.domain.enums import CardStatus, VisualKind
from spoin.domain.models import Card
from spoin.generation.base import CardDraft, CardPlan, ReservedImage

logger = logging.getLogger(__name__)


@dataclass
class ImageAssignmentReport:
    """Outcome of attempting to assign images to a batch of card drafts."""

    assigned: int = 0
    no_candidate: int = 0
    below_floor: int = 0
    unavailable: int = 0
    scores: list[float] = field(default_factory=list)


async def topic_used_image_ids(session: AsyncSession, topic_id: uuid.UUID) -> set[uuid.UUID]:
    """Every image catalog UUID already used by an active card in this topic."""
    statement = select(Card.visual_id).where(
        Card.topic_id == topic_id,
        Card.status == CardStatus.ACTIVE,
        Card.visual_id.is_not(None),
    )
    results = (await session.execute(statement)).scalars().all()
    used: set[uuid.UUID] = set()
    for val in results:
        if val:
            try:
                used.add(uuid.UUID(val))
            except ValueError:
                # ASCII card scene ids are not UUIDs
                continue
    return used


async def count_available_images(
    session_scope_fn: (
        Callable[[], AbstractAsyncContextManager[AsyncSession]]
    ) = universe_session_scope,
    *,
    categories: Collection[str] | None = None,
    exclude_image_ids: Collection[uuid.UUID] | None = None,
) -> int:
    """How many images the ceiling may allow, or 0 when the catalog is unreachable.

    Zero on failure is the safe direction and the only one: the ceiling exists to stop
    a card being planned as an image card when no image can resolve, and such a card is
    rejected and regenerated forever (ADR-0066, ADR-0102). An unreachable catalog
    answering "plenty available" would walk straight into that loop.

    Catches exactly the two failures that mean the corpus is not there. Everything else
    propagates: a TypeError in this function is a bug, and reporting it as an empty
    catalog would silently turn every image card in the run into a prose card.
    """

    try:
        async with session_scope_fn() as session:
            return await count_images(
                session,
                categories=categories,
                exclude_image_ids=exclude_image_ids,
            )
    except UniverseNotConfiguredError:
        logger.warning("image ceiling: SPOIN_UNIVERSE_DATABASE_URL is not set")
        return 0
    except SQLAlchemyError:
        logger.exception("image ceiling: the corpus database could not be read")
        return 0


@dataclass
class ImageReservationReport:
    """Outcome of reserving photographs for a tier's planned image cards."""

    reserved: int = 0
    no_candidate: int = 0
    unavailable: int = 0
    scores: list[float] = field(default_factory=list)


async def reserve_images_for_plans(
    session_scope_fn: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    embedder: Embedder,
    *,
    topic_id: uuid.UUID,
    subtopic_title: str,
    subtopic_description: str,
    categories: Collection[str],
    plans: Sequence[CardPlan],
    db_session: AsyncSession | None = None,
) -> ImageReservationReport:
    """Claim one catalog photograph per planned image card, BEFORE writing (ADR-0105).

    The inversion of `assign_images`, and the reason it exists is in `ReservedImage`:
    matching a photograph to a finished card is a search for something the catalog
    mostly does not contain, while writing a card about a photograph the catalog
    definitely has cannot miss.

    **The query is the SUBTOPIC, not a card.** No card text exists yet -- that is the
    point -- so the retrieval asks "what does this catalog hold that is relevant to
    this subtopic", takes the best `len(plans)` of them, and hands one to each brief.
    Ordering is by score, so the strongest match is briefed first and a thin catalog
    degrades by reserving fewer cards rather than by reserving bad ones.

    **No similarity floor.** A floor is what ADR-0102 needed because a card had
    already been written and something had to decide whether the photograph was good
    enough for it. Here the card has not been written: any photograph in scope is one
    a good card can be written about, and the relevance the floor was protecting is
    supplied by writing the card about the picture. Scores are still recorded, because
    a subtopic whose best available image scores near zero is a signal that the
    catalog does not cover it.

    **Never raises**, the same contract as `assign_images` and `Grounding`: an
    unreachable catalog reserves nothing, and the plans it could not serve become
    prose briefs rather than losing the run.
    """

    report = ImageReservationReport()
    wanted = [p for p in plans if p.reserved_image is None]
    if not wanted:
        return report

    exclude_image_ids: set[uuid.UUID] = set()
    try:
        if db_session is not None:
            exclude_image_ids = await topic_used_image_ids(db_session, topic_id)
        else:
            async with session_scope() as session:
                exclude_image_ids = await topic_used_image_ids(session, topic_id)
    except SQLAlchemyError:
        logger.exception("image reservation: could not read the topic's used images")
        report.unavailable = len(wanted)
        return report

    query = f"{subtopic_title}. {subtopic_description}".strip()
    try:
        async with session_scope_fn() as universe:
            #: ONE query for the whole tier rather than one per card. Every brief in
            #: this tier is about the same subtopic, so they would all send the same
            #: query and differ only by what the previous card had already taken --
            #: which is exactly `k=len(wanted)` on a single call.
            hits = await search_images(
                universe,
                embedder,
                query,
                k=len(wanted),
                categories=categories,
                exclude_image_ids=exclude_image_ids,
                min_score=None,
            )
    except UniverseNotConfiguredError:
        logger.warning("image reservation unavailable: SPOIN_UNIVERSE_DATABASE_URL is not set")
        report.unavailable = len(wanted)
        return report
    except SQLAlchemyError:
        logger.exception("image reservation unavailable: the corpus database could not be read")
        report.unavailable = len(wanted)
        return report

    for plan, hit in zip(wanted, hits, strict=False):
        plan.reserved_image = ReservedImage(
            image_id=str(hit.image_id),
            title=hit.title,
            description=hit.description,
            score=hit.score,
            attribution=hit.attribution,
            display_url=hit.display_url,
            source_page=hit.source_page,
            licence=hit.licence.value,
        )
        report.scores.append(hit.score)
        report.reserved += 1
    report.no_candidate = len(wanted) - report.reserved
    return report


async def assign_images(
    session_scope_fn: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    embedder: Embedder,
    *,
    topic_id: uuid.UUID,
    categories: Collection[str],
    drafts: Sequence[CardDraft],
    min_score: float,
    db_session: AsyncSession | None = None,
) -> ImageAssignmentReport:
    """Attach a catalog image to each drafted image card (ADR-0095, ADR-0102).

    Runs AFTER drafting rather than at planning time because the query is the card own
    text, and a plan is a brief rather than a draft (ADR-0059). The model is never told
    images exist, so nothing it wrote is a request for one.

    **Uniqueness is a query, not caller-held state.** The exclusion set is read from the
    topic existing cards and then grown as this batch assigns, so two cards can never
    claim the same photograph without anything having to be locked.

    **Never raises**, the same contract as `Grounding`: an unreachable catalog degrades
    to unassigned drafts rather than losing the run. The four outcomes stay four
    separate counts, because a corpus that had nothing to offer, a match too weak to
    use, and a corpus that could not be reached are different facts, and folding them
    together is how "the catalog is thin" gets reported for an unset environment
    variable (CLAUDE.md).
    """
    report = ImageAssignmentReport()
    unassigned = [d for d in drafts if d.visual_id is None]
    if not unassigned:
        return report

    exclude_image_ids: set[uuid.UUID] = set()
    try:
        if db_session is not None:
            exclude_image_ids = await topic_used_image_ids(db_session, topic_id)
        else:
            async with session_scope() as session:
                exclude_image_ids = await topic_used_image_ids(session, topic_id)
    except SQLAlchemyError:
        #: Without the exclusion set every card in this batch races for the same best
        #: match, so this is not a degraded assignment -- it is no assignment.
        logger.exception("image assignment: could not read the topic's used images")
        report.unavailable = len(unassigned)
        return report

    #: Drafts already carrying an image -- a redraft round re-running over a batch --
    #: are excluded too, or the round hands out what it already handed out.
    for draft in drafts:
        if draft.visual_id:
            with contextlib.suppress(ValueError):
                exclude_image_ids.add(uuid.UUID(draft.visual_id))

    #: ONE session for the batch, not one per draft. The queries have to be sequential
    #: -- each card exclusion set depends on what the previous card took, which is what
    #: makes uniqueness a query instead of a lock -- but sequential is not a reason to
    #: open a connection per card, and 76 of them is what that would cost on astronomy.
    #: `Grounding` opens one the same way.
    try:
        async with session_scope_fn() as universe:
            for draft in unassigned:
                #: The card own text. `body` carries the substance the catalog
                #: description was written to be matched against; the titles keep a
                #: short body from matching on the wrong subject entirely.
                query = f"{draft.canonical_title}. {draft.summary} {draft.body}"
                hits = await search_images(
                    universe,
                    embedder,
                    query,
                    k=1,
                    categories=categories,
                    exclude_image_ids=exclude_image_ids,
                    #: Applied BELOW, not in the query, so a rejected match is still
                    #: scored and recorded. The floor is uncalibrated (ADR-0102) and
                    #: these scores are what will calibrate it -- filtering in SQL
                    #: would throw away the only evidence for setting it.
                    min_score=None,
                )
                if not hits:
                    report.no_candidate += 1
                    continue

                hit = hits[0]
                report.scores.append(hit.score)
                if hit.score < min_score:
                    report.below_floor += 1
                    continue

                draft.visual_id = str(hit.image_id)
                draft.visual_kind = VisualKind.IMAGE
                #: Everything the renderer needs, carried on the card. `attribution` is
                #: a licence CONDITION under CC BY and CC BY-SA, so it travels with the
                #: card rather than being fetched at render time -- a renderer that has
                #: to go and get it is one that ships without it once.
                draft.visual_slots = {
                    "title": hit.title,
                    #: The visible caption under the image, under the SAME key an
                    #: ASCII scene uses -- so the renderer captions both visuals through
                    #: one path instead of learning a second field name. The catalog
                    #: title is the caption: it was authored to name the photograph for
                    #: a reader, whereas `description` is the retrieval surface and runs
                    #: to several hundred characters of scene inventory.
                    "alt": hit.title,
                    "attribution": hit.attribution,
                    "display_url": hit.display_url,
                    "source_page": hit.source_page,
                    "licence": hit.licence.value,
                }
                exclude_image_ids.add(hit.image_id)
                report.assigned += 1
    except UniverseNotConfiguredError:
        logger.warning("image assignment unavailable: SPOIN_UNIVERSE_DATABASE_URL is not set")
        report.unavailable += len(unassigned) - report.assigned
    except SQLAlchemyError:
        logger.exception("image assignment unavailable: the corpus database could not be read")
        report.unavailable += len(unassigned) - report.assigned

    return report
