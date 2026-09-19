#!/usr/bin/env python3
"""Renumber segment indices in review-stg-29.json from position 27 onward.

Positions 0-26 already carry correct indices 0-26. Positions 27..107 are
mislabeled 17..97 (duplicating earlier indices). Renumber them 27..107.
Only the "index" field is touched; all other fields and formatting preserved.
"""
import json

path = "data/transcripts/review-stg-29.json"

with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

segs = data["segments"]
n = len(segs)
print(f"total segments: {n}")

# Sanity check: first 27 positions should already be 0..26
expected_head = list(range(27))
actual_head = [s["index"] for s in segs[:27]]
assert actual_head == expected_head, f"unexpected head indices: {actual_head}"

# Renumber from position 27 onward
for pos in range(27, n):
    segs[pos]["index"] = pos

# Verify uniqueness and sequential order
indices = [s["index"] for s in segs]
assert indices == list(range(n)), "indices not sequential after fix"

with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=2)
    fh.write("\n")

print("done. new indices:", indices[:30], "...", indices[-3:])
