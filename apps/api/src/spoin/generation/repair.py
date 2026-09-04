"""ADR-0076: execute one `kind='repair'` generation job.

Runs in the worker, never in a request. `run_card_repair` owns its session and
every `CardRepair` / `Card` write; the worker's `_run_job` only sets the
surrounding `GenerationJob` status. A structural-check or gate rejection is a
recorded `FAILED` repair, not a raised exception -- the card is left as it was
and reappears on the admin page.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

from frog.embeddings import Embedder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from spoin.content.archetype import classify_archetype
from spoin.core.db import session_scope
from spoin.domain.enums import CardStatus, RepairMode, RepairStatus
from spoin.domain.models import Card, CardRepair, CardReport, Subtopic, Topic
from spoin.generation.base import (
    CardCorrectionQuery,
    CardRepairQuery,
    CardVerificationQuery,
    ContentGenerator,
)
from spoin.generation.quota import QuotaExhaustedError
from spoin.moderation.service import mark_card_reports_resolved

logger = logging.getLogger("spoin.generation.repair")

_ASCII_MAX_WIDTH = 40
_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
#: A code fence whose language tag marks it as real code (not a diagram/ascii
#: block). Mirrors `content/archetype.py`'s `_DIAGRAM_LANG_TAGS` inverse.
_CODE_LANGS_EXEMPT = {"", "diagram", "text", "ascii", "mermaid"}


def _code_langs(body: str) -> set[str]:
    return {
        lang.strip().lower()
        for lang, _content in _FENCE.findall(body)
        if lang.strip().lower() not in _CODE_LANGS_EXEMPT
    }


def _structural_issue(
    original_body: str, result_body: str, visual_slots: dict[str, str] | None
) -> str | None:
    """Deterministic checks a repaired card must pass (ADR-0076). Structure
    only -- meaning is the operator's review, not this function's."""

    art = (visual_slots or {}).get("art", "")
    if art:
        over = [len(line) for line in art.splitlines() if len(line) > _ASCII_MAX_WIDTH]
        if over:
            return f"ASCII art still exceeds {_ASCII_MAX_WIDTH} columns (widest line {max(over)})"

    added = _code_langs(result_body) - _code_langs(original_body)
    if added:
        joined = ", ".join(sorted(added))
        return f"repair added a code fence ({joined}) absent from the original"

    for match in _FENCE.finditer(result_body):
        if match.group(1).strip().lower() != "mermaid":
            continue
        tail = result_body[match.end() : match.end() + 400].lstrip("\n")
        first_line = tail.split("\n", 1)[0].strip()
        captioned = first_line.startswith(("*", "_")) or first_line.lower().startswith(
            ("figure", "diagram")
        )
        if not captioned:
            return "a ```mermaid``` diagram has no one-line caption after it (F3)"

    return None


async def _mint_new_version(
    session: AsyncSession,
    embedder: Embedder,
    old: Card,
    *,
    title: str,
    canonical_title: str,
    summary: str,
    body: str,
    visual_slots: dict[str, str] | None,
    judged_difficulty: object,
    repair_mode: str,
) -> Card:
    """A new ACTIVE row in `old`'s family; `old` -> SUPERSEDED. The partial
    unique index (`uq_card_family_id_active`) enforces the one-active invariant,
    so both writes must land in the same transaction."""

    embedding = (await embedder.aembed_passage([body]))[0]
    new_card = Card(
        family_id=old.family_id,
        version=old.version + 1,
        topic_id=old.topic_id,
        subtopic_id=old.subtopic_id,
        difficulty=old.difficulty,
        judged_difficulty=judged_difficulty or old.judged_difficulty,
        status=CardStatus.ACTIVE,
        title=title[:120],
        canonical_title=canonical_title[:160],
        summary=summary,
        body=body,
        archetype=classify_archetype(body),
        visual_id=old.visual_id,
        visual_slots=visual_slots,
        is_hero=old.is_hero,
        content_embedding=embedding,
        gen_meta={
            **(old.gen_meta or {}),
            "repaired_from": str(old.id),
            "repair_mode": repair_mode,
            "repaired_at": datetime.now(UTC).isoformat(),
        },
    )
    old.status = CardStatus.SUPERSEDED
    session.add(new_card)
    await session.flush()
    return new_card


async def run_card_repair(
    job_id: uuid.UUID,
    card_id: uuid.UUID,
    generator: ContentGenerator,
    embedder: Embedder,
) -> None:
    async with session_scope() as session:
        repair = await session.scalar(
            select(CardRepair)
            .where(CardRepair.job_id == job_id)
            .options(undefer(CardRepair.source_image))
        )
        card = await session.get(Card, card_id)
        if repair is None or card is None:
            logger.warning("repair job %s: no CardRepair row or card -- nothing to do", job_id)
            return
        if card.status != CardStatus.ACTIVE:
            repair.status = RepairStatus.FAILED
            repair.error = f"card is {card.status.value}, not active -- nothing to repair"
            repair.resolved_at = datetime.now(UTC)
            return

        repair.status = RepairStatus.RUNNING
        await session.flush()

        topic = await session.get(Topic, card.topic_id)
        subtopic = await session.get(Subtopic, card.subtopic_id)
        assert topic is not None and subtopic is not None

        try:
            if repair.mode == RepairMode.FIX:
                new_card = await _run_fix(session, generator, embedder, card, repair, topic)
            else:
                new_card = await _run_remake(
                    session, generator, embedder, card, repair, topic, subtopic
                )
        except QuotaExhaustedError:
            # Roll back everything (incl. status=RUNNING) and let the job requeue.
            raise

        if new_card is None:
            # `repair` already carries FAILED + error.
            return

        repair.status = RepairStatus.DONE
        repair.result_card_id = new_card.id
        repair.resolved_at = datetime.now(UTC)
        await mark_card_reports_resolved(session, card_id)
        logger.info(
            "repair job %s: %s -> card %s (v%d)",
            job_id,
            repair.mode.value,
            new_card.id,
            new_card.version,
        )


async def _run_fix(
    session: AsyncSession,
    generator: ContentGenerator,
    embedder: Embedder,
    card: Card,
    repair: CardRepair,
    topic: Topic,
) -> Card | None:
    notes = list(
        (
            await session.execute(
                select(CardReport.note).where(
                    CardReport.card_id == card.id,
                    CardReport.resolved_at.is_(None),
                    CardReport.note.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    query = CardRepairQuery(
        index=0,
        topic_name=topic.canonical_name,
        topic_description=topic.description or "",
        reason_notes=[n for n in notes if n],
        operator_guidance=repair.guidance,
        title=card.title,
        canonical_title=card.canonical_title,
        summary=card.summary,
        body=card.body,
        visual_id=card.visual_id,
        visual_slots=card.visual_slots,
        image_png=repair.source_image,
    )
    result = await generator.repair_card_structure([query])
    if not result.items:
        repair.status = RepairStatus.FAILED
        repair.error = "repair call returned nothing: " + "; ".join(result.failures)[:1500]
        repair.resolved_at = datetime.now(UTC)
        return None

    repaired = result.items[0]
    issue = _structural_issue(card.body, repaired.body, repaired.visual_slots)
    if issue is not None:
        repair.status = RepairStatus.FAILED
        repair.error = f"structural check failed: {issue}"
        repair.resolved_at = datetime.now(UTC)
        return None

    return await _mint_new_version(
        session,
        embedder,
        card,
        title=repaired.title or card.title,
        canonical_title=repaired.canonical_title or card.canonical_title,
        summary=repaired.summary or card.summary,
        body=repaired.body,
        visual_slots=repaired.visual_slots,
        judged_difficulty=None,
        repair_mode="fix",
    )


async def _run_remake(
    session: AsyncSession,
    generator: ContentGenerator,
    embedder: Embedder,
    card: Card,
    repair: CardRepair,
    topic: Topic,
    subtopic: Subtopic,
) -> Card | None:
    brief = (
        f"{subtopic.description}\n\nOPERATOR INSTRUCTION -- this card is being "
        f"regenerated from scratch. Make it as follows: {repair.guidance}"
    )
    drafted = await generator.generate_cards(
        topic_name=topic.canonical_name,
        subtopic_title=subtopic.title,
        subtopic_description=brief,
        difficulty=card.difficulty,
        count=1,
        existing_titles=[],
        builds_on=[],
        difficulty_examples={},
        avoid_bodies=[card.body],
        rejection_feedback=[],
    )
    if not drafted.items:
        repair.status = RepairStatus.FAILED
        repair.error = "remake produced no draft: " + "; ".join(drafted.failures)[:1500]
        repair.resolved_at = datetime.now(UTC)
        return None
    draft = drafted.items[0]

    corrected = await generator.correct_cards(
        [
            CardCorrectionQuery(
                index=0,
                topic_name=topic.canonical_name,
                topic_description=topic.description or "",
                title=draft.title,
                canonical_title=draft.canonical_title,
                summary=draft.summary,
                body=draft.body,
            )
        ],
        difficulty_examples={},
    )
    fixed = corrected.items[0] if corrected.items else None
    title = fixed.title if fixed else draft.title
    canonical_title = fixed.canonical_title if fixed else draft.canonical_title
    summary = fixed.summary if fixed else draft.summary
    body = fixed.body if fixed else draft.body

    verdicts = await generator.verify_cards(
        [
            CardVerificationQuery(
                index=0,
                canonical_title=canonical_title,
                body=body,
                requested_difficulty=card.difficulty,
            )
        ],
        difficulty_examples={},
    )
    verdict = verdicts.items[0] if verdicts.items else None
    if verdict is None or not verdict.accepted:
        repair.status = RepairStatus.FAILED
        repair.error = "remade card rejected by the quality gate: " + (
            verdict.reason if verdict else "no verdict returned"
        )
        repair.resolved_at = datetime.now(UTC)
        return None

    return await _mint_new_version(
        session,
        embedder,
        card,
        title=title,
        canonical_title=canonical_title,
        summary=summary,
        body=body,
        visual_slots=card.visual_slots,
        judged_difficulty=verdict.confirmed_difficulty,
        repair_mode="remake",
    )
