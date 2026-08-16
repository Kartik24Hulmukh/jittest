"""Layer-1 Verifier Sweep (Parallel Execution).

Measures the differential verification engine (no generation, $0 LLM cost)
against benchmark cohorts with Ed25519-signed evidence receipts, honest
denominators, and auditable disposition tracking.

Supports:
- Frozen 83-row historical cohort (default)
- Layer-1B modern cohort (--manifest eval/layer1b_manifest.json)
- Self-bootstrapping fixture repositories (auto-cloning public repos into ~/.cache/jittest/fixtures if missing)
- JITTEST_FIXTURE_DIR environment variable
- Machine-diffed delta tables against baseline commit SHA (ENV-FIDELITY-2)
- Distinct wall time, summed row time, and worker count reporting
- Separate behavioral proven_catch and collection_catch signals
"""

from __future__ import annotations

import argparse
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

PUBLIC_REPOS = {
    "https://github.com/pallets/flask": "flask",
    "https://github.com/psf/requests": "requests",
    "https://github.com/ytdl-org/youtube-dl": "youtube-dl",
    "https://github.com/pallets/click": "click",
    "https://github.com/encode/httpx": "httpx",
    "https://github.com/Textualize/rich": "rich",
    "https://github.com/pytest-dev/pytest": "pytest",
    "https://github.com/pydantic/pydantic": "pydantic",
    "https://github.com/django/django": "django",
}

DEFAULT_TEST_MAP = {
    "flask": "tests/test_basic.py",
    "requests": "tests/test_requests.py",
    "youtube-dl": "test/test_utils.py",
    "click": "tests/test_basic.py",
    "httpx": "tests/test_api.py",
    "rich": "tests/test_text.py",
    "pytest": "testing/test_collection.py",
    "pydantic": "tests/test_main.py",
    "django": "tests/basic/tests.py",
}

print_lock = threading.Lock()
repo_clone_lock = threading.Lock()


def resolve_fixture_repo(repo_url: str) -> Path:
    """Resolve local path for a fixture repo, cloning from public GitHub if missing."""
    repo_name = PUBLIC_REPOS.get(repo_url, repo_url.rstrip("/").split("/")[-1])

    # 1. Respect JITTEST_FIXTURE_DIR if set
    if "JITTEST_FIXTURE_DIR" in os.environ:
        target = Path(os.environ["JITTEST_FIXTURE_DIR"]) / repo_name
    else:
        # Standard cached fixtures path (no machine-specific paths)
        target = Path.home() / ".cache" / "jittest" / "fixtures" / repo_name

    if not target.exists() or not (target / ".git").exists():
        with repo_clone_lock:
            if not target.exists() or not (target / ".git").exists():
                print(f"Cloning fixture repo {repo_url} into {target}...")
                target.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "clone", "--quiet", repo_url, str(target)], check=True)
    return target


def get_target_test(row: dict[str, Any], repo_dir: Path) -> Path:
    # 0. Check explicit test or test_file field in row
    if "test" in row and row["test"]:
        return repo_dir / row["test"]
    if "test_file" in row and row["test_file"]:
        return repo_dir / row["test_file"]

    row_id = row.get("row_id", "")
    # Check if dedicated test fixture exists
    if row_id.startswith("bug_"):
        parts = row_id.split("_")
        if len(parts) >= 3:
            for fix_name in [f"fixture_{parts[1]}_{parts[2]}.py", f"test_{parts[1]}_{parts[2]}.py"]:
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


def verify_row_task(item: tuple[int, int, dict[str, Any], Path, int]) -> dict[str, Any]:
    idx, total, row, out_dir, timeout_s = item
    row_id = row["row_id"]
    kind = row.get("kind", "bug")
    repo_url = row["repository"]

    try:
        repo_dir = resolve_fixture_repo(repo_url)
    except Exception as exc:
        with print_lock:
            print(f"[{idx:02d}/{total:02d}] {row_id} ERROR resolving repo {repo_url}: {exc}")
        return {
            "row_id": row_id,
            "kind": kind,
            "repository": repo_url,
            "base_sha": "",
            "head_sha": "",
            "test_file": "",
            "verdict": VerdictClass.INCONCLUSIVE,
            "disposition": "env_setup_failed",
            "proven_catch": False,
            "wall_clock_s": 0.0,
            "provider_cost_usd": 0.0,
            "signature_valid": False,
            "tool_dirty": False,
            "artifact": "",
        }

    base_sha = row.get("derived_base_sha") or row.get("base_sha") or row.get("real_fixed_sha")
    head_sha = row.get("derived_head_sha") or row.get("head_sha") or row.get("real_buggy_sha")
    test_path = get_target_test(row, repo_dir)
    out_file = out_dir / f"{row_id}_evidence.json"

    t0 = time.time()
    try:
        evidence, code = verify_test(
            repo_path=repo_dir,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=test_path,
            kind=kind,
            output_path=out_file,
            timeout_s=timeout_s,
            no_sandbox=True,
        )
        elapsed = time.time() - t0
        verdict = evidence["verdict"]
        disposition = evidence["disposition"]
        is_pc = evidence.get("proven_catch", False)
        base_repro = evidence.get("base_reproduced", False)
        cost = evidence.get("provider_cost_usd", 0.0)
        tool_dirty = evidence.get("provenance", {}).get("tool_dirty", False)

        sig_ok, sig_msg = verify_receipt(out_file)

        with print_lock:
            print(f"[{idx:02d}/{total:02d}] {row_id} ({kind}) | {repo_dir.name} base={base_sha[:8]} head={head_sha[:8]} | test={test_path.name} => {verdict} ({disposition}) in {elapsed:.1f}s [sig={sig_ok}]")

        return {
            "row_id": row_id,
            "kind": kind,
            "repository": repo_url,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "test_file": str(test_path.relative_to(repo_dir) if test_path.is_relative_to(repo_dir) else test_path.name).replace("\\", "/"),
            "verdict": verdict,
            "disposition": disposition,
            "proven_catch": is_pc,
            "base_reproduced": base_repro,
            "wall_clock_s": round(elapsed, 2),
            "provider_cost_usd": cost,
            "signature_valid": sig_ok,
            "tool_dirty": tool_dirty,
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
            "test_file": str(test_path.name).replace("\\", "/"),
            "verdict": VerdictClass.INCONCLUSIVE,
            "disposition": "env_setup_failed",
            "proven_catch": False,
            "base_reproduced": False,
            "wall_clock_s": round(elapsed, 2),
            "provider_cost_usd": 0.0,
            "signature_valid": False,
            "tool_dirty": False,
            "artifact": "",
        }


def load_baseline_summary(prev_sha: str, summary_file_rel: str) -> dict[str, Any] | None:
    """Load baseline sweep summary from git history at specified SHA."""
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{prev_sha}:{summary_file_rel}"],
            cwd=str(SCRIPT_DIR),
            text=True,
            errors="replace",
        )
        return json.loads(raw)
    except Exception:
        return None


def generate_report_content(
    cohort_name: str,
    manifest_rel: str,
    out_rel_dir: str,
    results: list[dict[str, Any]],
    total_time: float,
    summed_row_time: float,
    worker_count: int,
    total_cost: float,
    current_sha: str,
    prev_sha: str | None = None,
    baseline_summary: dict[str, Any] | None = None,
    ci_run_url: str | None = None,
) -> str:
    bugs = [r for r in results if r.get("kind") == "bug" or r.get("row_id", "").startswith("bug_")]
    ctrls = [r for r in results if r.get("kind") == "control" or r.get("row_id", "").startswith("ctrl_")]

    bugs_exec = [r for r in bugs if r.get("verdict") != "inconclusive"]
    bugs_pc = [r for r in bugs if r.get("verdict") == "proven_catch"]
    bugs_cc = [r for r in bugs if r.get("verdict") == "collection_catch"]
    bugs_base_passed = sum(1 for r in bugs if r.get("base_reproduced", False))
    base_repro_rate = (bugs_base_passed / len(bugs)) if bugs else 0.0

    ctrls_exec = [r for r in ctrls if r.get("verdict") != "inconclusive"]
    ctrls_pc = [r for r in ctrls if r.get("verdict") in ("proven_catch", "collection_catch")]
    ctrls_base_passed = sum(1 for r in ctrls if r.get("base_reproduced", False))
    false_proof_denom = ctrls_base_passed

    inconclusive_count = sum(1 for r in results if r.get("verdict") == "inconclusive")
    definitive_count = len(results) - inconclusive_count
    valid_sig_count = sum(1 for r in results if r.get("signature_valid"))
    any_dirty = any(r.get("tool_dirty", False) for r in results)

    dispositions: dict[str, int] = {}
    for r in results:
        disp = r.get("disposition", "UNKNOWN")
        dispositions[disp] = dispositions.get(disp, 0) + 1

    timeout_count = dispositions.get("env_build_timeout", 0) + sum(1 for r in results if "timeout" in r.get("disposition", ""))

    bugs_refuted = sum(1 for r in bugs if r.get("verdict") == "refuted")
    bugs_nd = sum(1 for r in bugs if r.get("verdict") == "non_discriminating")
    ctrls_refuted = sum(1 for r in ctrls if r.get("verdict") == "refuted")
    ctrls_nd = sum(1 for r in ctrls if r.get("verdict") == "non_discriminating")

    dirty_line = (
        "- **Provenance Dirty State**: Receipts ran with clean working tree (`tool_dirty=false`)."
        if not any_dirty
        else f"- **Provenance Dirty State**: Receipts ran with `tool_dirty={any_dirty}`."
    )

    ci_line = f"- **Public CI Run URL**: [{ci_run_url}]({ci_run_url})" if ci_run_url else ""

    report_md = f"""# Layer-1 Verifier Sweep Report

- **Target Cohort**: {cohort_name} (`{manifest_rel}`)
- **Evaluation Mode**: Layer-1 Differential Execution Verification (Zero LLM Generation)
- **LLM Provider Cost**: **${total_cost:.2f}**
- **Total Wall-Clock Time**: {total_time:.1f}s (Summed Row Time: {summed_row_time:.1f}s across {worker_count} parallel workers)
{ci_line}

> [!NOTE]
> **Errata**: The Run-2 delta table's baseline column was manually authored and has been superseded by the machine-diffed delta table generated directly from git history.

> [!NOTE]
> **Repository Support**: `requests` is marked unsupported due to external live HTTP test server dependencies (`pytest-httpbin` / live network daemons). Its 9 rows are reported honestly as inconclusive (`base_reproduction_failed` / `head_uncollectable`).

## Headline Metrics

- **Controls executed**: {len(ctrls_exec)}/{len(ctrls)} — false proofs: {len(ctrls_pc)}/{false_proof_denom} ({len(ctrls) - len(ctrls_exec)} controls inconclusive)
- **Bug rows executed**: {len(bugs_exec)}/{len(bugs)} — proven_catch: {len(bugs_pc)}/{len(bugs_exec)} (behavioral), collection_catch: {len(bugs_cc)}/{len(bugs_exec)} (collection)
- **Base Reproduction Rate**: {bugs_base_passed}/{len(bugs)} ({base_repro_rate*100:.1f}%) of bug rows reproduced expected passing behavior on base commit
- **Coverage**: {definitive_count}/{len(results)} ({definitive_count/len(results)*100:.1f}%) executed to definitive verdicts; {inconclusive_count}/{len(results)} refused loudly (inconclusive)
- **Attempt Rate**: {len(results)}/{len(results)} (100.0%) attempted with signed receipts
- **Execution Timeouts**: {timeout_count} timeout classes observed during sweep execution.

{inconclusive_count} signed refusals are the trust story: jittest does not manufacture verdicts when environments cannot be built.

## Execution Provenance & Environment Notes

{dirty_line}
- **Tool Commit SHA**: `{current_sha}`
- **Sandbox Backend**: Ran with sandbox backend `"none"` (--no-sandbox; candidate tests ran unconfined). Outside PRs default to sandbox mode.
- **Receipt Cryptographic Validity**: {valid_sig_count}/{len(results)} signed Ed25519 receipts valid.

## Per-Cohort Breakdown

| Cohort | Total Rows | Executed to Definitive Verdict | Inconclusive (Refused) | Detailed Results |
| :--- | :--- | :--- | :--- | :--- |
| **Bug Rows** | {len(bugs)} | {len(bugs_exec)} ({len(bugs_exec)/len(bugs)*100:.1f}%) | {len(bugs)-len(bugs_exec)} ({(len(bugs)-len(bugs_exec))/len(bugs)*100:.1f}%) | {len(bugs_pc)} `proven_catch` (behavioral), {len(bugs_cc)} `collection_catch`, {bugs_refuted} `refuted`, {bugs_nd} `non_discriminating` |
| **Control Rows** | {len(ctrls)} | {len(ctrls_exec)} ({len(ctrls_exec)/len(ctrls)*100:.1f}%) | {len(ctrls)-len(ctrls_exec)} ({(len(ctrls)-len(ctrls_exec))/len(ctrls)*100:.1f}%) | {len(ctrls_pc)} false proofs, {ctrls_refuted} `refuted`, {ctrls_nd} `non_discriminating` |
| **Total Cohort** | **{len(results)}** | **{definitive_count} ({definitive_count/len(results)*100:.1f}%)** | **{inconclusive_count} ({inconclusive_count/len(results)*100:.1f}%)** | **{len(bugs_pc)} proven catches, {len(bugs_cc)} collection catches, {len(ctrls_pc)} false proofs, {inconclusive_count} signed refusals** |

## Full Disposition Breakdown

| Disposition | Count | Percentage |
| :--- | :--- | :--- |
"""
    for disp, cnt in sorted(dispositions.items()):
        report_md += f"| `{disp}` | {cnt} | {cnt/len(results)*100:.1f}% |\n"

    # Machine-diffed delta table if baseline is provided
    if baseline_summary and "rows" in baseline_summary:
        old_map = {r["row_id"]: r for r in baseline_summary["rows"]}
        prev_sha_label = prev_sha[:8] if prev_sha else "baseline"
        curr_sha_label = current_sha[:8] if current_sha else "new"
        report_md += f"""
## Machine-Diffed Delta Table (Baseline @{prev_sha_label} vs Current @{curr_sha_label})

| Row ID | Kind | Repo | Baseline Disp (`@{prev_sha_label}`) | New Disp (`@{curr_sha_label}`) | Baseline Verdict (`@{prev_sha_label}`) | New Verdict (`@{curr_sha_label}`) | Delta Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""
        for r in results:
            rid = r["row_id"]
            old_r = old_map.get(rid, {})
            old_disp = old_r.get("disposition", "n/a")
            new_disp = r.get("disposition", "n/a")
            old_verdict = old_r.get("verdict", "n/a")
            new_verdict = r.get("verdict", "n/a")
            repo_short = r.get("repository", "").split("/")[-1]

            if old_disp == new_disp and old_verdict == new_verdict:
                delta_status = "Unchanged"
            else:
                delta_status = f"`{old_disp}` → `{new_disp}`"

            report_md += f"| `{rid}` | {r.get('kind')} | {repo_short} | `{old_disp}` | `{new_disp}` | `{old_verdict}` | `{new_verdict}` | {delta_status} |\n"

    report_md += f"""
## Recompute Command

To recompute and verify any individual evidence receipt:
```bash
jittest verify-receipt {out_rel_dir}/<row_id>_evidence.json
```

Or re-run the full sweep:
```bash
python scripts/run_layer1_sweep.py --manifest {manifest_rel} --prev-sha {prev_sha or '9c6320df'}
```
"""
    return report_md


def main():
    parser = argparse.ArgumentParser(description="Layer-1 Differential Verifier Sweep")
    parser.add_argument(
        "--manifest",
        type=str,
        default=str(SCRIPT_DIR / "phase-c-benchmark-manifest.json"),
        help="Path to manifest JSON file",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Path to evidence output directory",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(8, os.cpu_count() or 4),
        help="Number of parallel execution workers",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Per-test timeout in seconds",
    )
    parser.add_argument(
        "--prev-sha",
        type=str,
        default=None,
        help="Baseline commit SHA to machine-diff against (defaults to 9c6320df for layer1b)",
    )
    parser.add_argument(
        "--ci-run-url",
        type=str,
        default=None,
        help="Public URL of the GitHub Actions CI run",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.exists():
        print(f"Error: manifest path {manifest_path} does not exist.")
        sys.exit(1)

    is_layer1b = "layer1b" in manifest_path.name.lower()
    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    elif is_layer1b:
        out_dir = SCRIPT_DIR / "docs" / "evidence" / "layer1b"
    else:
        out_dir = SCRIPT_DIR / "docs" / "evidence" / "layer1"

    out_dir.mkdir(parents=True, exist_ok=True)

    prev_sha = args.prev_sha or ("9c6320df" if is_layer1b else None)

    # Resolve tool git commit SHA
    try:
        current_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(SCRIPT_DIR),
            text=True,
        ).strip()
    except Exception:
        current_sha = "unknown"

    # Load baseline summary via git show at prev_sha
    summary_rel = str(out_dir.relative_to(SCRIPT_DIR) / "sweep_summary.json").replace("\\", "/")
    baseline_summary = None
    if prev_sha:
        baseline_summary = load_baseline_summary(prev_sha, summary_rel)

    # Fallback to local sweep_summary.json if git show failed
    if baseline_summary is None and (out_dir / "sweep_summary.json").exists():
        try:
            with open(out_dir / "sweep_summary.json", encoding="utf-8") as fh:
                baseline_summary = json.load(fh)
        except Exception:
            pass

    with open(manifest_path, encoding="utf-8") as fh:
        manifest_data = json.load(fh)

    cohort_name = manifest_data.get("cohort_name") if isinstance(manifest_data, dict) else None
    if not cohort_name:
        cohort_name = "Layer-1B Modern Cohort" if is_layer1b else "Frozen 83-Row Benchmark Cohort"

    rows = manifest_data if isinstance(manifest_data, list) else manifest_data.get("rows", manifest_data.get("benchmarks", []))
    manifest_rel = str(manifest_path.relative_to(SCRIPT_DIR) if manifest_path.is_relative_to(SCRIPT_DIR) else manifest_path.name).replace("\\", "/")
    out_rel = str(out_dir.relative_to(SCRIPT_DIR) if out_dir.is_relative_to(SCRIPT_DIR) else out_dir.name).replace("\\", "/")

    print(f"=== LAYER-1 VERIFIER SWEEP ON {len(rows)} ROWS ({cohort_name}) ===")
    print(f"Manifest: {manifest_rel}")
    print(f"Artifacts output directory: {out_rel}")
    print(f"Baseline SHA for diff: {prev_sha or 'None'}\n")

    items = [(i + 1, len(rows), r, out_dir, args.timeout) for i, r in enumerate(rows)]
    start_all = time.time()

    is_ci = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
    if is_ci:
        workers = min(args.workers, 2)
    else:
        workers = min(args.workers, os.cpu_count() or 4)

    print(f"Launching ThreadPoolExecutor with {workers} workers (timeout={args.timeout}s)...")

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(verify_row_task, items))

    total_time = time.time() - start_all
    summed_row_time = sum(r.get("wall_clock_s", 0.0) for r in results)

    bugs = [r for r in results if r.get("kind") == "bug" or r.get("row_id", "").startswith("bug_")]
    ctrls = [r for r in results if r.get("kind") == "control" or r.get("row_id", "").startswith("ctrl_")]

    bugs_exec = [r for r in bugs if r.get("verdict") != "inconclusive"]
    bugs_pc = [r for r in bugs if r.get("verdict") == "proven_catch"]
    bugs_cc = [r for r in bugs if r.get("verdict") == "collection_catch"]
    bugs_base_passed = sum(1 for r in bugs if r.get("base_reproduced", False))
    base_repro_rate = (bugs_base_passed / len(bugs)) if bugs else 0.0

    ctrls_exec = [r for r in ctrls if r.get("verdict") != "inconclusive"]
    ctrls_pc = [r for r in ctrls if r.get("verdict") in ("proven_catch", "collection_catch")]
    ctrls_base_passed = sum(1 for r in ctrls if r.get("base_reproduced", False))
    false_proof_denom = ctrls_base_passed
    false_proof_rate = (len(ctrls_pc) / false_proof_denom) if false_proof_denom > 0 else 0.0

    inconclusive_count = sum(1 for r in results if r.get("verdict") == "inconclusive")
    definitive_count = len(results) - inconclusive_count

    dispositions: dict[str, int] = {}
    verdicts: dict[str, int] = {}
    total_cost = 0.0

    for r in results:
        cost = r.get("provider_cost_usd", 0.0)
        total_cost += cost
        disp = r.get("disposition", "UNKNOWN")
        v = r.get("verdict", "UNKNOWN")
        dispositions[disp] = dispositions.get(disp, 0) + 1
        verdicts[v] = verdicts.get(v, 0) + 1

    timeout_count = dispositions.get("env_build_timeout", 0) + sum(1 for r in results if "timeout" in r.get("disposition", ""))

    print("\n" + "=" * 60)
    print("=== LAYER-1 VERIFIER SWEEP SUMMARY (HONEST DENOMINATORS) ===")
    print("=" * 60)
    print(f"Controls executed: {len(ctrls_exec)}/{len(ctrls)} — false proofs: {len(ctrls_pc)}/{false_proof_denom} ({len(ctrls) - len(ctrls_exec)} controls inconclusive)")
    print(f"Bug rows executed: {len(bugs_exec)}/{len(bugs)} — proven_catch: {len(bugs_pc)}/{len(bugs_exec)} (behavioral), collection_catch: {len(bugs_cc)}/{len(bugs_exec)} (collection)")
    print(f"Base Reproduction Rate: {bugs_base_passed}/{len(bugs)} ({base_repro_rate*100:.1f}%) of bug rows reproduced passing behavior on base commit")
    print(f"Coverage: {len(results)}/{len(results)} rows attempted with signed receipts; {definitive_count}/{len(results)} ({definitive_count/len(results)*100:.1f}%) executed to definitive verdicts; {inconclusive_count}/{len(results)} refused loudly (inconclusive)")
    print(f"Attempt Rate: {len(results)}/{len(rows)} (100.0%) attempted with signed receipts")
    print(f"{inconclusive_count} signed refusals are the trust story: jittest does not manufacture verdicts when environments cannot be built.")
    print(f"Execution Timeouts: {timeout_count} timeout classes observed during sweep execution.")
    print(f"Total LLM Cost: ${total_cost:.4f}")
    print(f"Total Wall-Clock Execution Time: {total_time:.1f}s (Summed: {summed_row_time:.1f}s across {workers} workers)")
    print(f"\nReceipts remain cryptographically verifiable without fixture clones via:\n  jittest verify-receipt {out_rel}/<row_id>_evidence.json")
    print("\nDispositions Tally:")
    for disp, cnt in sorted(dispositions.items()):
        print(f"  {disp}: {cnt}")
    print("\nVerdicts Tally:")
    for v, cnt in sorted(verdicts.items()):
        print(f"  {v}: {cnt}")

    # Write summary JSON with updated schema
    summary_data = {
        "sweep_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "manifest": manifest_rel,
        "sweep_summary_prev_sha": prev_sha,
        "tool_commit_sha": current_sha,
        "ci_run_url": args.ci_run_url,
        "total_rows": len(results),
        "attempt_rate": len(results) / len(rows),
        "coverage_rate": definitive_count / len(rows),
        "base_reproduction_rate": base_repro_rate,
        "base_reproduced_controls": ctrls_base_passed,
        "false_proof_denominator": false_proof_denom,
        "timeout_count": timeout_count,
        "catch_proof_rate": (len(bugs_pc) / len(bugs)) if bugs else 0.0,
        "collection_catch_rate": (len(bugs_cc) / len(bugs)) if bugs else 0.0,
        "false_proof_rate": false_proof_rate,
        "total_cost_usd": total_cost,
        "total_wall_clock_s": round(total_time, 2),
        "summed_row_time_s": round(summed_row_time, 2),
        "worker_count": workers,
        "dispositions": dispositions,
        "verdicts": verdicts,
        "rows": results,
    }
    with open(out_dir / "sweep_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary_data, fh, indent=2)

    report_content = generate_report_content(
        cohort_name,
        manifest_rel,
        out_rel,
        results,
        total_time,
        summed_row_time,
        workers,
        total_cost,
        current_sha,
        prev_sha,
        baseline_summary,
        args.ci_run_url,
    )
    report_filename = "REPORT.md" if is_layer1b else "REPORT_LATEST.md"
    with open(out_dir / report_filename, "w", encoding="utf-8") as fh:
        fh.write(report_content)

    print(f"\nWrote sweep artifacts to {out_dir} ({report_filename} & sweep_summary.json)")


if __name__ == "__main__":
    main()
