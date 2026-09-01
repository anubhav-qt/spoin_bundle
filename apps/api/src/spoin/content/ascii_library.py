"""Retrieval over the curated ASCII art reference library (ADR-0068, Task 0029).

The library (`content/ascii_library_data/*.txt` — the runtime copy; the curation
workspace is `apps/helpers/`, see that directory's README and Task 0030) is
~2,500 hand-curated, hand-titled entries, each independently verified to fit
the 40-column phone budget. Too large to paste into a prompt whole (hundreds
of thousands of tokens), so this module does what a prompt instruction can't:
a deterministic nearest-neighbor search over the library's TITLES, keyed off
the planner's own `asset_direction` text for an ascii-typed card, returning a
short candidate list the writer prompt can actually show the model.

This is retrieval, not selection. The writer is never told to pick one of the
returned candidates -- CLAUDE.md's "trusted for taste, never for constraints"
cuts the same way here as it does for archetype and difficulty: which idea a
scene should evoke is a judgment call, and the candidates exist to ground that
judgment in a piece of art that is KNOWN to render cleanly, not to constrain
it. A card whose idea fits nothing in the library still gets original art.

Embeddings run through `content/embeddings.get_embedder()` -- the same local,
never-quota'd embedder every other semantic-similarity feature in the codebase
uses (topic matching, `normalize_topic_text`). Whichever backend that resolves
to (fastembed in production, the deterministic hash stand-in in tests/dev
without the model downloaded) is what this module searches with too; a
meaningless-similarity hash embedder just means candidates come back in a
meaningless order, never a crash.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from spoin.embeddings import get_embedder

#: `apps/helpers/`'s curated file, copied into the package so the library ships
#: with the built image (`apps/api/Dockerfile` only `COPY`s `src`, never the
#: sibling `apps/helpers/` tooling directory). This copy is the deployed source
#: of truth; `apps/helpers/use_for_gags.txt` is where curation edits happen
#: (Task 0030) and gets synced here afterward -- see that task's note.
#:
#: ADR-0079: gags only. `use_for_informative_visualization.txt` still sits next
#: to this one on disk but is deliberately NOT loaded -- every ASCII card is a
#: comedic scene now, so an "informative visualisation" candidate pool has
#: nothing to feed. Re-add the filename here to bring it back.
_LIBRARY_FILES = ("use_for_gags.txt",)

#: `=== ID: art_52_5 | TITLE: Boxer fighter stance ... | ARTIST: unknown |
#:  CATEGORY: one-line | SUBCATEGORY: actions | SIZE: 7x1 ===` followed by a
#: fenced block. Every field before TITLE and after it is present in every
#: entry across both files (verified against the full corpus, 2,487 entries,
#: zero non-matches) -- this is a stable, machine-generated format, not
#: hand-written prose to be lenient with.
_ENTRY_RE = re.compile(
    r"=== ID: (?P<id>\S+) \| TITLE: (?P<title>.*?) \| ARTIST: .*? \| "
    r"CATEGORY: (?P<category>.*?) \| SUBCATEGORY: (?P<subcategory>.*?) \| SIZE: .*? ===\n"
    r"```\n(?P<art>.*?)```",
    re.DOTALL,
)


@dataclass(frozen=True)
class AsciiLibraryEntry:
    id: str
    title: str
    category: str
    subcategory: str
    art: str


@lru_cache
def load_library() -> tuple[AsciiLibraryEntry, ...]:
    """Parses the curated gag file once per process. A missing file (a dev
    checkout that hasn't pulled the data, or a build that genuinely omitted
    it) degrades to an empty library rather than crashing generation -- the
    pre-retrieval behavior (the model draws its own scene, unaided) is a
    correct fallback, not a broken one."""

    entries: list[AsciiLibraryEntry] = []
    package = resources.files("spoin.content") / "ascii_library_data"
    for filename in _LIBRARY_FILES:
        target = package / filename
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        for match in _ENTRY_RE.finditer(text):
            entries.append(
                AsciiLibraryEntry(
                    id=match.group("id"),
                    title=match.group("title").strip(),
                    category=match.group("category").strip(),
                    subcategory=match.group("subcategory").strip(),
                    art=match.group("art").rstrip("\n"),
                )
            )
    return tuple(entries)


#: Populated once per process by `_library_index`, guarded by `_index_lock` so
#: two concurrent callers (two ascii-typed cards in the same batch) don't both
#: pay the embedding cost. `None` until first computed.
_index_cache: list[list[float]] | None = None
_index_lock = asyncio.Lock()


async def _library_index() -> list[list[float]]:
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    async with _index_lock:
        if _index_cache is None:  # re-check: another caller may have won the race
            library = load_library()
            embedder = get_embedder()
            _index_cache = (
                await embedder.aembed([entry.title for entry in library]) if library else []
            )
    return _index_cache


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def top_candidates(query: str, k: int = 10) -> list[AsciiLibraryEntry]:
    """The `k` library entries whose TITLE is most similar to `query` (the
    planner's `asset_direction` for an ascii-typed card), ranked descending.

    Returns `[]` for an empty query or an empty/unavailable library -- both
    are the caller's cue to fall back to unaided generation, not an error."""

    library = load_library()
    if not library or not query.strip():
        return []

    embedder = get_embedder()
    index, query_vec = await asyncio.gather(_library_index(), embedder.aembed([query]))
    scored = sorted(
        zip(library, index, strict=True),
        key=lambda pair: _cosine(pair[1], query_vec[0]),
        reverse=True,
    )
    return [entry for entry, _vec in scored[:k]]
