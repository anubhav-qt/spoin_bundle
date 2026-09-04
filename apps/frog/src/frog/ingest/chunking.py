"""Turning a parsed document into the text that gets embedded and stored.

Chunking is section-level: one `##` section, one chunk, no sub-splitter. A section
boundary is the author's judgment about where one idea ends, and a recursive splitter
would overrule it with machinery that has read less of the material than they have.

That holds only while sections stay chunk-sized, which they were **not** doing on their
own — measured over 358 real sections with `Qwen3-Embedding-0.6B`'s own tokenizer, the
median is 339 tokens but 17% run over 512 and the largest is 1385. Hence the enforced
size limit in `contract.MAX_SECTION_CHARS` rather than a guideline (task 0038, Phase 2).
"""

from __future__ import annotations

from frog.ingest.contract import ParsedDocument

#: Separates the situating header from the author's prose. A blank line, so a model
#: reading the chunk sees a title and a body rather than one run-on paragraph.
_HEADER_SEPARATOR = "\n\n"

#: Joins the document title to the section heading.
_HEADER_JOIN = " — "


def contextual_text(document: ParsedDocument, heading: str, text: str) -> str:
    """The exact string that is both embedded and stored (rag-design-space 3.8).

    A section is retrieved and shown to a model **without its neighbours**, and dense
    authoritative prose routinely never names its own subject — a chunk explaining why
    `z-index` fails inside a transformed ancestor says nothing about CSS, frontend
    engineering, or which document it came from. That costs twice: the vector is vague,
    so the chunk is harder to find, and the model reading it cannot attribute it.

    Prefixing the document title and section heading is the free, deterministic half of
    3.8's proposal. The generated-sentence half is deliberately not built until the
    eval harness can show it earns its cost.

    **The header is stored, not merely embedded** (owner's decision, 2026-09-05). The
    alternative — embed the header, store bare prose — makes the vector and the stored
    text describe different strings, which is the silent-divergence shape ADR-0092 was
    written about. Re-ingestion is minutes on a GPU and the corpus is derived, so the
    cost of that choice is a rebuild we are already set up to do.
    """

    header = document.title
    #: Suppressed when the heading merely restates the title, which would spend prompt
    #: tokens saying the same thing twice.
    if heading.strip().lower() != document.title.strip().lower():
        header = f"{document.title}{_HEADER_JOIN}{heading}"
    return f"{header}{_HEADER_SEPARATOR}{text}"


def chunk_texts(document: ParsedDocument) -> list[str]:
    """Every chunk of one document, in document order.

    Order is the `ordinal` column: it makes a chunk citable as "part 3 of" and lets
    retrieval widen a hit to its neighbours later without guessing.
    """

    return [contextual_text(document, s.heading, s.text) for s in document.sections]
