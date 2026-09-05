# Retrieval eval (task 0038, Phase 3)

Measures how good `frog.retrieval` actually is at finding corpus passages for a subtopic.

> **The decision this was built to inform has been made without it** (owner,
> 2026-09-05): grounding takes the top 2 with no `min_score` floor, because the curated
> corpus covers a topic before that topic is live. See ADR-0089's amendment.
>
> The harness is kept, not deleted. It measures retrieval quality, which is still worth
> knowing before adding an ANN index, a reranker or hybrid retrieval — none of which
> should be chosen on intuition. Nothing currently blocks on it.

Three steps, two of them in containers because the query builder is `spoin`'s and the
embedder needs the GPU:

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
  -v "E:/spoin_bundle/scripts:/repo/scripts" -v "E:/spoin_bundle/.eval:/repo/.eval" \
  --entrypoint python api /repo/scripts/eval/build_queries.py \
  --out /repo/.eval/queries.json --per-topic 4
```

```bash
MSYS_NO_PATHCONV=1 docker compose --profile frog run --rm \
  -v "E:/spoin_bundle/scripts:/repo/scripts" -v "E:/spoin_bundle/.eval:/repo/.eval" \
  --entrypoint python frog /repo/scripts/eval/retrieve_pools.py \
  --queries /repo/.eval/queries.json --out /repo/.eval/pools.json
```

```bash
python scripts/eval/harness/build_artifact.py --preview .eval/local_preview.html
```

`MSYS_NO_PATHCONV=1` is not optional under Git Bash on this machine — without it the
container paths are rewritten into `C:/Program Files/...`.

`.eval/` is gitignored: every file in it rebuilds from the two commands above, and
`pools.json` is ~1MB. **Check `corpus_version()` against the files on disk before trusting
any retrieval number** — the corpus-authoring track commits continuously, and a stale
ingest once moved Bhagavad Gita top-1 from 0.418 to 0.701.

## The labelling page

`harness/build_artifact.py` bakes `pools.json` into `harness/harness.tpl.html` and writes
the page that is published as an Artifact with `capabilities: {db: {}}`. The owner marks
every passage that would genuinely help write a card; the page stores one document per
query at `judgements/<subtopic_group_id>` as `{marks: {chunk_id: true}, done, updatedAt}`,
and the final metrics are read back with the Artifact tool's `read_db`.

**Verify locally before publishing.** `--preview` writes a standalone copy wrapped in the
same head skeleton the Artifact runtime supplies, so the page can be served and driven
before it reaches the owner. The harness shipped unverified once; a harness that loses
judgements halfway through is worse than no harness.

A judged query with nothing marked scores **precision 0** — that is the entire finding for
a topic the corpus does not cover (Physical Fitness, whose pool is 10m air-pistol passages
at 0.339). It stays out of recall only, where 0/0 is undefined rather than bad.
