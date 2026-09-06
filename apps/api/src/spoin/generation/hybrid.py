"""`HybridContentGenerator`: prose on Mistral, verdicts on Gemini.

ADR-0090. **The split is by what a call PRODUCES** -- a call that produces a verdict
runs on Gemini's thinking cells, a call that produces prose runs on Mistral -- and that
is already exactly the ladder split (`"generator"` vs `"thinking"`) every call in
`GeminiContentGenerator` passes to `_invoke_with_retry`. So the routing table is not a
second hand-written list that can drift from the ladder; it *is* the ladder, read at
the one place every call funnels through:

    plan_cards, fetch_ascii_scenes (+ redraw), generate_cards,
    correct_cards, generate_questions, repair_card_structure   -> "generator" -> Mistral
    match_topics, validate_topic_names, verify_cards,
    grade_free_text                                            -> "thinking"  -> Gemini

ADR-0090 rejected "route by a hand-written method list" for this reason: the ladder
split already carries the reasoning, and a second list would drift from it.

Subclassing rather than composing is what makes that true. Every prompt, every wire
model, every parse and every `BatchResult` failure path is inherited verbatim -- the
subclass changes the transport for one ladder and nothing else, so there is no second
copy of `generate_cards`'s prompt selection to keep in step.

**Two calls stay on Gemini despite producing prose**, and both are deliberate:

- `stream_topic_answer` (AskAI). ADR-0090's stated capacity-allocation exception: it is
  the one user-facing, latency-visible call, and it is low volume. It streams and never
  goes through `_invoke_with_retry`, so it stays on Gemini by construction.
- Any prompt carrying an image. `repair_card_structure` (ADR-0076) sends the card's
  rendered PNG as a multimodal part, and `ministral-8b` is text-only. ADR-0090's table
  puts repair on Mistral; that is right about the *kind* of work and wrong about this
  model's capability, so the transport check below wins. A repair that silently lost
  the image it was asked to look at would produce a plausible fix for something the
  model never saw.

**No cross-provider fallback.** A Mistral failure raises and the caller counts it as a
call failure. It never becomes a Gemini call: an outage that quietly turns into a Gemini
bill is a corpus you cannot attribute afterwards.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from pydantic import BaseModel

from spoin.core.config import Settings
from spoin.generation.langchain_impl import GeminiContentGenerator
from spoin.generation.load_balancer import LadderKind
from spoin.generation.mistral import MistralClient

logger = logging.getLogger(__name__)

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)


class HybridContentGenerator(GeminiContentGenerator):
    """`GeminiContentGenerator` with the generator ladder's transport swapped."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._mistral = MistralClient(settings)

    async def aclose(self) -> None:
        await self._mistral.aclose()

    async def _invoke_with_retry(
        self,
        kind: LadderKind,
        schema: type[_SchemaT],
        prompt: list[tuple[str, Any]],
    ) -> _SchemaT:
        if kind != "generator" or _has_image(prompt):
            #: Gemini's whole apparatus -- box leasing, the load balancer, the rung
            #: ladder, the 429 classification -- is untouched and still schedules
            #: every call that lands here. ADR-0084 remains what runs the thinkers.
            return await super()._invoke_with_retry(kind, schema, prompt)

        #: Mistral's admission control is the client's semaphore and nothing else.
        #: No box is claimed, no cell is assigned, no quota row is written -- the
        #: sweep measured no concurrency wall to defend against (ADR-0090).
        return await self._mistral.invoke(schema, prompt)


def _has_image(prompt: list[tuple[str, Any]]) -> bool:
    """Whether any message carries a non-text part.

    A multimodal message is a `list` of content dicts rather than a `str` (see
    `repair_card_structure`), so this is a shape check rather than a scan for a
    particular key -- a future multimodal call gets routed correctly without anyone
    remembering to update a list here.
    """

    for _role, content in prompt:
        if isinstance(content, str):
            continue
        if not isinstance(content, list):
            return True
        if any(
            isinstance(part, dict) and part.get("type") not in (None, "text") for part in content
        ):
            return True
    return False
