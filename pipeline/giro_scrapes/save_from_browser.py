#!/usr/bin/env python3
"""Helper: reads stage JSON from stdin and saves to stage_N.json"""
import json, sys

data = json.load(sys.stdin)
n = data['n']
outfile = f'stage_{n}.json'
with open(outfile, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print(f'Saved {outfile}: {len(data.get("rows", []))} rows')
