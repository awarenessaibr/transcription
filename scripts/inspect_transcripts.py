#!/usr/bin/env python3.10
"""Inspect all transcripts to understand formats and content."""
import json
import os
import glob

for f in sorted(glob.glob("data/transcripts/*.json")):
    name = os.path.basename(f)
    size = os.path.getsize(f)
    with open(f) as fp:
        d = json.load(fp)
    
    if isinstance(d, list):
        keys = list(d[0].keys()) if d and isinstance(d[0], dict) else "?"
        n = len(d)
        first_text = ""
        if d and isinstance(d[0], dict):
            first_text = d[0].get("text", "")[:80]
        # Check for any source_file references
        source = None
        for item in d[:3]:
            if isinstance(item, dict):
                source = item.get("source_file") or item.get("file") or item.get("audio_file")
        total_chars = sum(len(item.get("text", "")) for item in d if isinstance(item, dict))
        speakers = set()
        for item in d:
            if isinstance(item, dict) and "speaker" in item:
                speakers.add(item["speaker"])
        
        print(f"{name} ({size/1024:.0f}KB): array[{n}] speakers={sorted(speakers)} chars={total_chars}")
        print(f"  keys: {keys}")
        print(f"  first: {first_text}")
        if source:
            print(f"  source: {source}")
    elif isinstance(d, dict):
        print(f"{name} ({size/1024:.0f}KB): dict keys={list(d.keys())}")
        if "source_file" in d:
            print(f"  source: {d['source_file']}")
        if "segments" in d:
            print(f"  segments: {len(d['segments'])}")
    print()
