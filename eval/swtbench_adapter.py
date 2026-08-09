"""SWT-Bench adapter scaffolding and rank calibration dry-run (Mission M4).

Maps SWT-Bench instance specifications to (repo, base, head) commit pairs and
runs rank calibration over the Lite instance dataset without executing inference.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add repo root and src to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from eval.rank_calibration import calibrate  # noqa: E402
from eval.unmeasured import unmeasured_reason  # noqa: E402


def map_swtbench_instance(instance: dict) -> tuple[str, str, str]:
    """Map an SWT-Bench instance dict to (repo, base, head).

    base = base_commit / gold-patch parent
    head = environment / resolving commit
    """
    repo = instance.get("repo", "")
    base = instance.get("base_commit", "")
    head = instance.get("environment_setup_commit", "") or instance.get("commit", "")
    return repo, base, head


def rank_calibration_sweep(
    instances: list[dict], repo_base_dir: Path | None = None, threshold: float = 0.35
) -> dict:
    """Run rank calibration over a set of SWT-Bench instances.

    Returns summary stats on how many instances clear the risk threshold.
    """
    total = len(instances)
    cleared_risk_gate = 0
    results = []

    for inst in instances:
        instance_id = inst.get("instance_id", "unknown")
        repo_name, base, head = map_swtbench_instance(inst)

        local_repo = (repo_base_dir / repo_name.split("/")[-1]) if repo_base_dir else None
        if local_repo and local_repo.exists() and base and head:
            try:
                cal = calibrate(local_repo, base, head, threshold=threshold)
                above = cal.get("targets_at_or_above_threshold", 0)
                if above > 0:
                    cleared_risk_gate += 1
                results.append({
                    "instance_id": instance_id,
                    "repo": repo_name,
                    "base": base[:8],
                    "head": head[:8],
                    "targets_extracted": cal.get("targets_extracted", 0),
                    "targets_at_or_above_threshold": above,
                    "max_score": cal.get("max", 0.0),
                    "verdict": cal.get("verdict", "unknown"),
                })
            except Exception as exc:
                results.append({
                    "instance_id": instance_id,
                    "repo": repo_name,
                    "error": str(exc),
                })
        else:
            # Synthetic / dry-run placeholder when local clone is absent
            results.append({
                "instance_id": instance_id,
                "repo": repo_name,
                "base": base[:8] if base else "",
                "head": head[:8] if head else "",
                "status": "instance_mapped",
            })

    return {
        "instances_total": total,
        "instances_evaluated": len(results),
        "instances_cleared_risk_gate": cleared_risk_gate,
        "clearance_rate": round(cleared_risk_gate / total, 4) if total > 0 else 0.0,
        "threshold": threshold,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SWT-Bench adapter scaffolding and rank calibration"
    )
    parser.add_argument("--instances-file", type=Path, help="JSON file containing SWT-Bench instances")
    parser.add_argument("--repo-dir", type=Path, help="Base directory containing local repo clones")
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--out", type=Path, default=Path("swtbench-calibration.json"))
    args = parser.parse_args(argv)

    instances = []
    if args.instances_file and args.instances_file.exists():
        try:
            instances = json.loads(args.instances_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Error reading instances file: {exc}", file=sys.stderr)
            return 1
    else:
        # Sample Lite instance definitions for scaffolding demonstration
        instances = [
            {
                "instance_id": "pytest-dev__pytest-5221",
                "repo": "pytest-dev/pytest",
                "base_commit": "d98eb69a1234567890abcdef1234567890abcdef",
                "environment_setup_commit": "eca5fd1d1234567890abcdef1234567890abcdef",
            },
            {
                "instance_id": "pallets__flask-4992",
                "repo": "pallets/flask",
                "base_commit": "27be93381234567890abcdef1234567890abcdef",
                "environment_setup_commit": "c17f37931234567890abcdef1234567890abcdef",
            },
        ]

    summary = rank_calibration_sweep(instances, repo_base_dir=args.repo_dir, threshold=args.threshold)
    print(f"SWT-Bench Scaffolding Summary: {summary['instances_total']} instances mapped")
    print(f"Instances clearing risk gate (threshold={args.threshold}): {summary['instances_cleared_risk_gate']}")

    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
