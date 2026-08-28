# -*- coding: utf-8 -*-
"""Post-curation gate. Run against the REBUILT library files.

    python verify.py out_gags.txt out_info.txt

Checks the invariants the library's whole value rests on. Exits non-zero on
any failure, so it can be wired into CI or a make target later.

The important one is the near-duplicate title check: the pre-curation library
technically had 0 duplicate titles, yet 77% of entries shared a title once the
`(WxH)` suffix was stripped -- 40 mice all titled "little mouse with round
ears and curly tail (WxH)". Uniqueness alone is not the property that matters;
the property that matters is that two different pictures do not read as the
same picture to an embedding model, because `content/ascii_library.py` ranks
candidates by title similarity and near-identical titles collapse the entire
10-candidate budget onto one subject.
"""

from __future__ import annotations

import io
import re
import sys
from collections import Counter

PAT = re.compile(
    r"=== ID: (?P<id>\S+) \| TITLE: (?P<title>.*?) \| ARTIST: (?P<artist>.*?) \| "
    r"CATEGORY: (?P<cat>.*?) \| SUBCATEGORY: (?P<sub>.*?) \| SIZE: (?P<size>.*?) ===\n"
    r"```\n(?P<art>.*?)```",
    re.DOTALL,
)

FILLER = [
    "in distinct wildlife posture",
    "expressive pose",
    "practical tool utility everyday object",
    "apparel wardrobe fashion garment accessory",
    "pop culture television and cinema character",
    "geometric decorative graphic design pattern",
    "animal in distinct",
    "figurine",
]

MAX_WIDTH = 40


def main() -> None:
    entries = []
    for path in sys.argv[1:]:
        text = io.open(path, encoding="utf-8").read()
        for m in PAT.finditer(text):
            entries.append({k: m.group(k) for k in
                            ("id", "title", "artist", "cat", "sub", "art")} | {"file": path})

    fails: list[str] = []
    print(f"entries: {len(entries)}")

    # 1. width budget
    over = [(e["id"], len(x)) for e in entries for x in e["art"].split("\n") if len(x) > MAX_WIDTH]
    if over:
        fails.append(f"{len(over)} lines exceed {MAX_WIDTH} columns, e.g. {over[:5]}")

    # 2. exact-duplicate titles
    dup = [t for t, n in Counter(e["title"].strip().lower() for e in entries).items() if n > 1]
    if dup:
        fails.append(f"{len(dup)} duplicate titles, e.g. {dup[:5]}")

    # 3. leftover (WxH) suffixes -- the tell of an unrewritten scraped caption
    dims = [e["title"] for e in entries if re.search(r"\(\d+x\d+\)\s*$", e["title"])]
    if dims:
        fails.append(f"{len(dims)} titles still end in a (WxH) suffix, e.g. {dims[:5]}")

    # 4. filler phrases that describe nothing
    filler = [e["title"] for e in entries if any(f in e["title"].lower() for f in FILLER)]
    if filler:
        fails.append(f"{len(filler)} titles still use a generic filler phrase, e.g. {filler[:5]}")

    # 5. near-duplicate titles: identical once trivial words are dropped
    def norm(t: str) -> str:
        t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
        stop = {"a", "an", "the", "with", "and", "of", "in", "on", "its", "his", "her",
                "their", "at", "to", "from", "by", "for"}
        return " ".join(sorted(w for w in t.split() if w not in stop))

    near = [t for t, n in Counter(norm(e["title"]) for e in entries).items() if n > 1]
    if near:
        fails.append(f"{len(near)} near-duplicate titles (same words, reordered), e.g. {near[:5]}")

    # 6. duplicate IDs
    dupid = [i for i, n in Counter(e["id"] for e in entries).items() if n > 1]
    if dupid:
        fails.append(f"{len(dupid)} duplicate IDs, e.g. {dupid[:5]}")

    # 7. non-breaking spaces (invisible, break monospace alignment)
    nbsp = [e["id"] for e in entries if " " in e["art"]]
    if nbsp:
        fails.append(f"{len(nbsp)} entries contain U+00A0 NO-BREAK SPACE, e.g. {nbsp[:5]}")

    # 8. empty / trivially short titles
    thin = [e["title"] for e in entries if len(e["title"].split()) < 4]
    if thin:
        fails.append(f"{len(thin)} titles are under 4 words, e.g. {thin[:5]}")

    # 9. empty art
    empty = [e["id"] for e in entries if not e["art"].strip()]
    if empty:
        fails.append(f"{len(empty)} entries have empty art: {empty[:5]}")

    if fails:
        print("\nFAILED:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
