# -*- coding: utf-8 -*-
"""Inspect entries with art details and create batch decisions."""
import json

entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))

def get_entry(idx):
    return entries[idx]

# Let's inspect specific ranges as needed
