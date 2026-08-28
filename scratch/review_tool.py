# -*- coding: utf-8 -*-
import json, sys

def dump_range(start, end):
    entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))
    for i in range(start, min(end, len(entries))):
        e = entries[i]
        print(f"=== {i} [{e['src']}/{e['cat']}/{e['sub']}] {e['id']} :: {e['title']} ===")
        print(e['art'])
        print("-" * 40)

if __name__ == "__main__":
    start = int(sys.argv[1])
    end = int(sys.argv[2])
    dump_range(start, end)
