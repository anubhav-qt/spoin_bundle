"""Run the real grounding path against the real corpus, once, and print what it got.

Every test of `spoin.generation.grounding` uses `HashEmbedder` over a handful of seeded
rows, which is right for the tests — they assert caching, outcomes and counts, none of
which need a real model. What none of them cover is the chain end to end: the worker
image, Qwen3 on the GPU, `the_spoin_universe`, `Grounding`, and the block that actually
reaches a prompt. This runs it.

**Reads only.** No LLM call, no writes to either database. It is safe to run whenever
the corpus changes, and it is the cheapest way to answer "is grounding actually
working?" before a generation run depends on the answer — a silently ungrounded run
does not fail, it produces worse cards, which is what ADR-0089 is most worried about.

What to look for in the output:

* `outcome=GROUNDED`. `NO_MATCH` means the corpus has nothing for this subtopic;
  `UNAVAILABLE` means it could not be read at all (usually
  `SPOIN_UNIVERSE_DATABASE_URL`), and generation would silently proceed ungrounded.
* Two passages, because `Settings.grounding_chunks` is 2 (ADR-0089 as amended).
* Passages that are actually about the subtopic. This is the check no assertion
  replaces — retrieval returns its best answer whether or not the corpus holds one.
* `embedder=Qwen/...`, not `hash`. A hash-grounded run is grounded on nothing.

    MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \\
        -v "E:/spoin_bundle/scripts:/repo/scripts" --entrypoint python worker \\
        /repo/scripts/eval/ground_smoke.py --topic "PostgreSQL" \\
        --subtopic "MVCC" --description "How a transaction sees a fixed view."

The **worker** image, not `frog`: this imports `spoin.generation.grounding`, and the
frog image installs frog alone — ADR-0087 runs the dependency `api -> frog` only, so
frog has no reason to carry `spoin`. The worker is also the service built with
`EMBEDDER_BACKEND=gpu`. `--no-deps` skips the seed migration; nothing here writes.
`MSYS_NO_PATHCONV=1` is not optional under Git Bash on this machine.

Verified working 2026-09-05 against 933 chunks: "PostgreSQL / MVCC and snapshot
isolation" returned two passages from the transaction-isolation source at 908
estimated prompt tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

from frog.embeddings import HashEmbedder, Qwen3Embedder
from frog.universe.models import EMBEDDING_DIM

from spoin.generation.grounding import Grounding, build_query

DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--subtopic", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--chunks", type=int, default=2, help="Settings.grounding_chunks")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument(
        "--hash",
        action="store_true",
        help="use HashEmbedder instead — only to see what a broken run looks like",
    )
    args = ap.parse_args()

    if not os.environ.get("SPOIN_UNIVERSE_DATABASE_URL"):
        print("SPOIN_UNIVERSE_DATABASE_URL is not set — grounding will report UNAVAILABLE")

    embedder = HashEmbedder(EMBEDDING_DIM) if args.hash else Qwen3Embedder(args.model)

    query = build_query(args.topic, args.subtopic, args.description)
    context = await Grounding(embedder, chunks=args.chunks).for_subtopic(
        #: A fresh id every run: the cache is per subtopic GROUP and this process is
        #: not trying to exercise it.
        subtopic_group_id=uuid.uuid4(),
        topic_name=args.topic,
        subtopic_title=args.subtopic,
        subtopic_description=args.description,
    )

    print(f"embedder={embedder.model_name}")
    print(f"query={query}")
    print(
        f"outcome={context.outcome.value} retrieved={context.retrieved} "
        f"used={len(context.chunk_ids)} est_tokens={context.estimated_tokens}"
    )
    print()
    print(context.block or "(no block — nothing grounded this call)")


if __name__ == "__main__":
    asyncio.run(main())
