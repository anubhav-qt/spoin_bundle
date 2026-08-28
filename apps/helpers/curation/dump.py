# -*- coding: utf-8 -*-
"""Dump a slice of entries for review, bounded by an art-line budget.

Usage: python dump.py entries.json <start_index> <line_budget>
Prints entries starting at start_index until the budget is spent, then prints
NEXT=<index> so the caller knows where to resume.
"""
import io, json, sys

entries = json.load(io.open(sys.argv[1], encoding="utf-8"))
start = int(sys.argv[2])
budget = int(sys.argv[3])

i = start
used = 0
while i < len(entries) and (used == 0 or used + entries[i]["lines"] <= budget):
    e = entries[i]
    print(f'#{i} [{e["src"]}/{e["cat"]}/{e["sub"]}] {e["id"]} :: {e["title"]}')
    print(e["art"])
    print("~~~")
    used += e["lines"]
    i += 1

print(f"NEXT={i} OF={len(entries)} LINES_USED={used}")
