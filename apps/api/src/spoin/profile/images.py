"""Avatar upload validation.

The previous checks trusted the client: `file.content_type` is whatever the
browser (or curl) put in the multipart part, so a `.html` renamed to `.png`
passed, and the size limit was applied *after* `await file.read()` had already
buffered the whole body into memory — a 500MB upload was fully resident before
being rejected.

This sniffs the actual bytes and reads in bounded chunks, so an oversized body
is abandoned as soon as it crosses the limit rather than after it lands.

Not a full image decode. Re-encoding through Pillow would be the stronger
answer (it also strips EXIF), but that is a new dependency for a feature whose
output is only ever served back with an explicit `Content-Type` to the user who
uploaded it; magic bytes plus a byte cap closes the realistic gap here.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, UploadFile, status

MAX_BYTES = 5 * 1024 * 1024
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    #: Sniffed, never taken from the request. This is what gets served back.
    media_type: str


def _sniff(head: bytes) -> str | None:
    """Media type from the file's own leading bytes, or None if unrecognised."""

    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    # RIFF....WEBP — the size field sits between the two markers.
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    return None


async def read_validated_image(file: UploadFile) -> ValidatedImage:
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BYTES:
            # Stop reading. Whatever the client is still sending is discarded
            # by the server closing out the request, not accumulated here.
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Image is too large. Maximum size is 5MB.",
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty upload")

    media_type = _sniff(data[:16])
    if media_type is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Invalid image format. Only JPEG, PNG, and WebP are supported.",
        )

    return ValidatedImage(data=data, media_type=media_type)
