"""Inspect all 83 rows in phase-c-benchmark-manifest.json."""

import json
from pathlib import Path

MANIFEST_FILE = Path("phase-c-benchmark-manifest.json")
data = json.load(open(MANIFEST_FILE, encoding="utf-8"))
rows = data if isinstance(data, list) else data.get("rows", data.get("benchmarks", []))

print(f"Loaded {len(rows)} rows from {MANIFEST_FILE}")

bugs = [r for r in rows if r.get("kind") == "bug"]
controls = [r for r in rows if r.get("kind") == "control"]

print(f"Bugs: {len(bugs)}")
print(f"Controls: {len(controls)}")

print("\n--- 23 BUGS ---")
for i, b in enumerate(bugs):
    row_id = b["row_id"]
    repo = b["repository"]
    base = b.get("derived_base_sha") or b.get("real_fixed_sha")
    head = b.get("derived_head_sha") or b.get("real_buggy_sha")
    trig_cmd = b.get("trigger_command") or b.get("provenance", {}).get("trigger_command") or " ".join(b.get("trigger_on_buggy", {}).get("command", []))
    print(f"[{i+1:02d}] {row_id} | {repo.split('/')[-1]} | base={base[:8]} head={head[:8]} | trig={trig_cmd}")

print("\n--- 60 CONTROLS (sample first 10) ---")
for i, c in enumerate(controls[:10]):
    row_id = c["row_id"]
    repo = c["repository"]
    base = c.get("base_sha")
    head = c.get("head_sha")
    pr_num = c.get("pr_number")
    print(f"[{i+1:02d}] {row_id} | {repo.split('/')[-1]} | PR #{pr_num} | base={base[:8]} head={head[:8]}")
