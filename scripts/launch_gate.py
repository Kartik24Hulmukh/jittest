#!/usr/bin/env python3
"""Single-command launch go/no-go gate for the September 16-17, 2026 window.

Aggregates every launch-critical check into one deterministic JSON report so
that "is main launchable right now?" has exactly one answer and one digest:

  * static gates   - ruff, version drift, release-to-artifact mapping
  * product gates  - offline Ed25519 verification of every committed receipt
                     (the product must be able to recompute its own evidence)
  * evidence gates - committed 100k-op soak evidence must still satisfy the
                     leak-gate contract it claims to satisfy
  * test gates     - focused launch suites (or the full suite with --full)
  * honesty gate   - ga_ready is *derived* from the open GA blockers, never
                     hand-set; a green run with open blockers is LAUNCH_OK
                     but never GA.

Run from checkout: PYTHONPATH=src python scripts/launch_gate.py --json out.json
Exit code 0 = all gates pass, 1 = at least one gate failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from jittest.integrity import canonical_json  # noqa: E402

LAUNCH_WINDOW = "2026-09-16/2026-09-17"

# Open GA blockers. ga_ready is derived from this list being empty, so the only
# way to flip it is to close the issues and delete the rows in the same PR.
GA_BLOCKERS = [
    {"issue": 73, "title": "real catch-rate / FPR / USD-per-PR evaluation"},
]

# Independent runtime failures block *launch*, not merely GA. Remove entries
# only in the change carrying verified cross-platform resolution evidence.
RUNTIME_BLOCKERS = [
    {"issue": 225, "title": "Windows descendant containment and bounded capture disk usage"},
]


def gate_runtime_blockers() -> dict:
    return {"ok": not RUNTIME_BLOCKERS, "blockers": list(RUNTIME_BLOCKERS)}


FOCUSED_SUITES = [
    "tests/test_memory_soak.py",
    "tests/test_stress_100x.py",
    "tests/test_chaos_resilience.py",
    "tests/test_prod_observability.py",
    "tests/test_phase_boundaries.py",
    "tests/test_cli_refusal_edges.py",
    "tests/test_receipt_json_schema.py",
    "tests/test_version_drift.py",
    "tests/test_cli_explain.py",
    "tests/test_anti_fabrication_lint.py",
    "tests/test_launch_gate.py",
]

RECEIPT_DIRS = ["docs/evidence/quadrants", "docs/evidence/pr"]

# Receipts the product is *expected* to refuse (path -> refusal code). Empty since
# 2026-09-16: the legacy 2.0 showcase receipt (base_execution NOTRUN yet claiming
# non_discriminating) was regenerated against real Flask base/head as a schema
# 2.1 receipt (issue #206). Keep the mechanism so a future documented refusal is
# pinned as fail-closed proof rather than hidden.
KNOWN_REFUSED_RECEIPTS: dict[str, str] = {}
SOAK_EVIDENCE = "docs/evidence/memory-soak-20260916.json"


def _run(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


def gate_ruff() -> dict:
    code, out = _run([sys.executable, "-m", "ruff", "check", "src", "tests", "scripts", "eval"])
    if code == 1 and "No module named ruff" in out:
        # Infrastructure failure, not a source regression: fail loudly and
        # distinctly so a missing tool can never masquerade as a lint FAIL.
        return {"ok": False, "tool_missing": "ruff",
                "detail": ["ruff is not installed; this is TOOL_MISSING, not a lint failure"]}
    return {"ok": code == 0, "detail": out.strip().splitlines()[-1:] if out else []}


def gate_script(name: str) -> dict:
    code, out = _run([sys.executable, f"scripts/{name}"])
    return {"ok": code == 0, "detail": out.strip().splitlines()[-1:]}


def classify_receipt(rel: str, code: int, payload: dict) -> dict:
    """Pure classification of one verify-receipt result against expectations."""
    payload = payload if isinstance(payload, dict) else {}
    sig = payload.get("signature_valid") is True
    valid = payload.get("valid") is True and code == 0
    expected_refusal = KNOWN_REFUSED_RECEIPTS.get(rel)
    if expected_refusal is None:
        ok = sig and valid and payload.get("semantic_valid") is True
        expectation = "valid"
    else:
        # Fail-closed proof: signature intact, explicit semantic refusal (exit 5).
        ok = (sig and payload.get("valid") is False
              and payload.get("semantic_valid") is False and code == 5)
        expectation = f"refused:{expected_refusal}"
    return {
        "artifact": rel,
        "expectation": expectation,
        "signature_valid": sig,
        "valid": valid,
        "ok": ok,
    }


def gate_receipts(root: Path = ROOT) -> dict:
    # The product must be able to recompute every receipt it publishes, offline,
    # and must refuse the ones it is documented to refuse.
    results = []
    for rel in RECEIPT_DIRS:
        for path in sorted((root / rel).glob("*.json")):
            code, out = _run(
                [sys.executable, "-m", "jittest", "verify-receipt", str(path), "--json"]
            )
            try:
                payload = json.loads(out[out.index("{") :])
            except (ValueError, json.JSONDecodeError):
                payload = {}
            results.append(classify_receipt(str(path.relative_to(root)), code, payload))
    ok = bool(results) and all(r["ok"] for r in results)
    return {"ok": ok, "receipts": results}


def check_soak_evidence(doc: dict) -> dict:
    """Pure check of committed soak evidence against the leak-gate contract."""
    problems = []
    if not isinstance(doc, dict):
        return {"ok": False, "problems": ["soak evidence must be an object"]}
    limit = doc.get("leak_slope_limit_kib_per_1k_ops")
    slope = doc.get("leak_slope_kib_per_1k_ops")

    # Evidence cannot choose its own acceptance threshold. bool is an int in
    # Python, and JSON's permissive decoder accepts NaN/Infinity: reject both.
    def finite_number(value):
        return type(value) is int or (type(value) is float and math.isfinite(value))

    if not finite_number(limit) or limit != 1.0:
        problems.append("leak slope limit must be the launch policy value 1.0")
    if not finite_number(slope):
        problems.append("slope missing or non-finite")
    elif slope > 1.0:
        problems.append(f"leak slope {slope} exceeds limit 1.0")
    if doc.get("leak_suspected") is not False:
        problems.append("leak_suspected is not false")
    if type(doc.get("errors")) is not int or doc["errors"] != 0:
        problems.append(f"errors={doc.get('errors')!r}")
    if (
        type(doc.get("distinct_digests")) is not int
        or doc["distinct_digests"] != 1
        or doc.get("deterministic") is not True
    ):
        problems.append("soak run is not deterministic")
    if type(doc.get("total_ops")) is not int or doc["total_ops"] < 100_000:
        problems.append("fewer than 100k ops or invalid operation count")
    if type(doc.get("seed")) is not int or doc["seed"] != 20260916:
        problems.append("unexpected seed")
    return {"ok": not problems, "problems": problems}


def gate_soak_evidence(root: Path = ROOT) -> dict:
    path = root / SOAK_EVIDENCE
    if not path.exists():
        return {"ok": False, "problems": [f"{SOAK_EVIDENCE} missing"]}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "problems": [f"invalid JSON: {exc}"]}
    result = check_soak_evidence(doc)
    result["artifact"] = SOAK_EVIDENCE
    return result


def gate_tests(full: bool) -> dict:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if not full:
        missing = [p for p in FOCUSED_SUITES if not (ROOT / p).is_file()]
        if missing:
            return {"ok": False, "mode": "focused", "missing_suites": missing}
        cmd += FOCUSED_SUITES
    code, out = _run(cmd, timeout=3600)
    if "No module named pytest" in out:
        # Infrastructure failure, not a test regression: an absent test runner
        # is TOOL_MISSING, never an ordinary FAIL/NO_GO.
        return {"ok": False, "mode": "full" if full else "focused",
                "tool_missing": "pytest",
                "summary": ["pytest is not installed; this is TOOL_MISSING, not a test failure"]}
    summary = [ln for ln in out.strip().splitlines() if "passed" in ln or "failed" in ln]
    return {"ok": code == 0, "mode": "full" if full else "focused", "summary": summary[-1:]}


def derive_ga_ready(blockers: list[dict]) -> bool:
    return not blockers


def build_report(gates: dict, blockers: list[dict]) -> dict:
    all_ok = bool(gates) and all(g.get("ok") is True for g in gates.values())
    missing_tools = sorted(
        {g["tool_missing"] for g in gates.values() if g.get("tool_missing")}
    )
    ga_ready = derive_ga_ready(blockers)
    if missing_tools:
        # Distinct from NO_GO: the source tree may be fine, the toolchain is not.
        decision = "NO_GO_TOOL_MISSING"
    elif not all_ok:
        decision = "NO_GO"
    elif ga_ready:
        decision = "GO_GA"
    else:
        decision = "GO_LAUNCH_NOT_GA"
    stable = {
        "kind": "launch_gate",
        "launch_window": LAUNCH_WINDOW,
        "gates": gates,
        "ga_blockers": blockers,
        "ga_ready": ga_ready,
        "decision": decision,
        "tool_missing": missing_tools,
    }
    stable["digest"] = hashlib.sha256(canonical_json(stable).encode("utf-8")).hexdigest()
    return stable


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", action="store_true", help="run the full pytest suite")
    ap.add_argument("--skip-tests", action="store_true", help="skip the pytest gate")
    ap.add_argument("--json", type=Path, help="write the report here")
    args = ap.parse_args(argv)

    started = time.time()
    gates = {
        "ruff": gate_ruff(),
        "version_drift": gate_script("check_version_drift.py"),
        "release_mapping": gate_script("check_release_mapping.py"),
        "workflow_cli_contract": gate_script("check_workflow_cli_contract.py"),
        "receipts_recompute": gate_receipts(),
        "soak_evidence": gate_soak_evidence(),
        "runtime_blockers": gate_runtime_blockers(),
    }
    if not args.skip_tests:
        gates["tests"] = gate_tests(args.full)
    else:
        gates["tests"] = {"ok": False, "mode": "skipped",
                          "detail": ["tests are required for launch approval"]}
    report = build_report(gates, GA_BLOCKERS)
    report["volatile"] = {"elapsed_s": round(time.time() - started, 1), "python": sys.version}

    for name, gate in gates.items():
        if gate.get("tool_missing"):
            print(f"  [TOOL_MISSING:{gate['tool_missing']}] {name}")
        else:
            print(f"  [{'ok  ' if gate['ok'] else 'FAIL'}] {name}")
    print(f"decision: {report['decision']}  ga_ready: {report['ga_ready']}")
    print(f"digest:   {report['digest']}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report["decision"] == "NO_GO_TOOL_MISSING":
        return 2
    return 0 if report["decision"] != "NO_GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
