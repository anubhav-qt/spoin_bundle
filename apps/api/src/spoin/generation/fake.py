"""Deterministic in-memory `ContentGenerator`.

This is the default everywhere except production. Tests and local development
never call a real model, never burn quota, and run in milliseconds — which is what
makes the "clone to running app in under 10 minutes" promise hold on a machine
with no API key.

Deterministic on purpose: same inputs, same output, so a test that depends on
generated text is not flaky.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

from spoin.domain.enums import CardType, Difficulty
from spoin.generation.base import (
    AsciiFetchQuery,
    AsciiFetchResult,
    AskTurnQuery,
    BatchResult,
    CardCorrectionQuery,
    CardCorrectionResult,
    CardDraft,
    CardPlan,
    CardRepairQuery,
    CardRepairResult,
    CardVerificationQuery,
    CardVerificationResult,
    ContentGenerator,
    CurriculumDraft,
    FreeTextGradeQuery,
    FreeTextGradeResult,
    QuestionDraft,
    SubtopicGroupDraft,
    SubtopicTierDraft,
    TopicMatchQuery,
    TopicMatchResult,
    TopicNameQuery,
    TopicNameVerdict,
)


def _stable_index(*parts: str, modulo: int) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:4], "big") % modulo


#: Distinct filler angles so fake card bodies in the same subtopic/difficulty
#: don't collide under the deterministic HashEmbedder used in tests (it's a
#: crude bag-of-words -- see embeddings/__init__.py -- so near-identical
#: placeholder text WOULD trip the near-duplicate gate on real generated
#: content, not just on genuinely-repetitive ones). Real generated prose
#: doesn't need this; this is purely a test-fixture concern.
_FAKE_ANGLES = [
    "how it behaves under load",
    "why it is designed this way",
    "a common mistake beginners make with it",
    "how to reason about its edge cases",
    "the tradeoff it makes against simpler alternatives",
    "how to explain it to someone new",
    "the mental model that makes it click",
    "how it composes with related concepts",
    "when not to reach for it",
    "a worked example most people skip",
]


class FakeContentGenerator(ContentGenerator):
    #: Deliberately failing one item per batch when asked. Partial failure is the
    #: normal case under ADR-0005, so the happy path should not be the only one
    #: that ever gets exercised.
    def __init__(
        self, *, fail_one_per_batch: bool = False, reject_one_per_verify_batch: bool = False
    ) -> None:
        self._fail_one = fail_one_per_batch
        #: Deliberately rejecting one item per `verify_cards` batch when asked
        #: -- ADR-0030's pass 2 CAN reject, and the happy path (accept
        #: everything) shouldn't be the only path a test ever exercises.
        self._reject_one = reject_one_per_verify_batch
        self._card_counter = 0
        self._plan_counter = 0

    async def generate_curriculum(
        self,
        topic_name: str,
        description: str,
        existing_subtopics: list[str] | None = None,
    ) -> CurriculumDraft:
        groups = [
            SubtopicGroupDraft(
                title=f"{topic_name}: part {n + 1}",
                tiers=[
                    SubtopicTierDraft(
                        difficulty=difficulty,
                        description=f"Placeholder curriculum slot {n + 1} for {topic_name}.",
                        target_cards=10,
                        card_type_quotas={
                            "prose": 2,
                            "code": 2,
                            "diagram": 2,
                            "comparison": 2,
                            "ascii": 2,
                        },
                    )
                    for difficulty in Difficulty
                ],
                position=n,
            )
            for n in range(3)
        ]
        if existing_subtopics:
            # Deterministically "decide" the first already-existing subtopic is
            # the same as its own first group, reusing the EXACT title verbatim —
            # simulates the real prevention behavior (generate_curriculum's
            # docstring) so a test can assert the pipeline's persistence step
            # actually reuses that row instead of forking a duplicate.
            reused_title = existing_subtopics[0].split(" :: ", 1)[0]
            groups[0].title = reused_title
        return CurriculumDraft(subtopics=groups)

    async def match_topics(self, queries: list[TopicMatchQuery]) -> BatchResult[TopicMatchResult]:
        # Deterministic stand-in for an LLM opinion: the highest-similarity
        # candidate "matches" above a fixed cutoff. This is the FAKE's own
        # simulated judgment, not a system threshold — ADR-0025 removed those.
        items = []
        for query in queries:
            best = max(query.candidates, key=lambda c: c.similarity, default=None)
            matched = best.topic_id if best is not None and best.similarity >= 0.9 else None
            items.append(
                TopicMatchResult(request_index=query.request_index, matched_topic_id=matched)
            )
        return BatchResult(items=items)

    async def validate_topic_names(
        self, queries: list[TopicNameQuery]
    ) -> BatchResult[TopicNameVerdict]:
        # Deterministic stand-in for the LLM's judgment call: accepts
        # everything except a fixed marker string, so a test can exercise
        # the rejection path without depending on real model behavior.
        items = [
            TopicNameVerdict(
                request_index=query.request_index,
                acceptable="trolltest" not in query.name.lower(),
                reason="" if "trolltest" not in query.name.lower() else "simulated rejection",
            )
            for query in queries
        ]
        return BatchResult(items=items)

    async def plan_cards(
        self,
        *,
        topic_name: str,
        subtopic_title: str,
        subtopic_description: str,
        difficulty: Difficulty,
        count: int,
        type_quotas: dict[str, int],
        existing_titles: list[str],
        builds_on: list[str],
        avoid_bodies: list[str],
        rejection_feedback: list[tuple[str, str]],
        grounding: str = "",
    ) -> BatchResult[CardPlan]:
        """Hands back exactly `count` briefs whose type mix honours `type_quotas`
        (ADR-0059), so a test exercising the planned path gets the same shape
        distribution the real planner is asked for -- the caller's quota
        accounting is what's usually under test, not the plan's prose."""

        wanted = [ct for ct, qty in type_quotas.items() for _ in range(max(0, qty))]
        items: list[CardPlan] = []
        for n in range(count):
            self._plan_counter += 1
            idx = self._plan_counter
            chosen = wanted[n] if n < len(wanted) else CardType.PROSE.value
            items.append(
                CardPlan(
                    canonical_title=f"{subtopic_title}: planned concept {idx}",
                    card_type=chosen,
                    asset_direction=(
                        "" if chosen == CardType.PROSE.value else f"a {chosen} showing case {idx}"
                    ),
                    content_direction=(
                        f"angle {idx}: {_FAKE_ANGLES[idx % len(_FAKE_ANGLES)]}, "
                        f"distinct from the other planned cards"
                    ),
                )
            )
        return BatchResult(items=items)

    async def fetch_ascii_scenes(
        self,
        queries: list[AsciiFetchQuery],
        *,
        topic_name: str,
        subtopic_title: str,
        difficulty: Difficulty,
        exclude_ids: frozenset[str],
    ) -> BatchResult[AsciiFetchResult]:
        """Deterministic stand-in (ADR-0080): "matches" every query to a stable
        fake library id and hands back a tiny captioned scene, so the planned-
        ascii path (fetcher owns the art) is what tests exercise by default.
        Honours `exclude_ids` so a test can assert per-topic non-repetition --
        an id already used yields `no_match` for that query instead."""

        items: list[AsciiFetchResult] = []
        for q in queries:
            src_id = f"fake-lib-{_stable_index(q.canonical_title, modulo=997)}"
            if src_id in exclude_ids:
                items.append(AsciiFetchResult(index=q.index, matched=False))
                continue
            items.append(
                AsciiFetchResult(
                    index=q.index,
                    matched=True,
                    src_id=src_id,
                    label=f"fake-scene-{q.index}",
                    art=f'  o    "{q.asset_direction[:24] or "gag"}"\n /|\\\n / \\',
                    alt=f"Stick figure acting out: {q.canonical_title}",
                )
            )
        return BatchResult(items=items)

    async def generate_cards(
        self,
        *,
        topic_name: str,
        subtopic_title: str,
        subtopic_description: str,
        difficulty: Difficulty,
        count: int,
        existing_titles: list[str],
        builds_on: list[str],
        difficulty_examples: dict[Difficulty, list[str]],
        avoid_bodies: list[str],
        rejection_feedback: list[tuple[str, str]],
        want_hero: bool = False,
        card_type: CardType | str | None = None,
        plans: list[CardPlan] | None = None,
        grounding: str = "",
    ) -> BatchResult[CardDraft]:
        builds_on_note = f" Builds on {len(builds_on)} lower-tier card(s)." if builds_on else ""

        items: list[CardDraft] = []
        for n in range(count):
            self._card_counter += 1
            idx = self._card_counter
            extra_body = ""
            visual_id = None
            visual_slots = None

            # ADR-0080: a planned ascii card whose fetcher matched carries its
            # scene on the plan; the writer (this call) does NOT redraw it.
            plan = plans[n] if plans is not None and n < len(plans) else None
            fetched = plan.fetched_scene if plan is not None else None

            if fetched is not None:
                visual_id = fetched.label
                visual_slots = {
                    "art": fetched.art,
                    "alt": fetched.alt,
                    "src_id": fetched.src_id,
                }
            elif card_type in (CardType.ASCII, "ascii") or want_hero:
                visual_id = f"fake-ascii-scene-{idx}"
                visual_slots = {
                    "art": f'  o   "Check this #{idx}!"\n /|\\\n / \\',
                    "alt": f"Stick figure explaining scenario {idx}",
                }
            elif card_type in (CardType.COMPARISON, "comparison"):
                extra_body = (
                    f"\n\n❌ **Common Myth #{idx}**: Misconception {idx} about this topic.\n"
                    f"✅ **True Fact #{idx}**: Verified behavior for {idx}.\n"
                )
            elif card_type in (CardType.CODE, "code"):
                extra_body = (
                    f"\n\n```python\ndef handle_operation_{idx}():\n"
                    f"    return 'result_{idx}'\n```\n"
                )
            elif card_type in (CardType.DIAGRAM, "diagram"):
                extra_body = (
                    f"\n\n```diagram\n[Source_{idx}] --> [Process_{idx}] --> [Sink_{idx}]\n```\n"
                )

            angle = _FAKE_ANGLES[(idx - 1) % len(_FAKE_ANGLES)]
            items.append(
                CardDraft(
                    title=(
                        f"{subtopic_title} — the big idea"
                        if want_hero
                        else f"{subtopic_title} — note {idx}"
                    )[:120],
                    canonical_title=f"{subtopic_title}: note {idx}"[:160],
                    summary=f"A placeholder hook for {subtopic_title} at {difficulty.value} level.",
                    body=(
                        f"# {subtopic_title}\n\n"
                        f"Card {idx} on **{topic_name}** ({difficulty.value}): "
                        f"{angle}.{builds_on_note}{extra_body}\n"
                    ),
                    difficulty=difficulty,
                    visual_id=visual_id,
                    visual_slots=visual_slots,
                    is_hero=want_hero,
                )
            )

        failures = []
        if self._fail_one and items:
            items.pop()
            failures.append("simulated malformed item")
        return BatchResult(items=items, failures=failures)

    async def correct_cards(
        self,
        queries: list[CardCorrectionQuery],
        *,
        difficulty_examples: dict[Difficulty, list[str]],
        grounding: str = "",
    ) -> BatchResult[CardCorrectionResult]:
        # Deterministic pass-through: the fake never finds anything to fix.
        # Correction-behavior itself is exercised by tests that construct their
        # own generator subclass or stub, not by this default.
        return BatchResult(
            items=[
                CardCorrectionResult(
                    index=query.index,
                    title=query.title,
                    canonical_title=query.canonical_title,
                    summary=query.summary,
                    body=query.body,
                    was_edited=False,
                )
                for query in queries
            ]
        )

    async def verify_cards(
        self,
        queries: list[CardVerificationQuery],
        *,
        difficulty_examples: dict[Difficulty, list[str]],
        grounding: str = "",
    ) -> BatchResult[CardVerificationResult]:
        items = [
            CardVerificationResult(
                index=query.index,
                accepted=True,
                confirmed_difficulty=query.requested_difficulty,
            )
            for query in queries
        ]
        if self._reject_one and items:
            first = items[0]
            items[0] = CardVerificationResult(
                index=first.index,
                accepted=False,
                confirmed_difficulty=first.confirmed_difficulty,
                reason="simulated verification rejection",
            )
        return BatchResult(items=items)

    async def generate_questions(
        self,
        cards: list[tuple[str, str]],
        difficulty: Difficulty,
        *,
        existing_stems: list[str],
        is_backfill: bool,
        grounding: str = "",
    ) -> BatchResult[QuestionDraft]:
        items: list[QuestionDraft] = []
        for index, (title, _body) in enumerate(cards):
            if index == len(cards) - 1:
                # 9 MCQ + 1 free text (ADR-0009).
                items.append(
                    QuestionDraft(
                        card_index=index,
                        stem=f"In your own words, explain {title}.",
                        rubric="0 none / 1 surface / 2 solid / 3 deep",
                        reference_answer=f"A correct account of {title}.",
                    )
                )
            else:
                items.append(
                    QuestionDraft(
                        card_index=index,
                        stem=f"Which statement about {title} is correct?",
                        options=[f"Option {n}" for n in range(4)],
                        correct_index=_stable_index(title, modulo=4),
                        explanation=f"See the card '{title}'.",
                    )
                )
        return BatchResult(items=items)

    async def grade_free_text(
        self, items: list[FreeTextGradeQuery]
    ) -> BatchResult[FreeTextGradeResult]:
        # Deterministic stand-in for judgment: length of the (stripped) answer
        # is a stable, inspectable proxy for "did they write something real,"
        # which is all a fake grader needs to be useful in tests — an empty or
        # near-empty answer always grades 0, never a coincidence of hashing.
        results = []
        for item in items:
            answer = item.user_answer.strip()
            level = 0 if not answer else 1 + _stable_index(item.stem, answer, modulo=3)
            results.append(
                FreeTextGradeResult(
                    index=item.index,
                    rubric_level=level,
                    justification=(
                        f"Placeholder grade referencing '{item.stem[:40]}': "
                        f"answer length {len(answer)} chars."
                    ),
                )
            )
        return BatchResult(items=results)

    async def repair_card_structure(
        self, queries: list[CardRepairQuery]
    ) -> BatchResult[CardRepairResult]:
        # Echo the card back unchanged except for a marker in `note`. A test that
        # wants a specific repaired body stubs this method; the default just has
        # to be well-formed and deterministic.
        items = [
            CardRepairResult(
                index=q.index,
                title=q.title,
                canonical_title=q.canonical_title,
                summary=q.summary,
                body=q.body,
                visual_slots=q.visual_slots,
                note="fake repair: returned the card unchanged",
            )
            for q in queries
        ]
        return BatchResult(items=items)

    async def stream_topic_answer(self, query: AskTurnQuery) -> AsyncIterator[str]:
        # Deterministic two-chunk stream, echoing the topic + turn count so a
        # test can assert the wiring end to end. `_stable_index` keeps it
        # varying without randomness.
        marker = _stable_index(query.topic_name, query.question, modulo=1000)
        turn = len(query.history) // 2 + 1
        for chunk in (
            f"On {query.topic_name} (turn {turn}): ",
            f"placeholder answer #{marker} drawn from the supplied context.",
        ):
            yield chunk
