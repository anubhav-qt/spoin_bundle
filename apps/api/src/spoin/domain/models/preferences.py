"""Server-stored appearance preferences (ADR-0070).

ADR-0045 kept the palette and font client-side in `localStorage`. ADR-0070
reverses that for those two, because F4/F5 turn them into user-authored content
(named saved themes, an imported font file) that must follow the user across
devices and reach the future mobile client. `localStorage` stays, demoted to a
pre-paint cache the client reconciles against these rows.

`daily_card_goal` (a scalar on `app_user`) and reduced-motion (still
`localStorage`) are unaffected — ADR-0045's split governs everything except the
palette and the font.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from spoin.domain.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey

#: Keep in step with the client. A built-in palette key, or `custom:<uuid>`
#: pointing into `custom_palettes`; a built-in font key, or `import:<uuid>`
#: pointing at a `user_font` row.
DEFAULT_PALETTE = "notebook"
DEFAULT_FONT = "literata"

#: The magic-number-sniffed formats an imported font may be. Not the request's
#: declared type — see `profile/fonts.py`, same reasoning as avatar images.
FONT_FORMATS = ("woff2", "ttf", "otf")


class UserPreference(Base, Timestamps):
    """One row per user, created lazily on first write. Absence means "this user
    has never changed an appearance setting" — the client falls back to its
    `localStorage` cache and then the built-in defaults.
    """

    __tablename__ = "user_preference"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        primary_key=True,
    )

    #: The active palette. NOT NULL with a default so a read never has to handle
    #: a partial row — a write always sets every scalar field.
    palette: Mapped[str] = mapped_column(
        String(64), nullable=False, default=DEFAULT_PALETTE, server_default=DEFAULT_PALETTE
    )

    #: The user's saved themes: `[{id, name, bg, fg, accent, accent2}]`. A
    #: `jsonb` document, not its own table, because it is a small
    #: (realistically < 20) always-read-and-written-whole list with no query
    #: needs of its own. Schema-checked by a Pydantic model at the API
    #: boundary (`api/schemas.py`), so Postgres seeing it as a document does
    #: not mean it is unvalidated — this is the one narrow relaxation of
    #: ADR-0045's "typed column, not a stringly-typed bag" rule.
    custom_palettes: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    #: The active font — a built-in key or `import:<user_font.id>`.
    font: Mapped[str] = mapped_column(
        String(64), nullable=False, default=DEFAULT_FONT, server_default=DEFAULT_FONT
    )


class UserFont(Base, UUIDPrimaryKey, CreatedAt):
    """An imported font file. Its own table, not a field on `user_preference`,
    because it carries a binary payload and a per-file lifecycle (uploaded,
    validated, referenced, deleted) — and because base64 in the preferences JSON
    would put megabytes on the `/auth/me` payload and defeat HTTP caching of the
    file itself.
    """

    __tablename__ = "user_font"
    __table_args__ = (
        CheckConstraint("format IN ('woff2', 'ttf', 'otf')", name="format_valid"),
        Index("ix_user_font_user_id", "user_id"),
    )

    #: Every read of this table is scoped to the caller in the query itself
    #: (`profile/fonts.py`) — a font id belonging to another user 404s, it is
    #: not merely hidden. First per-user binary the API serves, so the scoping
    #: is enforced twice (a router dependency AND `tests/test_architecture.py`).
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: Sniffed from the file's magic bytes at upload time, never taken from the
    #: multipart part's declared `content_type`.
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    #: The font file. Deferred for the same reason `User.avatar_image` is: the
    #: list endpoint and every `/auth/me` must be able to enumerate a user's
    #: fonts without pulling the payloads off the wire. Only
    #: `GET /profile/me/fonts/{id}` undefers it.
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    #: Denormalised so "how big" needs no blob load — matches the
    #: `has_avatar_image` pattern.
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
