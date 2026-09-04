"""`python -m frog.ingest` — the corpus ingestion entrypoint.

Runs in the `frog` compose service, which is the only image in this project carrying
torch and a CUDA runtime (task 0038, Phase 2). Generation and bulk embedding run on the
owner's machine; only the app backend deploys, so the GPU lives here rather than in the
api image.

    docker compose --profile frog run --rm frog                 # ingest
    docker compose --profile frog run --rm frog --check         # validate only

**`--check` writes nothing and needs no database or model.** It is the half of this
command the corpus-authoring track actually wants: it answers "does the corpus satisfy
the contract" without a GPU.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from frog.embeddings import Embedder, HashEmbedder, Qwen3Embedder
from frog.ingest.contract import DocumentErrors
from frog.ingest.runner import ingest_corpus, parse_corpus
from frog.universe.config import universe_url
from frog.universe.models import EMBEDDING_DIM

#: ADR-0092. Named here rather than read from settings because frog deliberately has no
#: settings object beyond the database URL: `embedding_dim` configured in two places is
#: how two databases end up holding vectors that are silently not comparable.
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"

#: The delivered corpus, relative to the repository root.
DEFAULT_CORPUS = Path("docs/the_spoin_universe/corpus")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="frog.ingest", description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate against the contract and exit; writes nothing, loads no model",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-embed every document even when its hash is unchanged (after a chunking "
        "or header-format change, which alters what was embedded without altering the file)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--device",
        default=None,
        help="torch device; the default lets sentence-transformers pick CUDA when present",
    )
    parser.add_argument(
        "--embedder",
        choices=("qwen3", "hash"),
        default="qwen3",
        help="`hash` is a deterministic stand-in with NO semantic meaning. Ingesting with "
        "it produces a corpus that cannot be retrieved from usefully; it exists for tests.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def build_embedder(name: str, model: str, device: str | None) -> Embedder:
    if name == "hash":
        #: Loud, because a corpus embedded with this looks completely normal in the
        #: database and is useless — the exact shape of task 0039, where hash vectors
        #: sat in production for months because nothing said so.
        logging.getLogger(__name__).warning(
            "HashEmbedder: vectors will have NO semantic meaning. Do not draw retrieval "
            "conclusions from this corpus."
        )
        return HashEmbedder(EMBEDDING_DIM)
    return Qwen3Embedder(model, device=device)


def check(root: Path) -> int:
    """Validate the corpus and report. Synchronous, and never opens a database.

    Deliberately not inside `_run`: `--check` is the half of this command the
    corpus-authoring track runs, and there is no reason for it to need an event loop,
    a model or a connection string to answer "does the corpus satisfy the contract".
    """

    parsed, failures = parse_corpus(root)
    _print_failures(failures)
    print(
        f"checked {len(parsed) + len(failures)} documents: "
        f"{len(parsed)} ok, {len(failures)} failing"
    )
    return 1 if failures else 0


async def _run(args: argparse.Namespace, root: Path) -> int:
    embedder = build_embedder(args.embedder, args.model, args.device)
    engine = create_async_engine(universe_url())
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            #: One transaction for the whole run. A document's chunks are deleted and
            #: rebuilt, and a crash mid-run must not leave a document whose hash claims
            #: it is current while its chunks are gone (ADR-0088).
            report = await ingest_corpus(session, root, embedder, force=args.force)
            await session.commit()
    finally:
        await engine.dispose()

    _print_failures(report.errors)
    print(report.summary())
    return 1 if report.failed else 0


def _print_failures(failures: list[DocumentErrors]) -> None:
    """Every problem in every failing document, named by path and by field.

    The corpus is authored by another track, so a failure message is a work item handed
    back to a person. "validation failed" is not one; "`title` is missing" is.
    """

    for failure in failures:
        print(f"\nFAIL {failure.source_path}", file=sys.stderr)
        for problem in failure.problems:
            print(f"  - {problem}", file=sys.stderr)


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    root: Path = args.corpus
    if not root.is_dir():
        print(f"corpus not found: {root}", file=sys.stderr)
        return 2

    if args.check:
        return check(root)
    return asyncio.run(_run(args, root))


if __name__ == "__main__":
    raise SystemExit(main())
