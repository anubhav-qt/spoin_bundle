"""Avatar upload validation.

The behaviour under test is specifically that the *request* is not trusted:
before this, `file.content_type` decided whether an upload was an image, so
anything at all passed by claiming `image/png`.
"""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile

from spoin.profile.images import MAX_BYTES, read_validated_image

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF" + (72).to_bytes(4, "little") + b"WEBP" + b"\x00" * 64


def _upload(
    data: bytes, *, filename: str = "avatar.png", content_type: str = "image/png"
) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename=filename,
        headers={"content-type": content_type},  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("data", "expected"),
    [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")],
    ids=["jpeg", "png", "webp"],
)
async def test_media_type_comes_from_the_bytes(data: bytes, expected: str) -> None:
    """Note the deliberately wrong `content_type` on every one of these: the
    header says image/png and the answer still tracks the actual bytes."""

    result = await read_validated_image(_upload(data, content_type="image/png"))
    assert result.media_type == expected
    assert result.data == data


async def test_a_disguised_non_image_is_rejected() -> None:
    """The case the old check could not see: correct declared type, correct
    extension, contents that are not an image at all."""

    payload = b"<html><script>alert(1)</script></html>"
    with pytest.raises(HTTPException) as exc:
        await read_validated_image(_upload(payload, content_type="image/png"))
    assert exc.value.status_code == 400


async def test_empty_upload_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        await read_validated_image(_upload(b""))
    assert exc.value.status_code == 400


async def test_oversized_upload_is_rejected() -> None:
    oversized = PNG + b"\x00" * (MAX_BYTES + 1)
    with pytest.raises(HTTPException) as exc:
        await read_validated_image(_upload(oversized))
    assert exc.value.status_code == 413


async def test_an_upload_at_the_limit_is_accepted() -> None:
    at_limit = PNG + b"\x00" * (MAX_BYTES - len(PNG))
    result = await read_validated_image(_upload(at_limit))
    assert len(result.data) == MAX_BYTES
