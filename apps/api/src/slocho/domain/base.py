"""Declarative base and the mixins every table reuses."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Naming convention so Alembic autogenerate produces stable, diffable constraint
# names instead of Postgres-assigned ones that churn between runs.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_ENUM_TYPES: dict[str, Enum] = {}


def pg_enum(python_enum: type[enum.Enum], name: str) -> Enum:
    """One shared type object per Postgres enum name.

    Two columns referencing the same enum (``card.difficulty`` and
    ``card.judged_difficulty``) must share the *same* type instance, or the schema
    emits ``CREATE TYPE difficulty`` twice and the migration fails.
    """

    if name not in _ENUM_TYPES:
        _ENUM_TYPES[name] = Enum(
            python_enum,
            name=name,
            values_callable=lambda e: [member.value for member in e],
        )
    return _ENUM_TYPES[name]


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
