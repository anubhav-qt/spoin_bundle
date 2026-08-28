# -*- coding: utf-8 -*-
"""Apply the review decisions and rewrite both curated library files.

    python apply.py entries.json decisions/ out_gags.txt out_info.txt

Reads every `decisions/*.tsv`, requires a decision for EVERY entry index in
entries.json, and rewrites the two library files with the surviving entries.

Refuses to write anything if the decision set is incomplete or malformed --
a half-applied curation pass that silently keeps stale titles is worse than
no pass at all, because nothing downstream can tell the difference.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

VALID = {"KEEP", "RETITLE", "DELETE", "ASK"}
DELETE_REASONS = {"nsfw", "unclear", "unsuitable", "duplicate", "broken"}

HEADER = {
    "gags": (
        "# SPOIN ASCII REFERENCE LIBRARY — USE FOR GAGS & SCENE HOOKS\n"
        "# Total High-Clarity Curated Artwork Cards: {n}\n"
        "# Width Limit: <= 40 monospace characters (phone card safe)\n"
        "# Every TITLE describes what the art actually SHOWS, and is unique.\n"
        "# Best for: Comedic character reactions, silly animals, facial expressions,"
        " memes, punchy hooks\n"
        "# Format: Header with explicit TITLE followed by triple-backtick fenced ASCII art\n"
    ),
    "info": (
        "# SPOIN ASCII REFERENCE LIBRARY — USE FOR INFORMATIVE VISUALIZATION\n"
        "# Total High-Clarity Curated Artwork Cards: {n}\n"
        "# Width Limit: <= 40 monospace characters (phone card safe)\n"
        "# Every TITLE describes what the art actually SHOWS, and is unique.\n"
        "# Best for: Hardware/computers, scientific concepts, books/scrolls, checklists,"
        " tools, real-world objects\n"
        "# Format: Header with explicit TITLE followed by triple-backtick fenced ASCII art\n"
    ),
}


def load_decisions(folder: str) -> dict[int, tuple[str, str]]:
    decisions: dict[int, tuple[str, str]] = {}
    files = sorted(glob.glob(os.path.join(folder, "*.tsv")))
    if not files:
        sys.exit(f"no decision files found in {folder}")
    for path in files:
        for lineno, raw in enumerate(io.open(path, encoding="utf-8"), start=1):
            if not raw.strip():
                continue
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 2:
                sys.exit(f"{path}:{lineno}: expected `index<TAB>ACTION<TAB>payload`")
            idx_s, action = parts[0], parts[1].strip()
            payload = parts[2].strip() if len(parts) > 2 else ""
            if action not in VALID:
                sys.exit(f"{path}:{lineno}: unknown action {action!r} (valid: {sorted(VALID)})")
            idx = int(idx_s)
            if idx in decisions:
                sys.exit(f"{path}:{lineno}: index {idx} decided twice")
            if action == "RETITLE" and not payload:
                sys.exit(f"{path}:{lineno}: RETITLE needs a new title")
            if action == "DELETE" and payload not in DELETE_REASONS:
                sys.exit(
                    f"{path}:{lineno}: DELETE reason {payload!r} not in {sorted(DELETE_REASONS)}"
                )
            decisions[idx] = (action, payload)
    return decisions


def main() -> None:
    entries_path, folder, out_gags, out_info = sys.argv[1:5]
    entries = json.load(io.open(entries_path, encoding="utf-8"))
    decisions = load_decisions(folder)

    missing = [i for i in range(len(entries)) if i not in decisions]
    if missing:
        sys.exit(
            f"INCOMPLETE: {len(missing)} of {len(entries)} entries have no decision. "
            f"First missing indexes: {missing[:20]}"
        )

    asks = [i for i, (a, _) in decisions.items() if a == "ASK"]
    if asks:
        sys.exit(
            f"{len(asks)} entries are still marked ASK and need a human answer before "
            f"applying: {asks[:40]}"
        )

    kept: list[dict] = []
    for i, e in enumerate(entries):
        action, payload = decisions[i]
        if action == "DELETE":
            continue
        title = payload if action == "RETITLE" else e["title"]
        # A KEEP whose title still carries the scraped `(WxH)` suffix is a
        # review miss, not an intentional keep -- the suffix is noise for the
        # embedding retrieval this library exists to feed.
        if re.search(r"\(\d+x\d+\)\s*$", title):
            sys.exit(f"index {i}: title still ends in a (WxH) size suffix: {title!r}")
        e = dict(e)
        e["title"] = title
        # U+00A0 is invisible but is NOT a monospace space in every renderer --
        # it silently breaks the column alignment the 40-char budget protects.
        e["art"] = e["art"].replace(" ", " ")
        kept.append(e)

    # Titles are the retrieval key (content/ascii_library.py embeds them), so a
    # duplicate title means two entries compete for the same query forever.
    seen: dict[str, int] = {}
    for n, e in enumerate(kept):
        key = e["title"].strip().lower()
        if key in seen:
            sys.exit(f"duplicate title after curation: {e['title']!r} (entries {seen[key]} and {n})")
        seen[key] = n

    # IDs must be unique: they are how a curated piece is cited back.
    used: set[str] = set()
    for e in kept:
        base = e["id"]
        if base in used:
            k = 2
            while f"{base}-{k}" in used:
                k += 1
            base = f"{base}-{k}"
        e["id"] = base
        used.add(base)

    for src, out in (("gags", out_gags), ("info", out_info)):
        rows = [e for e in kept if e["src"] == src]
        with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(HEADER[src].format(n=len(rows)))
            for e in rows:
                lines = e["art"].split("\n")
                w = max((len(x) for x in lines), default=0)
                fh.write(
                    f"\n=== ID: {e['id']} | TITLE: {e['title']} | ARTIST: {e['artist']} | "
                    f"CATEGORY: {e['cat']} | SUBCATEGORY: {e['sub']} | "
                    f"SIZE: {w}x{len(lines)} ===\n```\n{e['art']}\n```\n"
                )
        print(f"wrote {out}: {len(rows)} entries")

    dropped = len(entries) - len(kept)
    print(f"kept {len(kept)} / {len(entries)}  (deleted {dropped})")


if __name__ == "__main__":
    main()
