"""Mechanical generator for Layer-1B Modern Cohort Manifest (eval/layer1b_manifest.json).

Constructed purely via mechanical git commit inspection (zero LLM spend).
"""

import json
import random
import subprocess
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

FIXTURES_BASE = Path.home() / ".cache" / "jittest" / "fixtures"

REPOS = {
    "flask": {
        "url": "https://github.com/pallets/flask",
        "path": FIXTURES_BASE / "flask",
        "default_test": "tests/test_basic.py",
        "bug_target": 5,
        "ctrl_target": 4,
    },
    "requests": {
        "url": "https://github.com/psf/requests",
        "path": FIXTURES_BASE / "requests",
        "default_test": "tests/test_requests.py",
        "bug_target": 5,
        "ctrl_target": 4,
    },
    "click": {
        "url": "https://github.com/pallets/click",
        "path": FIXTURES_BASE / "click",
        "default_test": "tests/test_basic.py",
        "bug_target": 5,
        "ctrl_target": 4,
    },
    "httpx": {
        "url": "https://github.com/encode/httpx",
        "path": FIXTURES_BASE / "httpx",
        "default_test": "tests/test_api.py",
        "bug_target": 5,
        "ctrl_target": 4,
    },
    "rich": {
        "url": "https://github.com/Textualize/rich",
        "path": FIXTURES_BASE / "rich",
        "default_test": "tests/test_text.py",
        "bug_target": 5,
        "ctrl_target": 4,
    },
    "pytest": {
        "url": "https://github.com/pytest-dev/pytest",
        "path": FIXTURES_BASE / "pytest",
        "default_test": "testing/test_collection.py",
        "bug_target": 5,
        "ctrl_target": 4,
    },
}


def is_test_file(f: str) -> bool:
    f_norm = f.replace("\\", "/")
    if not f_norm.endswith(".py"):
        return False
    if f_norm.endswith("conftest.py"):
        return False
    parts = f_norm.split("/")
    return parts[0] in ("tests", "testing", "test") or any(p.startswith("test_") for p in parts)


def is_src_file(f: str) -> bool:
    f_norm = f.replace("\\", "/")
    if not f_norm.endswith(".py"):
        return False
    parts = f_norm.split("/")
    if parts[0] in ("tests", "testing", "test", "docs", "doc", "examples", "benchmarks", "scripts"):
        return False
    return True


def find_bug_rows(repo_name: str, config: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    path = config["path"]
    url = config["url"]
    
    cmd = [
        "git", "-C", str(path), "log",
        "-n", "500",
        "--since=2023-01-01", "--until=2026-08-15",
        "--no-merges",
        "--format=%H %ci %s"
    ]
    lines = subprocess.check_output(cmd, text=True, errors="replace").splitlines()
    
    candidates = []
    seen_shas = set()
    for line in lines:
        if not line.strip():
            continue
        parts = line.strip().split(" ", 4)
        sha = parts[0]
        date_str = f"{parts[1]} {parts[2]} {parts[3]}"
        subject = parts[4] if len(parts) > 4 else ""
        
        subj_lower = subject.lower()
        is_fix = any(w in subj_lower for w in ["fix", "bug", "resolve", "handle", "prevent", "error", "patch", "correct", "close"])
        if not is_fix:
            continue
            
        parents = subprocess.check_output(
            ["git", "-C", str(path), "rev-list", "--parents", "-n", "1", sha],
            text=True, errors="replace"
        ).split()[1:]
        if len(parents) != 1:
            continue
        parent_sha = parents[0]
        if sha in seen_shas or parent_sha in seen_shas or sha == parent_sha:
            continue
        
        diff_files = subprocess.check_output(
            ["git", "-C", str(path), "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
            text=True, errors="replace"
        ).splitlines()
        
        src_files = [f for f in diff_files if is_src_file(f)]
        test_files = [f for f in diff_files if is_test_file(f)]
        
        if src_files and test_files:
            test_file = test_files[0].replace("\\", "/")
            # Verify test file actually exists at base_sha
            try:
                subprocess.check_output(
                    ["git", "-C", str(path), "cat-file", "-e", f"{sha}:{test_file}"],
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                continue
                
            seen_shas.add(sha)
            candidates.append({
                "repo_name": repo_name,
                "repository": url,
                "base_sha": sha,
                "head_sha": parent_sha,
                "test": test_file,
                "commit_date": date_str,
                "commit_subject": subject,
                "derivation_command": f"git -C {repo_name} diff {parent_sha}..{sha} -- {test_file}",
            })
            if len(candidates) >= limit:
                break
                
    return candidates


def find_control_rows(repo_name: str, config: dict[str, Any], limit: int = 4) -> list[dict[str, Any]]:
    path = config["path"]
    url = config["url"]
    default_test = config["default_test"]
    
    cmd = [
        "git", "-C", str(path), "log",
        "-n", "300",
        "--since=2024-01-01", "--until=2026-08-15",
        "--no-merges",
        "--format=%H %ci %s"
    ]
    lines = subprocess.check_output(cmd, text=True, errors="replace").splitlines()
    
    candidates = []
    seen_shas = set()
    for line in lines:
        if not line.strip():
            continue
        parts = line.strip().split(" ", 4)
        sha = parts[0]
        date_str = f"{parts[1]} {parts[2]} {parts[3]}"
        subject = parts[4] if len(parts) > 4 else ""
        
        parents = subprocess.check_output(
            ["git", "-C", str(path), "rev-list", "--parents", "-n", "1", sha],
            text=True, errors="replace"
        ).split()[1:]
        if len(parents) != 1:
            continue
        parent_sha = parents[0]
        if sha in seen_shas or parent_sha in seen_shas or sha == parent_sha:
            continue
        
        diff_files = subprocess.check_output(
            ["git", "-C", str(path), "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
            text=True, errors="replace"
        ).splitlines()
        
        if not diff_files:
            continue
            
        is_docs_only = all(
            f.endswith((".md", ".rst", ".txt", ".png", ".svg", ".gif")) or
            (f.startswith(("docs/", "doc/")) and not f.endswith(".py"))
            for f in diff_files
        )
        
        if is_docs_only:
            seen_shas.add(sha)
            candidates.append({
                "repo_name": repo_name,
                "repository": url,
                "base_sha": sha,
                "head_sha": parent_sha,
                "test": default_test,
                "commit_date": date_str,
                "commit_subject": subject,
                "changed_files": diff_files,
                "derivation_command": f"git -C {repo_name} diff {parent_sha}..{sha} -- {' '.join(diff_files[:3])}",
            })
            if len(candidates) >= limit:
                break
                
    return candidates


def validate_manifest(manifest: dict[str, Any]) -> None:
    print("\n--- Validating Layer-1B Manifest ---")
    rows = manifest["rows"]
    all_row_ids = set()
    all_sha_pairs = set()
    
    for r in rows:
        row_id = r["row_id"]
        assert row_id not in all_row_ids, f"Duplicate row_id: {row_id}"
        all_row_ids.add(row_id)
        
        base = r["base_sha"]
        head = r["head_sha"]
        assert base, f"Missing base_sha in {row_id}"
        assert head, f"Missing head_sha in {row_id}"
        assert base != head, f"base_sha equals head_sha in {row_id}: {base}"
        
        pair = (r["repository"], base, head)
        assert pair not in all_sha_pairs, f"Duplicate commit pair in {row_id}: {pair}"
        all_sha_pairs.add(pair)
        
        repo_name = r["repo_name"]
        repo_path = REPOS[repo_name]["path"]
        
        # Verify base commit resolves
        base_chk = subprocess.run(
            ["git", "-C", str(repo_path), "cat-file", "-e", f"{base}^{{commit}}"],
            capture_output=True
        )
        assert base_chk.returncode == 0, f"base_sha {base} did not resolve in {repo_name}"
        
        # Verify head commit resolves
        head_chk = subprocess.run(
            ["git", "-C", str(repo_path), "cat-file", "-e", f"{head}^{{commit}}"],
            capture_output=True
        )
        assert head_chk.returncode == 0, f"head_sha {head} did not resolve in {repo_name}"

    print(f"Validation PASSED: {len(rows)} rows validated (every SHA resolves, base != head, no duplicates).")
    
    # Upstream spot check 3 random rows
    print("\n--- Upstream Spot Check (3 Random Rows) ---")
    random.seed(42)
    sample_rows = random.sample(rows, min(3, len(rows)))
    for s in sample_rows:
        repo_path = REPOS[s["repo_name"]]["path"]
        log_out = subprocess.check_output(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%H | %ci | %s", s["base_sha"]],
            text=True, errors="replace"
        ).strip()
        print(f"Spot check [{s['row_id']} - {s['repo_name']}]:")
        print(f"  Base: {log_out}")
        print(f"  Test: {s['test']}")
        print(f"  Derivation: {s['derivation_command']}")


def build_manifest() -> dict[str, Any]:
    print("Extracting candidate rows across modern repos...")
    all_bugs = []
    all_ctrls = []
    
    for repo_name, config in REPOS.items():
        bugs = find_bug_rows(repo_name, config, limit=config["bug_target"])
        ctrls = find_control_rows(repo_name, config, limit=config["ctrl_target"])
        print(f"[{repo_name}] Extracted {len(bugs)} bugs, {len(ctrls)} controls")
        all_bugs.extend(bugs)
        all_ctrls.extend(ctrls)
        
    formatted_rows = []
    # Add bugs
    for idx, b in enumerate(all_bugs, 1):
        r_id = f"bug_{b['repo_name']}_{idx:02d}"
        formatted_rows.append({
            "row_id": r_id,
            "kind": "bug",
            "repository": b["repository"],
            "repo_name": b["repo_name"],
            "base_sha": b["base_sha"],
            "head_sha": b["head_sha"],
            "test": b["test"],
            "commit_date": b["commit_date"],
            "commit_subject": b["commit_subject"],
            "derivation_command": b["derivation_command"],
        })
        
    # Add controls
    for idx, c in enumerate(all_ctrls, 1):
        r_id = f"ctrl_{c['repo_name']}_{idx:02d}"
        formatted_rows.append({
            "row_id": r_id,
            "kind": "control",
            "repository": c["repository"],
            "repo_name": c["repo_name"],
            "base_sha": c["base_sha"],
            "head_sha": c["head_sha"],
            "test": c["test"],
            "commit_date": c["commit_date"],
            "commit_subject": c["commit_subject"],
            "changed_files": c.get("changed_files", []),
            "derivation_command": c["derivation_command"],
        })
        
    manifest = {
        "schema_version": "1.0",
        "cohort_name": "layer1b_modern_cohort",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": "Layer-1B Modern Python Cohort (2023-2026 bug fixes and 2024-2026 docs-only controls across flask, requests, click, httpx, rich, pytest)",
        "total_rows": len(formatted_rows),
        "bug_rows_count": len(all_bugs),
        "control_rows_count": len(all_ctrls),
        "rows": formatted_rows,
    }
    
    validate_manifest(manifest)
    
    out_path = REPO_ROOT / "eval" / "layer1b_manifest.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        
    print(f"\nWrote manifest to {out_path} ({len(formatted_rows)} rows: {len(all_bugs)} bugs, {len(all_ctrls)} controls)")
    return manifest


if __name__ == "__main__":
    build_manifest()
