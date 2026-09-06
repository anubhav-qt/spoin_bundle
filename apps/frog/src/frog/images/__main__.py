"""`python -m frog.images` — the image catalog entrypoint (ADR-0095, task 0040).

    docker compose --profile frog run --rm --entrypoint python frog -m frog.images --check
    docker compose --profile frog run --rm --entrypoint python frog -m frog.images

`--check` writes nothing, opens no database, loads no model and makes **no network
call** — not even to see whether a `source_url` still resolves. That purity is what
makes it the thing the image-authoring track can run while it works, and a reachability
probe would destroy it; if one is ever wanted it goes behind its own flag (task 0040,
Phase 2).

Runs in the `frog` service for `frog.ingest`'s reason: the embedder is a GPU model, and
only the app backend deploys (ADR-0094).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from frog.embeddings import Embedder, HashEmbedder, Qwen3Embedder
from frog.images.contract import DEFAULT_IMAGES_ROOT, ManifestErrors, parse_images
from frog.images.runner import ingest_images
from frog.universe.config import universe_url
from frog.universe.models import EMBEDDING_DIM

#: ADR-0092, and named here rather than imported from a settings object for
#: `frog.ingest`'s reason: an embedding model configured in two places is how two
#: tables end up holding vectors that are silently not comparable.
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="frog.images", description=__doc__)
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES_ROOT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate against the contract and exit; writes nothing, loads no model, "
        "makes no network call",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-embed every entry even when its hash is unchanged (after an embedding "
        "model change, which alters the vectors without altering the manifest)",
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
        help="`hash` is a deterministic stand-in with NO semantic meaning. A catalog "
        "embedded with it assigns uniformly irrelevant images and looks normal doing it; "
        "it exists for tests.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def build_embedder(name: str, model: str, device: str | None) -> Embedder:
    if name == "hash":
        logging.getLogger(__name__).warning(
            "HashEmbedder: vectors will have NO semantic meaning. Every image assignment "
            "from this catalog is arbitrary."
        )
        return HashEmbedder(EMBEDDING_DIM)
    return Qwen3Embedder(model, device=device)


def check(root: Path) -> int:
    """Validate the delivered manifests and report. Synchronous, opens nothing.

    Separate from `_run` for the same reason `frog.ingest.check` is: there is no reason
    "do these manifests satisfy the contract" should need an event loop, a GPU or a
    connection string to answer.
    """

    parsed, failures = parse_images(root)
    _print_failures(failures)
    images = sum(len(manifest.images) for manifest in parsed)
    print(
        f"checked {len(parsed) + len(failures)} manifests: "
        f"{len(parsed)} ok, {len(failures)} failing, {images} images"
    )
    return 1 if failures else 0


async def _run(args: argparse.Namespace, root: Path) -> int:
    embedder = build_embedder(args.embedder, args.model, args.device)
    engine = create_async_engine(universe_url())
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            #: One transaction for the whole run, matching the prose ingester: a crash
            #: part-way must not leave rows whose `content_hash` claims they are current
            #: while their embedding is from the previous description.
            report = await ingest_images(session, root, embedder, force=args.force)
            await session.commit()
    finally:
        await engine.dispose()

    _print_failures(report.errors)
    print(report)
    return 1 if report.failed_manifests else 0


def _print_failures(failures: list[ManifestErrors]) -> None:
    """Every problem in every failing manifest, named by file, index and field.

    Manifests are authored by another track, so a failure message is a work item handed
    back to a person: "validation failed" is not one, "images[42]: `licence` 'CC-BY-NC'
    is not in the allowlist" is.
    """

    for failure in failures:
        print(f"\nFAIL {failure.manifest_path}", file=sys.stderr)
        for problem in failure.problems:
            print(f"  - {problem}", file=sys.stderr)


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    root: Path = args.images
    #: A missing tree is an empty delivery, not an error — `parse_images` says why —
    #: so unlike the corpus entrypoint this does not exit 2 on one.
    if args.check:
        return check(root)
    return asyncio.run(_run(args, root))


if __name__ == "__main__":
    raise SystemExit(main())
