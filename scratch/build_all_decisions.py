# -*- coding: utf-8 -*-
"""Master Curation Engine for SPOIN ASCII Library (Indexes 189 to 2486)."""
import json, re, io, os, sys
from collections import Counter, defaultdict

ENTRIES = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))

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

NSFW_SUBS = {
    "naughty", "sexual/other", "sexual/women", "playboy", "bikinis", "underwear", "nightwears", "bra"
}

def norm_title(t: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return " ".join(sorted(w for w in t.split() if w not in STOP))

print(f"Loaded {len(ENTRIES)} entries.")
