"""`the_spoin_universe` — the source-of-truth corpus store.

Schema and reasoning: docs/adr/0088-the-spoin-universe.md.
"""

from frog.universe.models import Chunk, Document, DocumentKind, DocumentScope

__all__ = ["Chunk", "Document", "DocumentKind", "DocumentScope"]
