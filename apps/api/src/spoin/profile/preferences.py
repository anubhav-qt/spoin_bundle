"""Appearance-preferences read/write (ADR-0070).

A focused service rather than more methods on `ProfileService`: the palette, the
saved-theme list and the imported fonts are one coherent surface with its own
lifecycle. Every font query here filters by `user_id` in the SQL itself — a font
id belonging to another user is a 404, not a hidden row (`tests/test_architecture.py`
enforces that the filter is present).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from spoin.api.schemas import (
    CustomPalette,
    ImportedFontOut,
    PreferencesOut,
    PreferencesUpdateIn,
)
from spoin.domain.models.preferences import (
    DEFAULT_FONT,
    DEFAULT_PALETTE,
    UserFont,
    UserPreference,
)
from spoin.profile.fonts import ValidatedFont

_FONT_MEDIA_TYPE = {"woff2": "font/woff2", "ttf": "font/ttf", "otf": "font/otf"}
#: A generous ceiling on saved themes — the picker's fixed-height grid scrolls
#: well before this, and the JSON column has no business holding hundreds.
_MAX_CUSTOM_PALETTES = 50


class PreferencesService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _fonts(self, user_id: UUID) -> list[ImportedFontOut]:
        rows = (
            await self._session.execute(
                select(UserFont).where(UserFont.user_id == user_id).order_by(UserFont.created_at)
            )
        ).scalars()
        return [
            ImportedFontOut(id=r.id, name=r.name, format=r.format, byte_size=r.byte_size)
            for r in rows
        ]

    async def get(self, user_id: UUID) -> PreferencesOut:
        """The user's preferences, or the built-in defaults when they have never
        written one. `imported_fonts` is metadata only — no blobs."""

        row = await self._session.get(UserPreference, user_id)
        fonts = await self._fonts(user_id)
        if row is None:
            return PreferencesOut(
                palette=DEFAULT_PALETTE,
                custom_palettes=[],
                font=DEFAULT_FONT,
                imported_fonts=fonts,
            )
        return PreferencesOut(
            palette=row.palette,
            custom_palettes=[CustomPalette(**p) for p in row.custom_palettes],
            font=row.font,
            imported_fonts=fonts,
        )

    async def update(self, user_id: UUID, data: PreferencesUpdateIn) -> PreferencesOut:
        if len(data.custom_palettes) > _MAX_CUSTOM_PALETTES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"At most {_MAX_CUSTOM_PALETTES} saved themes.",
            )

        # References that must resolve, checked outside the model (the generator
        # /client is trusted for taste, not constraints): a `custom:<id>` palette
        # must be one of the themes in this same write, and an `import:<id>` font
        # must be one this user actually owns.
        saved_ids = {p.id for p in data.custom_palettes}
        if data.palette.startswith("custom:") and data.palette[len("custom:") :] not in saved_ids:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="palette points at a saved theme that is not in custom_palettes.",
            )
        if data.font.startswith("import:"):
            font_id = data.font[len("import:") :]
            owned = await self._session.scalar(
                select(UserFont.id).where(
                    UserFont.user_id == user_id, UserFont.id == _as_uuid(font_id)
                )
            )
            if owned is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="font points at an imported font that does not exist.",
                )

        row = await self._session.get(UserPreference, user_id)
        if row is None:
            row = UserPreference(user_id=user_id)
            self._session.add(row)
        row.palette = data.palette
        row.custom_palettes = [p.model_dump() for p in data.custom_palettes]
        row.font = data.font
        await self._session.commit()
        return await self.get(user_id)

    async def add_font(self, user_id: UUID, name: str, font: ValidatedFont) -> ImportedFontOut:
        row = UserFont(
            user_id=user_id,
            name=name,
            format=font.format,
            data=font.data,
            byte_size=len(font.data),
        )
        self._session.add(row)
        await self._session.commit()
        return ImportedFontOut(id=row.id, name=row.name, format=row.format, byte_size=row.byte_size)

    async def list_fonts(self, user_id: UUID) -> list[ImportedFontOut]:
        return await self._fonts(user_id)

    async def load_font_bytes(self, user_id: UUID, font_id: UUID) -> tuple[bytes, str]:
        """The bytes, blob explicitly undeferred, scoped to the caller. Raises
        `LookupError` when the id is not one of this user's fonts — same 404 a
        stranger's id gets, no distinction leaked."""

        row = (
            await self._session.execute(
                select(UserFont)
                .where(UserFont.user_id == user_id, UserFont.id == font_id)
                .options(undefer(UserFont.data))
            )
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("Font not found")
        return row.data, _FONT_MEDIA_TYPE.get(row.format, "application/octet-stream")

    async def delete_font(self, user_id: UUID, font_id: UUID) -> None:
        """Remove a font. If the active `font` pointed at it, reset to the
        default in the same transaction so a load never dangles."""

        font = (
            await self._session.execute(
                select(UserFont).where(UserFont.user_id == user_id, UserFont.id == font_id)
            )
        ).scalar_one_or_none()
        if font is None:
            raise LookupError("Font not found")
        await self._session.delete(font)

        pref = await self._session.get(UserPreference, user_id)
        if pref is not None and pref.font == f"import:{font_id}":
            pref.font = DEFAULT_FONT
        await self._session.commit()


def _as_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="font id is malformed."
        ) from e
