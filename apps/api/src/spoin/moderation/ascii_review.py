"""Operator review of the ASCII scenes in one topic (ADR-0104).

Exists because ADR-0104 moved the art out of the model's hands and into the
library's, which changes who the last reviewer is. Before, art arrived
mangled and the answer was to reject the card and pay for another draft.
Now the drawing is always structurally sound -- copied byte for byte from a
hand-verified entry -- and the only thing left to judge is taste: does THIS
scene carry THIS card's idea, and do the overlay lines land.

That is a human call on a rendered picture, not something a gate can decide,
so it gets a page instead of a check. The two verdicts map onto what already
exists rather than inventing a second repair system: keeping a scene writes
the art back to the card, and rejecting one files an `art` report, which is a
`CardReportReason` the repair queue has handled since ADR-0076.

Mounted dev-only, like `/admin/repairs` -- same missing admin role (task
0035), and this one edits live card content.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.content.ascii_library import ASCII_MAX_WIDTH, entry_by_id
from spoin.domain.enums import CardReportReason, CardStatus, VisualKind
from spoin.domain.models import Card, Subtopic, Topic


class AsciiReviewService:
    """Read and edit the ASCII scenes of one topic's active cards."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _topic_by_slug(self, slug: str) -> Topic:
        topic = await self._session.scalar(select(Topic).where(Topic.slug == slug))
        if topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No topic {slug!r}")
        return topic

    async def list_scenes(self, topic_slug: str) -> list[dict[str, object]]:
        """Every ASCII-carrying active card in the topic, oldest first.

        Ordered by creation so a reviewer works through a generation run in the
        order it produced cards -- a run that went wrong went wrong in a streak,
        and seeing them adjacent is what makes the streak visible.
        """

        topic = await self._topic_by_slug(topic_slug)
        rows = (
            await self._session.execute(
                select(Card, Subtopic.title)
                .join(Subtopic, Subtopic.id == Card.subtopic_id, isouter=True)
                .where(
                    Card.topic_id == topic.id,
                    Card.status == CardStatus.ACTIVE,
                    Card.visual_kind == VisualKind.ASCII,
                )
                .order_by(Card.created_at.asc())
            )
        ).all()

        out: list[dict[str, object]] = []
        for card, subtopic_title in rows:
            slots = card.visual_slots or {}
            art = str(slots.get("art", ""))
            src_id = str(slots.get("src_id", "")) or None
            #: The library entry the scene came from, resolved for display so a
            #: reviewer can see what the drawing was BEFORE anyone edited it --
            #: the single most useful thing on the page when a scene looks wrong,
            #: because it answers "was this always like this" without a query.
            entry = entry_by_id(src_id) if src_id else None
            out.append(
                {
                    "card_id": card.id,
                    "title": card.title,
                    "canonical_title": card.canonical_title,
                    "summary": card.summary,
                    "difficulty": card.difficulty,
                    "subtopic_title": subtopic_title,
                    "art": art,
                    "alt": str(slots.get("alt", "")),
                    "src_id": src_id,
                    "library_title": entry.title if entry is not None else None,
                    "library_art": entry.art if entry is not None else None,
                    "widest_line": max((len(line) for line in art.split("\n")), default=0),
                    "max_width": ASCII_MAX_WIDTH,
                }
            )
        return out

    async def keep(self, card_id: uuid.UUID, art: str, alt: str) -> dict[str, object]:
        """Accept the scene, writing the operator's edit back to the card.

        Writes `art` VERBATIM, including a line over the column budget. The
        budget is enforced against the model, which cannot judge its own output;
        an operator looking at the rendered scene can, and a page that silently
        reflowed what they typed would be arguing with the person it exists to
        serve. The width is reported to them instead.
        """

        card = await self._require_ascii_card(card_id)
        slots = dict(card.visual_slots or {})
        slots["art"] = art
        slots["alt"] = alt
        #: Records that a human, not the pipeline, last set this art -- so a
        #: later regeneration or audit can tell an operator's deliberate
        #: edit from a generated scene and leave it alone.
        slots["edited_by_operator"] = "true"
        card.visual_slots = slots
        await self._session.commit()
        return {"card_id": card.id, "action": "kept"}

    async def send_to_repairs(
        self, card_id: uuid.UUID, user_id: uuid.UUID, note: str | None
    ) -> dict[str, object]:
        """Reject the scene by filing an `art` report on the card.

        Deliberately goes through the SAME queue as a reader's report rather
        than retiring the card here: the operator's judgement is evidence about
        the card, and `/admin/repairs` is where evidence about a card is acted
        on. Reusing it means one repair history per card instead of two.
        """

        from spoin.moderation.service import ModerationService

        await self._require_ascii_card(card_id)
        await ModerationService(self._session).report_card(
            user_id=user_id,
            card_id=card_id,
            reason=CardReportReason.ART,
            note=note or "Scene rejected in ASCII review",
        )
        return {"card_id": card_id, "action": "sent_to_repairs"}

    async def _require_ascii_card(self, card_id: uuid.UUID) -> Card:
        card = await self._session.get(Card, card_id)
        if card is None or card.status != CardStatus.ACTIVE:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such card")
        if card.visual_kind is not VisualKind.ASCII:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="That card carries no ASCII scene"
            )
        return card
