"""Ingestion: the delivered corpus becomes `document` and `chunk` rows.

The contract this consumes is `docs/handoff/antigravity-corpus-authoring.md`; the plan
is task 0038's Phase 2. Three modules, in dependency order:

- `contract` — parse and validate one document. Pure, needs no database and no model.
- `chunking` — a validated document becomes the exact strings that get embedded.
- `runner` — walk, hash, skip-or-replace, embed, write.

`python -m frog.ingest --check` runs the first of those alone, which is what the
corpus-authoring track needs and what CI can afford.
"""

from frog.ingest.contract import (
    MAX_SECTION_CHARS,
    DocumentErrors,
    ParsedDocument,
    parse_document,
)
from frog.ingest.runner import IngestReport, ingest_corpus, ingest_document, parse_corpus

__all__ = [
    "MAX_SECTION_CHARS",
    "DocumentErrors",
    "IngestReport",
    "ParsedDocument",
    "ingest_corpus",
    "ingest_document",
    "parse_corpus",
    "parse_document",
]
