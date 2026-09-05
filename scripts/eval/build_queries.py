"""Step 1 of the retrieval eval (rag-design-space §3.2): pick the golden set's queries.

Runs in the **api** image, because the query string is `spoin`'s to build --
`grounding.build_query` is the real function the pipeline calls, and a copy of that
one line living in an eval script is how a harness ends up measuring something the
product does not do.

Retrieval itself is step 2 (`retrieve_pools.py`), which runs in the **frog** image
because that is the only one with torch and the GPU (ADR-0094). The two steps hand
each other a JSON file rather than sharing a process for exactly that reason.

`spoin_db_2` is read with SELECTs and nothing else.

    docker compose run --rm --no-deps --entrypoint python api \\
        /repo/scripts/eval/build_queries.py --out /repo/.eval/queries.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
from collections import defaultdict
from pathlib import Path

import asyncpg

from spoin.generation.grounding import build_query

#: Sampled per topic rather than uniformly at random over all 321 subtopic groups.
#: Uniform sampling would hand the golden set to whichever topics happen to have the
#: most subtopics -- Backend Engineering and PostgreSQL alone are a quarter of them --
#: and a harness that only measures the corpus's best-covered subject measures the
#: thing least likely to be broken.
PER_TOPIC = 2

#: One row per subtopic GROUP, not per tier: the query is tier-independent by design
#: (rag-design-space §3.7), so labelling three tiers of one concept would be labelling
#: the same query three times. The lowest tier's row carries the group.
_SUBTOPICS = """
    SELECT DISTINCT ON (s.subtopic_group_id)
           s.subtopic_group_id::text AS group_id,
           t.canonical_name          AS topic_name,
           s.title                   AS title,
           s.description             AS description
      FROM subtopic s
      JOIN topic t ON t.id = s.topic_id
     ORDER BY s.subtopic_group_id, s.difficulty
"""


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-topic", type=int, default=PER_TOPIC)
    #: Fixed so the golden set is reproducible. A harness whose sample moves between
    #: runs cannot tell a retrieval change from a sampling change.
    parser.add_argument("--seed", type=int, default=38)
    args = parser.parse_args()

    url = os.environ["SPOIN_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    connection = await asyncpg.connect(url)
    try:
        rows = await connection.fetch(_SUBTOPICS)
    finally:
        await connection.close()

    by_topic: dict[str, list[asyncpg.Record]] = defaultdict(list)
    for row in rows:
        by_topic[row["topic_name"]].append(row)

    rng = random.Random(args.seed)
    picked = []
    for topic_name in sorted(by_topic):
        group = by_topic[topic_name]
        for row in rng.sample(group, min(args.per_topic, len(group))):
            picked.append(
                {
                    "group_id": row["group_id"],
                    "topic_name": row["topic_name"],
                    "title": row["title"],
                    "description": row["description"],
                    #: The pipeline's own query, from the pipeline's own function.
                    "query": build_query(row["topic_name"], row["title"], row["description"]),
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(picked, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(picked)} queries across {len(by_topic)} topics -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
