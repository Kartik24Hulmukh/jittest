"""Check control diff files for all 60 controls."""

import json
import subprocess
from pathlib import Path

MANIFEST_FILE = Path("phase-c-benchmark-manifest.json")
data = json.load(open(MANIFEST_FILE, encoding="utf-8"))
rows = data if isinstance(data, list) else data.get("rows", data.get("benchmarks", []))
controls = [r for r in rows if r.get("kind") == "control"]

repo_map = {
    "https://github.com/pallets/flask": Path.home() / "src" / "flask",
    "https://github.com/psf/requests": Path.home() / "src" / "requests",
    "https://github.com/ytdl-org/youtube-dl": Path.home() / "src" / "youtube-dl",
}

missing_commits = []

for i, c in enumerate(controls):
    r_path = repo_map[c["repository"]]
    base = c["base_sha"]
    head = c["head_sha"]
    try:
        diff_files = subprocess.check_output(
            ["git", "-C", str(r_path), "diff", "--name-only", f"{base}..{head}"],
            text=True,
            errors="replace",
        ).splitlines()
        test_files = [f for f in diff_files if "test" in f]
        primary_test = test_files[0] if test_files else None
        if not primary_test:
            # Fallback to a standard test in the repository if no test changed in the PR
            if "flask" in str(r_path):
                primary_test = "tests/test_basic.py"
            elif "requests" in str(r_path):
                primary_test = "tests/test_requests.py"
            else:
                primary_test = "test/test_utils.py"
        print(f"[{i+1:02d}] {c['row_id']} | changed={len(diff_files)} | target_test={primary_test}")
    except Exception as exc:
        print(f"[{i+1:02d}] {c['row_id']} | ERROR: {exc}")
        missing_commits.append((c["repository"], base, head))

print(f"\nMissing commits count: {len(missing_commits)}")
