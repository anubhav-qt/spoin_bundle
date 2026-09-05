"""Retrieved corpus context, reused across a subtopic.

Shape and reasoning: docs/adr/0089-retrieval-grounded-generation.md.
`frog.retrieval` does the search; this module decides what a prompt actually gets.

**Two passages, asked for as two.** `Settings.grounding_chunks` is the `k` handed to
the database, not a cap applied to a wider result. There is no token budget and no
score floor — see that setting for why neither can earn its place: the ingestion
contract already bounds two passages at roughly 1200 prompt tokens, and the corpus
covers a topic before that topic is live. This module used to pack a top-10 result
down to a budget; that budget could never bind, which is the dead code `8a8e64c`
removed and this change stops recreating.

**Why this lives in `spoin` and not in `frog`.** It is prompt-shaped work — what a
generation prompt is given — which is this package's job rather than the search
package's. frog answers "what is most similar"; this decides what that is worth.

**Canon is not retrieved.** `generation/prompts/canon.py` pins it into every system
prompt as a fixed preamble (rag-design-space §3.9, amending ADR-0088), so retrieval
here asks for `topic_source` only and the whole budget goes to subject matter. Letting
canon compete for retrieval slots fails in both directions: it displaces facts the
model needed, and it is sometimes not retrieved at all for a call that needed it.

**Retrieval is per subtopic GROUP, not per call** (rag-design-space §3.7). The query
is known before generation and does not change within a subtopic — the drafter, the
redraft after a rejection, and the verifier grounding its check in the same passages
(ADR-0089) all want the same context. `Grounding` caches on that, which turns a
per-call cost into a per-subtopic one. Difficulty is deliberately NOT part of the
query or the key: difficulty-aware retrieval is rag-design-space §3.11 and is
deferred, and tier is a matter of how the card is WRITTEN, which is the prompt's job
(CLAUDE.md's trusted-for-taste-never-for-constraints split).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum

from frog.embeddings import Embedder
from frog.retrieval import Hit, corpus_version, search
from frog.universe.models import DocumentKind
from sqlalchemy.exc import SQLAlchemyError

from spoin.core.db import UniverseNotConfiguredError, universe_session_scope
from spoin.generation.load_balancer import estimate_tokens

logger = logging.getLogger(__name__)


class GroundingOutcome(StrEnum):
    """Why a call's prompt carries the context it carries.

    Three states rather than a bool, because CLAUDE.md's rule applies exactly here: a
    corpus that was searched and had nothing relevant is a **content** fact about the
    corpus, and a corpus that could not be reached is an **infrastructure** fact about
    this process. Folding them into "not grounded" is how a run of ungrounded cards
    gets read as a thin corpus when it was an unset environment variable — or worse,
    the reverse, with the corpus-authoring track sent to write material that was
    always there.
    """

    GROUNDED = "grounded"
    #: The corpus was searched and returned nothing to pack.
    NO_MATCH = "no_match"
    #: The corpus could not be searched at all. Never a statement about the corpus.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GroundingContext:
    """What one subtopic's retrieval produced, ready to drop into a prompt.

    Immutable and shared: the same instance is handed to every call in a subtopic
    group, including calls running concurrently on different tiers.
    """

    #: The prompt block, ready to interpolate. Empty string whenever `outcome` is not
    #: `GROUNDED`, so a prompt template can always interpolate it — the same
    #: empty-block-means-omitted convention `_format_builds_on` and friends use.
    block: str

    #: The chunks that produced `block`, in the order they appear in it. ADR-0089
    #: records these on the card so it can cite what grounded it — which is also what
    #: makes "which cards did this retracted chunk ground?" answerable
    #: (rag-design-space §3.12).
    chunk_ids: tuple[uuid.UUID, ...]

    outcome: GroundingOutcome

    #: `estimate_tokens(block)`. Carried rather than recomputed because it is what
    #: Phase 4 measures and what a caller logs; recomputing it at each call site is
    #: how two slightly different numbers end up in the same report.
    estimated_tokens: int

    #: How many hits the search returned before packing cut it to the budget. The
    #: gap between this and `len(chunk_ids)` is the only visible signal that the
    #: budget is binding, and it is the number Phase 4 wants.
    retrieved: int

    @classmethod
    def empty(cls, outcome: GroundingOutcome) -> GroundingContext:
        return cls(block="", chunk_ids=(), outcome=outcome, estimated_tokens=0, retrieved=0)


def build_query(topic_name: str, subtopic_title: str, subtopic_description: str) -> str:
    """The retrieval query for a subtopic.

    The description carries most of the signal — it is prose written for a model to
    read (`Subtopic.description`), not a label — and the topic name disambiguates a
    title that is only meaningful inside its topic ("Snapshots" under PostgreSQL
    versus under version control). Not normalized through
    `normalize_topic_text`: that normalizer exists to make two spellings of a topic
    NAME match (ADR-0093), and stripping punctuation from a sentence before embedding
    it discards signal the model was trained on.
    """

    return f"{topic_name}: {subtopic_title}. {subtopic_description}"


def render_block(hits: list[Hit]) -> str:
    """The retrieved passages as a prompt block, or `""` for no hits.

    Each passage is labelled with where it came from. That is not decoration: the
    verifier is asked to check a claim against a passage, and a passage the model
    cannot tell apart from the model's own memory is not evidence. The chunk text is
    interpolated whole, contextual header included — that header is what was embedded
    (task 0038 Phase 2) and stripping it makes two identically-worded sections
    indistinguishable.
    """

    if not hits:
        return ""
    passages = "\n\n".join(
        f"--- source {n + 1}: {hit.document_title} ({hit.source}) ---\n{hit.text}"
        for n, hit in enumerate(hits)
    )
    return (
        "\nSource material, retrieved for this subtopic. Everything factual you write "
        "must be supported by it; where it is silent, say less rather than filling the "
        "gap from memory:\n"
        f"{passages}\n"
    )


class Grounding:
    """Retrieval for a generation run, cached per subtopic group.

    One instance per run rather than a module-level singleton: the cache is only
    correct while the corpus is fixed, and tying its lifetime to a run makes that
    obvious. The corpus version is checked anyway (`corpus_version`), because the
    worker is long-lived and the owner re-ingests on the same machine while it runs.

    **Never raises.** A corpus that cannot be reached degrades to ungrounded
    generation, which is the pre-ADR-0089 behaviour and produces cards; a retrieval
    failure that aborted a run would trade every card for a missing environment
    variable. The reason is logged and reported in `GroundingContext.outcome` rather
    than swallowed — an ungrounded run has to be visible as one.
    """

    def __init__(self, embedder: Embedder, *, chunks: int) -> None:
        self._embedder = embedder
        self._chunks = chunks
        self._cache: dict[tuple[str, uuid.UUID], GroundingContext] = {}

    async def for_subtopic(
        self,
        *,
        subtopic_group_id: uuid.UUID,
        topic_name: str,
        subtopic_title: str,
        subtopic_description: str,
    ) -> GroundingContext:
        """Context for every call in this subtopic group, retrieved at most once.

        A miss is not cached: `UNAVAILABLE` is usually transient (the corpus database
        was restarting), and caching it would make one blip ground nothing for the
        rest of the run. `NO_MATCH` *is* cached — it is a fact about the corpus at
        this version, and re-asking will not change it.

        A cache hit still costs one `corpus_version` query, which is a count and a max
        over a few hundred rows. That is deliberately not optimised away: it is what
        makes the cache correct across a mid-run re-ingestion, and it is noise next to
        the LLM call this context is being assembled for.
        """

        try:
            async with universe_session_scope() as session:
                version = await corpus_version(session)
                key = (version, subtopic_group_id)
                cached = self._cache.get(key)
                if cached is not None:
                    return cached

                hits = await search(
                    session,
                    self._embedder,
                    build_query(topic_name, subtopic_title, subtopic_description),
                    #: Asked of the database as the final count, not trimmed to it
                    #: afterwards -- retrieving ten to keep two is nine wasted rows
                    #: per call and an invitation to re-rank in the application.
                    k=self._chunks,
                    #: Canon is pinned into the system prompt, not retrieved
                    #: (rag-design-space §3.9), so this is subject matter only.
                    kinds=[DocumentKind.TOPIC_SOURCE],
                )
        except UniverseNotConfiguredError:
            logger.warning("grounding unavailable: SPOIN_UNIVERSE_DATABASE_URL is not set")
            return GroundingContext.empty(GroundingOutcome.UNAVAILABLE)
        except SQLAlchemyError:
            logger.exception("grounding unavailable: the corpus database could not be read")
            return GroundingContext.empty(GroundingOutcome.UNAVAILABLE)

        context = self._context(hits)
        self._cache[key] = context
        return context

    def _context(self, hits: list[Hit]) -> GroundingContext:
        if not hits:
            return GroundingContext.empty(GroundingOutcome.NO_MATCH)
        block = render_block(hits)
        return GroundingContext(
            block=block,
            chunk_ids=tuple(hit.chunk_id for hit in hits),
            outcome=GroundingOutcome.GROUNDED,
            estimated_tokens=estimate_tokens(block),
            retrieved=len(hits),
        )
