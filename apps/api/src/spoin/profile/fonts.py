"""Imported-font upload validation (ADR-0070).

Same shape and reasoning as `profile/images.py`: the multipart part's declared
`content_type` is whatever the client put there, so the format is sniffed from
the file's own magic bytes, and the body is read in bounded chunks so an
oversized upload is abandoned at the limit rather than after it lands. A font
file is arbitrary binary handed to the browser's font parser, historically a
memory-safety target — the extension is not a check.

Not a full font parse. A malformed-but-correctly-magic'd file will be stored and
served; the browser rejects it at `@font-face` load and the reader sees the
fallback stack. Re-parsing every upload (fontTools) is a dependency for a
gap — a corrupt file the uploader immediately sees is broken — that magic bytes
plus a size cap already closes to the realistic level.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, UploadFile, status

MAX_BYTES = 2 * 1024 * 1024
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class ValidatedFont:
    data: bytes
    #: Sniffed, never taken from the request. One of `woff2` / `ttf` / `otf`.
    #: This is what the served `Content-Type` and the `user_font.format` column
    #: are set from.
    format: str


def _sniff(head: bytes) -> str | None:
    """Font format from the file's own leading bytes, or None if unrecognised."""

    if head.startswith(b"wOF2"):
        return "woff2"
    if head.startswith(b"OTTO"):
        return "otf"
    # TrueType outlines: the version tag 0x00010000, plus the legacy `true` /
    # `ttcf` (collection) markers.
    if head.startswith((b"\x00\x01\x00\x00", b"true", b"ttcf")):
        return "ttf"
    return None


async def read_validated_font(file: UploadFile) -> ValidatedFont:
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Font file is too large. Maximum size is 2MB.",
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty upload")

    fmt = _sniff(data[:16])
    if fmt is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Unsupported font file. Only WOFF2, TTF and OTF are supported.",
        )

    return ValidatedFont(data=data, format=fmt)
