"""Real isolated B1 smoke, bounded to 3 PySnooper bugs and USD 2 list-price accounting.

This is instrument validation, NOT a catch-rate/FPR/actual billing certificate.
No third-party dependency installer or corpus setup script runs on the host.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.ga73_collection import collection_screen  # noqa: E402
from eval.preflight_model import preflight_model  # noqa: E402
from eval.run_bugsinpy import discover, ensure_repo, evaluate_one, summarize  # noqa: E402
from jittest.sandbox import plan, validate_image_ref  # noqa: E402

DATASET_SHA = "11c5f1eea954a42132cfd06bf257766a7963e0fd"


def acceptance(rows: list[dict]) -> dict:
    telemetry = [t for row in rows for t in row.get("telemetry", [])]
    paired = [t for t in telemetry if t.get("head_outcome") in ("pass", "fail")
              and t.get("base_outcome") in ("pass", "fail")]
    uncollectable = sum(str(t.get("disposition", "")).startswith("head_uncollectable") for t in telemetry)
    collection = collection_screen(telemetry)
    gates = {"pytest_runner": bool(rows) and all(r.get("runner") == "pytest" for r in rows),
             "deps_installed": bool(rows) and all(r.get("deps_status") == "installed" for r in rows),
             "healthy_collection": collection["healthy_collection"],
             "base_head_pair": bool(paired),
             "all_selected_measured": len(rows) == 3 and all(r.get("model_requests", 0) > 0 for r in rows)}
    return {**gates, "passed": all(gates.values()), "paired_candidates": len(paired),
            "head_uncollectable": uncollectable, "telemetry_count": len(telemetry),
            "collection_screen": collection}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bugsinpy", type=Path, required=True)
    ap.add_argument("--workdir", type=Path, default=Path("/tmp/jittest-ga73-smoke"))
    ap.add_argument("--out", type=Path, default=Path("ga73-smoke.json"))
    args = ap.parse_args()
    evidence = {"scope": "B1 instrument smoke, not GA metrics", "dataset_sha": DATASET_SHA,
                "model": "melious/glm-5.3-flash", "risk_threshold": 0.0,
                "list_price_budget_usd": 2.0, "results": [], "acceptance": {"passed": False}}
    try:
        actual = subprocess.check_output(["git", "-C", str(args.bugsinpy), "rev-parse", "HEAD"], text=True).strip()
        if actual != DATASET_SHA:
            raise ValueError("dataset SHA does not match frozen manifest")
        image = os.getenv("JITTEST_RUNTIME_IMAGE", "")
        valid, _ = validate_image_ref(image)
        if not valid or os.getenv("JITTEST_SANDBOX") != "required":
            raise ValueError("required sandbox and digest-pinned operator runtime are mandatory")
        sbx = plan("required", preferred="docker", runtime_image=image)
        # Inventory is obtained from the immutable image, offline, no corpus mounts.
        probe = subprocess.run(["docker", "run", "--rm", "--network", "none", "--read-only",
                                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                                image, "python", "-I", "-c",
                                "import json,pytest,importlib.metadata as m;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"],
                               capture_output=True, text=True, timeout=30, check=True)
        evidence["image_inventory"] = json.loads(probe.stdout)
        evidence["sandbox"] = sbx.as_dict()
        probe_cost = preflight_model(evidence["model"])
        evidence["model_preflight"] = probe_cost
        spent = probe_cost["cost_usd"]
        args.workdir.mkdir(parents=True, exist_ok=True)
        results = []
        for spec in discover(args.bugsinpy, 3, ["PySnooper"]):
            if spent >= 2.0:
                raise ValueError("accounted sweep budget exhausted")
            repo, reason = ensure_repo(spec, args.workdir)
            if repo is None or reason.startswith("commits-missing"):
                raise ValueError("corpus revisions unavailable")
            # PySnooper's pinned requirements are empty; verify rather than executing setup.sh.
            req = args.bugsinpy / "projects" / spec.project / "bugs" / spec.bug_id / "requirements.txt"
            if req.read_text().strip():
                raise ValueError("smoke runtime has not been approved for additional dependencies")
            result = evaluate_one(spec, repo, evidence["model"], 2.0 - spent, risk_threshold=0.0)
            result.runner = "pytest"
            result.deps_status = "installed"
            spent += result.cost_usd
            results.append(result)
            evidence["results"] = [dict(asdict(r), base_sha=s.fixed_commit, head_sha=s.buggy_commit)
                                   for r, s in zip(results, discover(args.bugsinpy, 3, ["PySnooper"]), strict=False)]
            evidence["summary"] = summarize(results)
            evidence["accounted_list_price_usd"] = spent
            evidence["acceptance"] = acceptance(evidence["results"])
            args.out.write_text(json.dumps(evidence, indent=2) + "\n")
        evidence["cost_caveat"] = "Token/list-price accounting only; response guards can overshoot by a request and failed requests may have unobserved billing. Not reconciled wallet spend or USD per real PR."
    except Exception as exc:
        evidence["error_type"] = type(exc).__name__
        # Never copy request/provider bodies, environment values, or engine stderr.
        evidence["error"] = "Smoke refused or failed; inspect typed failure and safe CI step diagnostics."
    args.out.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({k: v for k, v in evidence.items() if k not in ("results", "image_inventory")}, indent=2))
    return 0 if evidence["acceptance"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
