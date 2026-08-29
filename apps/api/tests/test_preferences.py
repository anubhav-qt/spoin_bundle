"""Server-stored appearance preferences (ADR-0070).

Two things under test: the font upload trusts the *bytes*, not the request
(same property as avatars), and every imported-font read is scoped to its
owner — a stranger's font id is a 404, never a served blob.
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.api.schemas import CustomPalette, PreferencesUpdateIn
from spoin.domain.models import User
from spoin.domain.models.preferences import DEFAULT_FONT, DEFAULT_PALETTE
from spoin.profile.fonts import MAX_BYTES, ValidatedFont, read_validated_font
from spoin.profile.preferences import PreferencesService

WOFF2 = b"wOF2" + b"\x00" * 64
TTF = b"\x00\x01\x00\x00" + b"\x00" * 64
OTF = b"OTTO" + b"\x00" * 64


def _upload(data: bytes, *, content_type: str = "font/woff2") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename="font.woff2",
        headers={"content-type": content_type},  # type: ignore[arg-type]
    )


async def _user(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@test.local", display_name="Test")
    session.add(user)
    await session.flush()
    return user.id


# ---------------------------------------------------------------- font sniffing --


@pytest.mark.parametrize(
    ("data", "expected"),
    [(WOFF2, "woff2"), (TTF, "ttf"), (OTF, "otf")],
    ids=["woff2", "ttf", "otf"],
)
async def test_font_format_comes_from_the_bytes(data: bytes, expected: str) -> None:
    # Deliberately wrong declared content_type on every one; the answer tracks
    # the actual leading bytes.
    result = await read_validated_font(_upload(data, content_type="application/octet-stream"))
    assert result.format == expected
    assert result.data == data


async def test_a_non_font_is_rejected() -> None:
    payload = b"<html><script>alert(1)</script></html>"
    with pytest.raises(HTTPException) as exc:
        await read_validated_font(_upload(payload))
    assert exc.value.status_code == 400


async def test_oversized_font_is_rejected_at_the_limit() -> None:
    with pytest.raises(HTTPException) as exc:
        await read_validated_font(_upload(b"wOF2" + b"\x00" * (MAX_BYTES + 1)))
    assert exc.value.status_code == 413


# ------------------------------------------------------------- preferences CRUD --


async def test_get_returns_defaults_when_no_row(session: AsyncSession) -> None:
    user_id = await _user(session)
    prefs = await PreferencesService(session).get(user_id)
    assert prefs.palette == DEFAULT_PALETTE
    assert prefs.font == DEFAULT_FONT
    assert prefs.custom_palettes == []
    assert prefs.imported_fonts == []


async def test_update_creates_the_row_and_round_trips_saved_themes(session: AsyncSession) -> None:
    user_id = await _user(session)
    theme = CustomPalette(
        id="sunset", name="Sunset Desk", bg="#2b1d16", fg="#f2ede6", accent="#e08a3c", accent2="#c65b3f"
    )
    service = PreferencesService(session)

    out = await service.update(
        user_id,
        PreferencesUpdateIn(palette="custom:sunset", custom_palettes=[theme], font="inter"),
    )
    assert out.palette == "custom:sunset"
    assert out.font == "inter"
    assert [p.model_dump() for p in out.custom_palettes] == [theme.model_dump()]

    # A fresh read sees the same thing (it really persisted).
    assert (await service.get(user_id)).custom_palettes[0].name == "Sunset Desk"


async def test_update_rejects_a_palette_pointer_with_no_matching_theme(session: AsyncSession) -> None:
    user_id = await _user(session)
    with pytest.raises(HTTPException) as exc:
        await PreferencesService(session).update(
            user_id,
            PreferencesUpdateIn(palette="custom:ghost", custom_palettes=[], font="inter"),
        )
    assert exc.value.status_code == 422


async def test_update_rejects_a_font_pointer_to_an_unowned_import(session: AsyncSession) -> None:
    user_id = await _user(session)
    with pytest.raises(HTTPException) as exc:
        await PreferencesService(session).update(
            user_id,
            PreferencesUpdateIn(
                palette="notebook",
                custom_palettes=[],
                font=f"import:{uuid.uuid4()}",
            ),
        )
    assert exc.value.status_code == 422


# ------------------------------------------------------------ imported fonts --


async def _validated(data: bytes = WOFF2) -> ValidatedFont:
    return await read_validated_font(_upload(data))


async def test_add_list_and_serve_a_font(session: AsyncSession) -> None:
    user_id = await _user(session)
    service = PreferencesService(session)

    meta = await service.add_font(user_id, "My Face", await _validated())
    assert meta.format == "woff2"
    assert meta.byte_size == len(WOFF2)

    listed = await service.list_fonts(user_id)
    assert [f.id for f in listed] == [meta.id]

    data, media_type = await service.load_font_bytes(user_id, meta.id)
    assert data == WOFF2
    assert media_type == "font/woff2"


async def test_a_font_is_not_readable_by_another_user(session: AsyncSession) -> None:
    owner = await _user(session)
    stranger = await _user(session)
    service = PreferencesService(session)

    meta = await service.add_font(owner, "Private", await _validated())

    with pytest.raises(LookupError):
        await service.load_font_bytes(stranger, meta.id)
    assert await service.list_fonts(stranger) == []


async def test_deleting_the_active_font_resets_the_choice(session: AsyncSession) -> None:
    user_id = await _user(session)
    service = PreferencesService(session)

    meta = await service.add_font(user_id, "Temp", await _validated())
    await service.update(
        user_id,
        PreferencesUpdateIn(
            palette="notebook", custom_palettes=[], font=f"import:{meta.id}"
        ),
    )
    assert (await service.get(user_id)).font == f"import:{meta.id}"

    await service.delete_font(user_id, meta.id)
    assert (await service.get(user_id)).font == DEFAULT_FONT
    assert await service.list_fonts(user_id) == []


async def test_deleting_someone_elses_font_is_a_lookup_error(session: AsyncSession) -> None:
    owner = await _user(session)
    stranger = await _user(session)
    service = PreferencesService(session)
    meta = await service.add_font(owner, "Private", await _validated())

    with pytest.raises(LookupError):
        await service.delete_font(stranger, meta.id)
    # Still there for the owner.
    assert len(await service.list_fonts(owner)) == 1
