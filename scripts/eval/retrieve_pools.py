"""Step 2 of the retrieval eval (rag-design-space §3.2): the candidate pools to label.

Runs in the **frog** image -- the only one with torch and the GPU (ADR-0094), and the
reason this is a second script rather than a second function. It reads the queries
`build_queries.py` produced, embeds them with the real `Qwen3Embedder`, and retrieves a
pool wider than any prompt would carry.

**Wider than the prompt on purpose.** The prompt takes what fits in
`grounding_token_budget`; the pool has to include the passages that *lost*, or
precision@k is the only thing measurable and recall@k is not. `--pool` is the pool
size, not the prompt's.

Read-only against `the_spoin_universe`. Writes nothing to either database.

    docker compose --profile frog run --rm --entrypoint python frog \\
        /repo/scripts/eval/retrieve_pools.py \\
        --queries /repo/.eval/queries.json --out /repo/.eval/pools.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from frog.embeddings import Qwen3Embedder
from frog.retrieval import search_many
from frog.universe.models import DocumentKind

#: Matches production: canon is pinned into the prompt, never retrieved (ADR-0096), so
#: a pool that offered canon chunks for labelling would be asking about a decision that
#: is already made -- and would score the harness against passages no card can receive.
KINDS = [DocumentKind.TOPIC_SOURCE]

DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pool", type=int, default=10)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    queries = json.loads(args.queries.read_text(encoding="utf-8"))
    print(f"{len(queries)} queries, pool of {args.pool}, loading {args.model}...")

    embedder = Qwen3Embedder(args.model)
    engine = create_async_engine(os.environ["SPOIN_UNIVERSE_DATABASE_URL"])
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            #: One `encode` over every query -- one GPU round trip instead of N.
            pools = await search_many(
                session,
                embedder,
                [entry["query"] for entry in queries],
                k=args.pool,
                kinds=KINDS,
            )
    finally:
        await engine.dispose()

    out = [
        {
            **entry,
            "candidates": [
                {
                    "chunk_id": str(hit.chunk_id),
                    "document_id": str(hit.document_id),
                    "score": round(hit.score, 4),
                    "text": hit.text,
                    "document_title": hit.document_title,
                    "source": hit.source,
                    "source_path": hit.source_path,
                    "category": hit.category,
                    "sub_category": hit.sub_category,
                }
                for hit in hits
            ],
        }
        for entry, hits in zip(queries, pools, strict=True)
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    scored = [c["score"] for entry in out for c in entry["candidates"]]
    tops = [entry["candidates"][0]["score"] for entry in out if entry["candidates"]]
    print(f"{len(scored)} candidates -> {args.out}")
    if tops:
        tops.sort()
        mid = tops[len(tops) // 2]
        print(f"top-1 score: min {tops[0]:.3f}  median {mid:.3f}  max {tops[-1]:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
