# -*- coding: utf-8 -*-
"""Assemble all batches, validate against verify.py rules, and write TSV files."""
import json, io, os, re, sys
from collections import Counter, defaultdict

import batch1, batch2, batch3, batch4, batch5

ENTRIES = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))
DECISIONS_DIR = r"e:\spoin_bundle\apps\helpers\curation\decisions"

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

STOP = {"a", "an", "the", "with", "and", "of", "in", "on", "its", "his", "her",
        "their", "at", "to", "from", "by", "for"}

def norm_title(t: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return " ".join(sorted(w for w in t.split() if w not in STOP))

# 1. Load 0000-0188.tsv
all_decisions = {}
ref_file = os.path.join(DECISIONS_DIR, "0000-0188.tsv")
for line in io.open(ref_file, encoding="utf-8"):
    if not line.strip(): continue
    parts = line.rstrip("\n").split("\t")
    idx = int(parts[0])
    act = parts[1].strip()
    payload = parts[2].strip() if len(parts) > 2 else ""
    all_decisions[idx] = (act, payload)

print(f"Loaded {len(all_decisions)} reference decisions from 0000-0188.tsv")

# 2. Merge batches
b1 = batch1.get_batch1()
b2 = batch2.get_batch2()
b3 = batch3.get_batch3()
b4 = batch4.get_batch4()
b5 = batch5.get_batch5()

for b, name in [(b1, "b1"), (b2, "b2"), (b3, "b3"), (b4, "b4"), (b5, "b5")]:
    for idx, dec in b.items():
        if idx in all_decisions:
            print(f"ERROR: Duplicate index {idx} in {name}")
        all_decisions[idx] = dec

print(f"Total merged decisions: {len(all_decisions)} (expected 2487: 0..2486)")

# Check missing
missing = [i for i in range(len(ENTRIES)) if i not in all_decisions]
if missing:
    print(f"MISSING {len(missing)} indexes: {missing[:30]}")
    sys.exit(1)

# 3. Validate titles
seen_exact = {}
seen_norm = defaultdict(list)
issues = []

for idx in range(len(ENTRIES)):
    act, payload = all_decisions[idx]
    e = ENTRIES[idx]
    if act == "DELETE":
        continue
    title = payload if act == "RETITLE" else e["title"]
    
    # word count
    words = title.split()
    if len(words) < 4:
        issues.append((idx, f"Under 4 words ({len(words)}): {title!r}"))
        
    # (WxH)
    if re.search(r"\(\d+x\d+\)\s*$", title):
        issues.append((idx, f"Ends in (WxH): {title!r}"))
        
    # filler
    for f in FILLER:
        if f in title.lower():
            issues.append((idx, f"Contains filler {f!r}: {title!r}"))
            
    # duplicate
    k_exact = title.strip().lower()
    if k_exact in seen_exact:
        issues.append((idx, f"Exact duplicate title with {seen_exact[k_exact]}: {title!r}"))
    else:
        seen_exact[k_exact] = idx
        
    k_norm = norm_title(title)
    seen_norm[k_norm].append((idx, title))

near_dups = {k: v for k, v in seen_norm.items() if len(v) > 1}
if near_dups:
    print(f"\nFound {len(near_dups)} near-duplicate title groups:")
    for k, v in list(near_dups.items())[:15]:
        print(f"  norm: {k!r} -> entries: {v}")

if issues:
    print(f"\nFound {len(issues)} title validation issues:")
    for idx, msg in issues[:20]:
        print(f"  [{idx}] {msg}")

# Function to write batch TSV
def write_batch_tsv(filename, start, end, b_dict):
    out_path = os.path.join(DECISIONS_DIR, filename)
    with io.open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        for idx in range(start, end + 1):
            act, payload = b_dict[idx]
            if payload:
                fh.write(f"{idx}\t{act}\t{payload}\n")
            else:
                fh.write(f"{idx}\t{act}\n")
    print(f"Wrote {out_path} with {end - start + 1} decisions ({start}..{end})")

if not issues and not near_dups:
    print("\nAll validation checks passed! Writing batch TSV files...")
    write_batch_tsv("0189-0500.tsv", 189, 500, all_decisions)
    write_batch_tsv("0501-0887.tsv", 501, 887, all_decisions)
    write_batch_tsv("0888-1400.tsv", 888, 1400, all_decisions)
    write_batch_tsv("1401-1900.tsv", 1401, 1900, all_decisions)
    write_batch_tsv("1901-2486.tsv", 1901, 2486, all_decisions)
    print("\nTSVs written successfully.")
