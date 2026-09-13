#!/usr/bin/env python3
"""Real-daemon public verify proof. No daemon, skip or failed assertion is success."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jittest import _ed25519  # noqa: E402
from jittest.receipt import get_or_create_signing_key, verify_receipt  # noqa: E402
from jittest.verify import VerifyRefusalError, verify_test  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="phase-boundaries-proof.json")
    args = ap.parse_args()
    record: dict = {"proof": "public-verify-phase-boundaries", "status": "NOT_RUN"}
    try:
        os.environ["JITTEST_SANDBOX_BACKEND"] = "docker"
        os.environ["JITTEST_OUTPUT_GUARD"] = "required"
        with tempfile.TemporaryDirectory(prefix="jt-phase-proof-") as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            git(repo, "init")
            git(repo, "config", "user.name", "Jittest proof")
            git(repo, "config", "user.email", "proof@jittest.invalid")
            (repo / "app.py").write_text("def add(a, b):\n    return a + b\n")
            test = repo / "test_app.py"
            test.write_text("from app import add\ndef test_add():\n    assert add(2, 3) == 5\n")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            base = git(repo, "rev-parse", "HEAD")
            (repo / "app.py").write_text("def add(a, b):\n    return a - b\n")
            git(repo, "commit", "-am", "regression")
            head = git(repo, "rev-parse", "HEAD")
            key = root / "key"
            signer = _ed25519.secret_to_public(get_or_create_signing_key(key)).hex()
            receipt, rc = verify_test(repo, base, head, test, sandbox_mode="required",
                                      signing_key_path=key, timeout_s=30)
            assert rc == 0 and receipt["verdict"] == "proven_catch", receipt["verdict"]
            assert receipt["sandbox"]["backend"] == "docker"
            phases = receipt["verification_phases"]
            assert [p["phase"] for p in phases] == ["base", "head", "head_rerun_2"]
            assert all(p["output_guard"]["ok"] for p in phases)
            verified = verify_receipt(receipt, expected_signer=signer, strict_signer=True,
                                      require_confined=True, expected_base=base, expected_head=head)
            assert verified.valid, verified.reason
            record.update(status="RUN", verdict=receipt["verdict"], backend="docker",
                          phases=phases, confined_signature_valid=True)
            phases[-1]["output_guard"]["ok"] = False
            assert not verify_receipt(receipt, expected_signer=signer).valid
            record["phase_tamper_rejected"] = True
            # A violation present only at BASE must refuse on the public path.
            git(repo, "checkout", base)
            (repo / "escape").symlink_to("/etc/passwd")
            git(repo, "add", "escape")
            git(repo, "commit", "-m", "base-only unsafe node")
            unsafe_base = git(repo, "rev-parse", "HEAD")
            try:
                verify_test(repo, unsafe_base, head, test, sandbox_mode="required",
                            signing_key_path=key, timeout_s=30)
            except VerifyRefusalError as exc:
                assert exc.reason.code == "output_boundary_violation", exc.reason.code
                record["base_only_violation_refused"] = True
            else:
                raise AssertionError("base-only output violation failed open")
            record["passed"] = True
    except Exception as exc:
        record.update(passed=False, error=f"{type(exc).__name__}: {exc}")
    Path(args.out).write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))
    return 0 if record.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
