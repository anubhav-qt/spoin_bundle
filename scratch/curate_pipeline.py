# -*- coding: utf-8 -*-
import json, re, glob, os, sys
from collections import Counter

ENTRIES_PATH = r"C:\Temp\entries.json"
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

def check_title(title: str, seen_exact: set, seen_norm: set) -> list[str]:
    errs = []
    w = title.split()
    if len(w) < 4:
        errs.append(f"Under 4 words ({len(w)}): {title!r}")
    if re.search(r"\(\d+x\d+\)\s*$", title):
        errs.append(f"Has (WxH) suffix: {title!r}")
    for f in FILLER:
        if f in title.lower():
            errs.append(f"Contains filler {f!r}: {title!r}")
    k_exact = title.strip().lower()
    if k_exact in seen_exact:
        errs.append(f"Exact duplicate title: {title!r}")
    k_norm = norm_title(title)
    if k_norm in seen_norm:
        errs.append(f"Near-duplicate title: {title!r} (norm: {k_norm!r})")
    return errs

print("Validator ready.")
