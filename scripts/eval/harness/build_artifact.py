"""Bake `.eval/pools.json` into the labelling page.

The page is published as an Artifact with `capabilities: {db: {}}`; it stores one
document per query at `judgements/<subtopic_group_id>` and the final metrics are read
back with the Artifact tool's `read_db`. See docs/tasks/0038 Phase 3.

`--preview` also writes a standalone copy wrapped in the skeleton the Artifact runtime
supplies (doctype, charset, viewport, reset), so the page can be served and driven
locally BEFORE it is published. The harness once shipped unverified; this is the cheap
way not to repeat that.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

# Matches the head the Artifact runtime wraps a published page in.
SKELETON = """<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:light}
body{margin:0;font:14px system-ui,sans-serif}
img{max-width:100%%}
[hidden]{display:none!important}
</style>
</head><body>
%s
</body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pools", type=Path, default=ROOT / ".eval" / "pools.json")
    ap.add_argument("--out", type=Path, default=ROOT / ".eval" / "retrieval_judgements.html")
    ap.add_argument("--preview", type=Path, help="also write a locally servable copy")
    args = ap.parse_args()

    pools = json.loads(args.pools.read_text(encoding="utf-8"))
    template = (HERE / "harness.tpl.html").read_text(encoding="utf-8")

    # A literal "</script>" inside the JSON would close the script element early.
    payload = json.dumps(pools, ensure_ascii=False).replace("</", "<\\/")
    page = template.replace("__POOLS__", payload)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"{len(page):,} bytes -> {args.out}")

    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        args.preview.write_text(SKELETON % page, encoding="utf-8")
        print(f"preview -> {args.preview}")


if __name__ == "__main__":
    main()
