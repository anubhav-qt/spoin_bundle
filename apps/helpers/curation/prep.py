# -*- coding: utf-8 -*-
"""Parse both curated files into a working JSON, detect exact-duplicate art."""
import re, json, hashlib, io, sys
from collections import defaultdict

PAT = re.compile(
    r"=== ID: (?P<id>\S+) \| TITLE: (?P<title>.*?) \| ARTIST: (?P<artist>.*?) \| "
    r"CATEGORY: (?P<cat>.*?) \| SUBCATEGORY: (?P<sub>.*?) \| SIZE: (?P<size>.*?) ===\n"
    r"```\n(?P<art>.*?)```", re.DOTALL)

FILES = {
    "gags": "apps/helpers/use_for_gags.txt",
    "info": "apps/helpers/use_for_informative_visualization.txt",
}

entries = []
for src, path in FILES.items():
    text = io.open(path, encoding="utf-8").read()
    for i, m in enumerate(PAT.finditer(text)):
        art = m.group("art").rstrip("\n")
        entries.append({
            "src": src,
            "seq": i,
            "id": m.group("id"),
            "title": m.group("title").strip(),
            "artist": m.group("artist").strip(),
            "cat": m.group("cat").strip(),
            "sub": m.group("sub").strip(),
            "size": m.group("size").strip(),
            "art": art,
            "h": hashlib.sha1(art.encode()).hexdigest()[:12],
            "lines": art.count("\n") + 1,
        })

# exact duplicate art detection (across BOTH files)
by_hash = defaultdict(list)
for e in entries:
    by_hash[e["h"]].append(e)
dupes = {h: v for h, v in by_hash.items() if len(v) > 1}
dup_extra = sum(len(v) - 1 for v in dupes.values())

# duplicate IDs (the ID is supposed to be the key retrieval/citation uses)
by_id = defaultdict(list)
for e in entries:
    by_id[e["id"]].append(e)
dup_ids = {k: len(v) for k, v in by_id.items() if len(v) > 1}

# duplicate titles
by_title = defaultdict(list)
for e in entries:
    by_title[e["title"].lower()].append(e)
dup_titles = {k: len(v) for k, v in by_title.items() if len(v) > 1}

json.dump(entries, io.open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
print(f"entries: {len(entries)}  (gags={sum(1 for e in entries if e['src']=='gags')}, "
      f"info={sum(1 for e in entries if e['src']=='info')})")
print(f"exact-duplicate art groups: {len(dupes)}  redundant copies: {dup_extra}")
print(f"duplicate IDs: {len(dup_ids)} (worst: {sorted(dup_ids.items(), key=lambda x:-x[1])[:5]})")
print(f"duplicate titles: {len(dup_titles)} (worst: {sorted(dup_titles.items(), key=lambda x:-x[1])[:5]})")
print(f"total art lines: {sum(e['lines'] for e in entries)}")
