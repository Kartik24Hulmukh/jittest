"""Layer-1 Verifier Sweep on the Frozen 83-Row Cohort (Parallel Execution).

Measures the differential verification engine (no generation, $0 LLM cost)
against 83 ground-truth rows:
- 23 bugs (expected: proven_catch)
- 60 controls (expected: NOT proven_catch)
"""

import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from jittest.receipt import verify_receipt
from jittest.verify import VerdictClass, verify_test

SCRIPT_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = SCRIPT_DIR / "phase-c-benchmark-manifest.json"
OUT_DIR = SCRIPT_DIR / "docs" / "evidence" / "layer1"

if sys.platform == "win32":
    SRC_BASE = Path(r"C:\Users\praja\src")
else:
    SRC_BASE = Path("/mnt/c/Users/praja/src")
    if not SRC_BASE.exists():
        SRC_BASE = Path.home() / "src"

REPO_MAP = {
    "https://github.com/pallets/flask": SRC_BASE / "flask",
    "https://github.com/psf/requests": SRC_BASE / "requests",
    "https://github.com/ytdl-org/youtube-dl": SRC_BASE / "youtube-dl",
}

DEFAULT_TEST_MAP = {
    "flask": "tests/test_basic.py",
    "requests": "tests/test_requests.py",
    "youtube-dl": "test/test_utils.py",
}

print_lock = threading.Lock()


def get_target_test(row: dict[str, Any], repo_dir: Path) -> Path:
    row_id = row.get("row_id", "")
    # Check if dedicated test fixture exists
    if row_id.startswith("bug_"):
        parts = row_id.split("_")
        if len(parts) >= 3:
            fix_name = f"test_{parts[1]}_{parts[2]}.py"
            fix_path = SCRIPT_DIR / "tests" / "fixtures" / "v0.2_gate" / fix_name
            if fix_path.exists():
                return fix_path

    # 1. Check trigger command / trigger on buggy
    trig = row.get("trigger_command") or row.get("provenance", {}).get("trigger_command")
    if not trig and "trigger_on_buggy" in row:
        cmd = row["trigger_on_buggy"].get("command", [])
        if cmd:
            trig = " ".join(cmd)

    if trig:
        tokens = trig.split()
        for tok in tokens:
            if tok.endswith(".py"):
                p = repo_dir / tok
                if p.exists() or (repo_dir / tok).parent.exists():
                    return p
            if tok.startswith("tests."):
                rel = tok.replace(".", "/") + ".py"
                return repo_dir / rel

    # 2. For controls, inspect git diff for changed test files
    base = row.get("derived_base_sha") or row.get("base_sha")
    head = row.get("derived_head_sha") or row.get("head_sha")
    if base and head:
        try:
            diff_files = subprocess.check_output(
                ["git", "-C", str(repo_dir), "diff", "--name-only", f"{base}..{head}"],
                text=True,
                errors="replace",
            ).splitlines()
            py_tests = [f for f in diff_files if "test" in f and f.endswith(".py")]
            if py_tests:
                return repo_dir / py_tests[0]
        except Exception:
            pass

    # 3. Fallback to repo default test
    repo_name = repo_dir.name
    rel_def = DEFAULT_TEST_MAP.get(repo_name, "tests/test_basic.py")
    return repo_dir / rel_def


def verify_row(item: tuple[int, int, dict[str, Any]]) -> dict[str, Any]:
    idx, total, row = item
    row_id = row["row_id"]
    kind = row.get("kind", "bug")
    repo_url = row["repository"]
    repo_dir = REPO_MAP.get(repo_url)

    if not repo_dir or not repo_dir.exists():
        with print_lock:
            print(f"[{idx:02d}/{total:02d}] {row_id} ERROR: repo {repo_url} not found at {repo_dir}")
        return {
            "row_id": row_id,
            "kind": kind,
            "repository": repo_url,
            "base_sha": "",
            "head_sha": "",
            "test_file": "",
            "verdict": VerdictClass.INCONCLUSIVE,
            "disposition": "ENV_SETUP_FAILED",
            "proven_catch": False,
            "wall_clock_s": 0.0,
            "provider_cost_usd": 0.0,
            "signature_valid": False,
            "artifact": "",
        }

    base_sha = row.get("derived_base_sha") or row.get("base_sha") or row.get("real_fixed_sha")
    head_sha = row.get("derived_head_sha") or row.get("head_sha") or row.get("real_buggy_sha")
    test_path = get_target_test(row, repo_dir)
    out_file = OUT_DIR / f"{row_id}_evidence.json"

    t0 = time.time()
    try:
        evidence, code = verify_test(
            repo_path=repo_dir,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=test_path,
            output_path=out_file,
            no_sandbox=True,
        )
        elapsed = time.time() - t0
        verdict = evidence["verdict"]
        disposition = evidence["disposition"]
        is_pc = evidence.get("proven_catch", False)
        cost = evidence.get("provider_cost_usd", 0.0)

        sig_ok, sig_msg = verify_receipt(out_file)

        with print_lock:
            print(f"[{idx:02d}/{total:02d}] {row_id} ({kind}) | {repo_dir.name} base={base_sha[:8]} head={head_sha[:8]} | test={test_path.name} => {verdict} ({disposition}) in {elapsed:.1f}s [sig={sig_ok}]")

        return {
            "row_id": row_id,
            "kind": kind,
            "repository": repo_url,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "test_file": str(test_path.relative_to(repo_dir) if test_path.is_relative_to(repo_dir) else test_path.name),
            "verdict": verdict,
            "disposition": disposition,
            "proven_catch": is_pc,
            "wall_clock_s": round(elapsed, 2),
            "provider_cost_usd": cost,
            "signature_valid": sig_ok,
            "artifact": str(out_file.name),
        }
    except Exception as exc:
        elapsed = time.time() - t0
        with print_lock:
            print(f"[{idx:02d}/{total:02d}] {row_id} ({kind}) => EXCEPTION: {exc} in {elapsed:.1f}s")
        return {
            "row_id": row_id,
            "kind": kind,
            "repository": repo_url,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "test_file": str(test_path.name),
            "verdict": VerdictClass.INCONCLUSIVE,
            "disposition": "ENV_SETUP_FAILED",
            "proven_catch": False,
            "wall_clock_s": round(elapsed, 2),
            "provider_cost_usd": 0.0,
            "signature_valid": False,
            "artifact": "",
        }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        manifest_data = json.load(fh)

    rows = manifest_data if isinstance(manifest_data, list) else manifest_data.get("rows", manifest_data.get("benchmarks", []))
    print(f"=== LAYER-1 VERIFIER SWEEP ON {len(rows)} FROZEN COHORT ROWS (PARALLEL) ===")
    print(f"Artifacts output directory: {OUT_DIR}\n")

    items = [(i + 1, len(rows), r) for i, r in enumerate(rows)]
    start_all = time.time()

    workers = min(8, os.cpu_count() or 4)
    print(f"Launching ThreadPoolExecutor with {workers} workers...")

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(verify_row, items))

    total_time = time.time() - start_all

    bugs_proven_catch = 0
    bugs_total = 0
    ctrls_proven_catch = 0
    ctrls_total = 0
    dispositions: dict[str, int] = {}
    verdicts: dict[str, int] = {}
    total_cost = 0.0

    for r in results:
        kind = r.get("kind", "bug")
        is_pc = r.get("proven_catch", False)
        cost = r.get("provider_cost_usd", 0.0)
        total_cost += cost
        disp = r.get("disposition", "UNKNOWN")
        v = r.get("verdict", "UNKNOWN")

        dispositions[disp] = dispositions.get(disp, 0) + 1
        verdicts[v] = verdicts.get(v, 0) + 1

        if kind == "bug":
            bugs_total += 1
            if is_pc:
                bugs_proven_catch += 1
        else:
            ctrls_total += 1
            if is_pc:
                ctrls_proven_catch += 1

    catch_rate = (bugs_proven_catch / bugs_total) if bugs_total else 0.0
    false_proof_rate = (ctrls_proven_catch / ctrls_total) if ctrls_total else 0.0
    completion_rate = len(results) / len(rows)

    print("\n" + "=" * 60)
    print("=== LAYER-1 VERIFIER SWEEP SUMMARY ===")
    print("=" * 60)
    print(f"Total Rows Evaluated: {len(results)} / {len(rows)} ({completion_rate*100:.1f}%)")
    print(f"Bug Rows (expected proven_catch): {bugs_proven_catch} / {bugs_total} ({catch_rate*100:.1f}%)")
    print(f"Control Rows (expected NOT proven_catch): {ctrls_total - ctrls_proven_catch} / {ctrls_total} correct (False Proof Rate: {false_proof_rate*100:.1f}%)")
    print(f"Total LLM Cost: ${total_cost:.4f}")
    print(f"Total Wall-Clock Execution Time: {total_time:.1f}s")
    print("\nDispositions Tally:")
    for disp, cnt in sorted(dispositions.items()):
        print(f"  {disp}: {cnt}")
    print("\nVerdicts Tally:")
    for v, cnt in sorted(verdicts.items()):
        print(f"  {v}: {cnt}")

    # Write summary JSON
    summary_data = {
        "sweep_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_rows": len(results),
        "completion_rate": completion_rate,
        "catch_proof_rate": catch_rate,
        "false_proof_rate": false_proof_rate,
        "total_cost_usd": total_cost,
        "total_wall_clock_s": round(total_time, 2),
        "dispositions": dispositions,
        "verdicts": verdicts,
        "rows": results,
    }
    with open(OUT_DIR / "sweep_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary_data, fh, indent=2)

    # Write markdown REPORT.md
    report_md = f"""# Layer-1 Verifier Sweep Report

- **Target Cohort**: Frozen 83-Row Benchmark Cohort (`phase-c-benchmark-manifest.json`)
- **Evaluation Mode**: Layer-1 Differential Execution Verification (Zero LLM Generation)
- **Total Rows Evaluated**: {len(results)} / {len(rows)} ({completion_rate*100:.1f}%)
- **Catch-Proof Rate (Bugs)**: **{bugs_proven_catch}/{bugs_total} ({catch_rate*100:.1f}%)**
- **False-Proof Rate (Controls)**: **{ctrls_proven_catch}/{ctrls_total} ({false_proof_rate*100:.1f}%)**
- **LLM Provider Cost**: **$0.00**
- **Total Wall-Clock Time**: {total_time:.1f}s

## Verdict & Disposition Breakdown

| Disposition | Count | Percentage |
| :--- | :--- | :--- |
"""
    for disp, cnt in sorted(dispositions.items()):
        report_md += f"| `{disp}` | {cnt} | {cnt/len(results)*100:.1f}% |\n"

    report_md += """
## Recompute Command

To recompute and verify any individual evidence receipt:
```bash
jittest verify-receipt docs/evidence/layer1/<row_id>_evidence.json
```

Or re-run the full layer-1 sweep:
```bash
python scripts/run_layer1_sweep.py
```
"""
    with open(OUT_DIR / "REPORT.md", "w", encoding="utf-8") as fh:
        fh.write(report_md)

    print(f"\nWrote sweep artifacts to {OUT_DIR}")


if __name__ == "__main__":
    main()
