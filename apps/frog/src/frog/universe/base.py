"""Declarative base for `the_spoin_universe`.

Separate from `spoin.domain.base` by necessity, not by preference: ADR-0087 forbids
frog importing `spoin` at all. The naming convention below is copied deliberately
rather than shared — two databases with divergent constraint-naming rules produce
autogenerate diffs that churn, and a reader comparing the two schemas should not have
to hold two conventions in their head.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Identical to `spoin.domain.base.NAMING_CONVENTION`. Kept in step by hand; the
#: alternative is a shared package that both depend on, which is more machinery
#: than two dictionaries are worth.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
