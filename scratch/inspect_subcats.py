import json, sys

entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))
start = int(sys.argv[1])
end = int(sys.argv[2])

for i in range(start, min(end, len(entries))):
    e = entries[i]
    print(f"{i:4d}: [{e['cat']}/{e['sub']}] {e['id']} :: {e['title'][:60]} ({e['size']})")
