"""The database refuses a vector that does not name the model that produced it.

Task 0039 is the bug this exists to make impossible: `SPOIN_EMBEDDER` never reached the
containers, every vector in `spoin_db_2` was `HashEmbedder` output, and nothing — no
query, no log line, no test — could tell, because a hash vector has the right dimension
and the wrong meaning. The `embedding_model` stamp is the fix; this is what stops the
tenth write site from forgetting it (ADR-0097).

Against the real Postgres `session` fixture rather than a mock, because the behaviour
under test **is** the database's: a `CheckConstraint` declared in `__table_args__` and
created by migration `b9876ddc6238`. Mocking here would assert that SQLAlchemy holds an
object in memory, which is not the claim.
"""

from __future__ import annotations

import uuid

import pytest
from frog.universe.models import EMBEDDING_DIM
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.domain.models import Topic

pytestmark = pytest.mark.asyncio

_VECTOR = [0.1] * EMBEDDING_DIM


def _topic(**kwargs: object) -> Topic:
    return Topic(slug=f"t-{uuid.uuid4().hex[:8]}", canonical_name="Stamp", **kwargs)


async def test_a_vector_without_a_model_is_rejected(session: AsyncSession) -> None:
    session.add(_topic(embedding=_VECTOR, embedding_model=None))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_model_without_a_vector_is_rejected(session: AsyncSession) -> None:
    """The other direction matters too: a stamp with no vector is a row claiming to
    have been embedded by a model it was never run through."""

    session.add(_topic(embedding=None, embedding_model="Qwen/Qwen3-Embedding-0.6B"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_neither_is_fine(session: AsyncSession) -> None:
    """An un-embedded row is ordinary, not an error — topics exist before anything
    embeds them, and 30 of 41 were in exactly that state when task 0039 was found."""

    session.add(_topic(embedding=None, embedding_model=None))
    await session.flush()


async def test_a_stamped_vector_is_fine(session: AsyncSession) -> None:
    session.add(_topic(embedding=_VECTOR, embedding_model="Qwen/Qwen3-Embedding-0.6B"))
    await session.flush()
