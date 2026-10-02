"""Prospective required-isolation replay through the public CLI; no generation.

Repositories must already exist. This harness never fetches, installs, invokes a
provider, substitutes a row, or changes historical GA73 evidence. Use public
repositories only on the hosted confined runtime; local tests use owned fixtures.
An output directory is single-use so unsuccessful attempts cannot be overwritten.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def load_manifest(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    frame = manifest["sampling_frame"]
    if sha256(canonical(frame)) != manifest["sampling_frame_sha256"]:
        raise ValueError("sampling frame hash mismatch")
    rows = manifest["rows"]
    if not rows or sha256(canonical(rows)) != manifest["selected_rows_sha256"]:
        raise ValueError("selected rows hash mismatch")
    seen = set()
    for row in rows:
        ident = row["row_id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", ident) or ident in seen:
            raise ValueError("unsafe or duplicate row_id")
        seen.add(ident)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", row["repo_name"]):
            raise ValueError("unsafe repository directory")
        path = PurePosixPath(row["test"])
        if (path.is_absolute() or ".." in path.parts or not path.parts
                or "\\" in row["test"] or any(ord(c) < 32 for c in row["test"])):
            raise ValueError("unsafe candidate path")
        for field in ("base_sha", "head_sha", "test_source_ref"):
            if not re.fullmatch(r"[0-9a-f]{40}", row[field]):
                raise ValueError("full immutable SHA required")
        # A prospective row must be an exact original row plus declared source.
        original = {k: v for k, v in row.items() if k != "test_source_ref"}
        if original not in frame:
            raise ValueError("selected row not in declared sampling frame")
        expected = row["base_sha"] if row["kind"] == "bug" else row["head_sha"]
        if row["kind"] not in ("bug", "control") or row["test_source_ref"] != expected:
            raise ValueError("undeclared test direction")
    return manifest, raw


def clean_git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0")
    return env



def private_cli_env() -> dict[str, str]:
    """Allow only tool runtime controls, not provider/auth/proxy workflow values."""
    allowed = {
        "PATH", "HOME", "USERPROFILE", "TMPDIR", "TMP", "TEMP", "SYSTEMROOT",
        "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "LC_CTYPE",
        "TZ", "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
        "JITTEST_RUNTIME_IMAGE", "JITTEST_SANDBOX_BACKEND", "JITTEST_FORCE_MINIRUNNER",
        "JITTEST_READINESS", "JITTEST_OUTPUT_GUARD", "PIP_NO_INDEX", "UV_OFFLINE",
    }
    env = {k: v for k, v in os.environ.items() if k in allowed}
    # Only the known tool source path can be used by owned checkout fixture tests.
    if os.environ.get("PYTHONPATH") == str(ROOT / "src"):
        env["PYTHONPATH"] = str(ROOT / "src")
    return env

def command(argv: list[str], directory: Path, label: str, *, env=None,
            timeout: int = 120, cleanup_grace_s: float = 10) -> subprocess.CompletedProcess:
    """Retain exact command/output even on nonzero exits and timeouts."""
    save_json(directory / f"{label}.command.json", argv)
    started = time.monotonic()
    process = None
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, start_new_session=True)
        stdout, stderr = process.communicate(timeout=timeout)
        result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        # Candidate sessions/container clients are NOT the outer CLI group.
        # Give the real CLI's KeyboardInterrupt path a bounded opportunity to
        # clean those resources; forced fallback proves no descendant cleanup.
        cleanup_forced = False
        grace_completed = False
        drain_completed = False
        stdout, stderr = b"", b""
        cleanup_scope = "cli_sigint_grace" if hasattr(os, "killpg") else "direct_child_only"
        if process is not None:
            if hasattr(os, "killpg"):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(process.pid, signal.SIGINT)
                try:
                    stdout, stderr = process.communicate(timeout=min(max(cleanup_grace_s, 0), 10))
                    grace_completed = True
                    drain_completed = True
                except subprocess.TimeoutExpired as grace_error:
                    stdout, stderr = grace_error.stdout or b"", grace_error.stderr or b""
            if not grace_completed:
                cleanup_forced = True
                cleanup_scope = ("forced_outer_process_group_only" if hasattr(os, "killpg")
                                 else "direct_child_only")
                with contextlib.suppress(ProcessLookupError):
                    if hasattr(os, "killpg"):
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                try:
                    stdout, stderr = process.communicate(timeout=5)
                    drain_completed = True
                except subprocess.TimeoutExpired as drain_error:
                    stdout, stderr = drain_error.stdout or b"", drain_error.stderr or b""
                    process.stdout.close()
                    process.stderr.close()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=2)
        (directory / f"{label}.stdout").write_bytes(stdout)
        (directory / f"{label}.stderr").write_bytes(stderr)
        save_json(directory / f"{label}.status.json", {
                  "timeout": isinstance(exc, subprocess.TimeoutExpired),
                  "interrupted": isinstance(exc, KeyboardInterrupt),
                  "cleanup_scope": cleanup_scope,
                  "cleanup_forced": cleanup_forced,
                  "cleanup_grace_completed": grace_completed,
                  "output_drain_completed": drain_completed,
                  "cli_returncode": process.returncode if process is not None else None,
                  "descendant_cleanup": "unknown; outer-process exit alone is not proof",
                  "wall_s": time.monotonic() - started})
        raise
    except OSError as exc:
        save_json(directory / f"{label}.status.json", {"error": repr(exc),
                  "wall_s": time.monotonic() - started})
        raise
    (directory / f"{label}.stdout").write_bytes(result.stdout)
    (directory / f"{label}.stderr").write_bytes(result.stderr)
    save_json(directory / f"{label}.status.json", {"returncode": result.returncode,
              "wall_s": time.monotonic() - started})
    return result


def git(repo: Path, args: list[str], out: Path, label: str) -> bytes:
    result = command(["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo),
                      *args], out, label, env=clean_git_env(), timeout=300)
    if result.returncode:
        raise ValueError(f"git material unavailable: {label} (see retained stderr)")
    return result.stdout


def freeze(row: dict, repo: Path, stage: Path, out: Path) -> dict:
    """No checkout/smudge: retain and stage immutable, regular Git blob bytes."""
    pins = {}
    for field in ("base_sha", "head_sha", "test_source_ref"):
        resolved = git(repo, ["rev-parse", "--verify", row[field] + "^{commit}"],
                       out, "resolve_" + field).decode().strip()
        if resolved != row[field]:
            raise ValueError("revision did not resolve to declared pin")
        pins[field] = resolved
    entry = git(repo, ["ls-tree", "-z", pins["test_source_ref"], "--", row["test"]],
                out, "candidate_tree")
    if not entry.startswith((b"100644 blob ", b"100755 blob ")) or entry.count(b"\0") != 1:
        raise ValueError("candidate is not a single regular Git blob")
    blob = entry.split(b" ", 2)[2].split(b"\t", 1)[0].decode()
    data = git(repo, ["cat-file", "blob", blob], out, "candidate_blob")
    (out / "candidate.py").write_bytes(data)
    pins.update(test_git_blob=blob, test_file_sha256=sha256(data), test_path=row["test"],
                repository=row["repository"], source_origin="raw_git_blob")
    save_json(out / "pins.json", pins)
    stage.mkdir()
    git(stage, ["init", "-q", "--template="], out, "stage_init")
    objects = git(repo, ["rev-parse", "--git-path", "objects"], out, "objects_path").decode().strip()
    object_path = Path(objects)
    if not object_path.is_absolute():
        object_path = repo / object_path
    # Git metadata is a byte contract: forward-slash path and LF on all OSes.
    # Text-mode CRLF/backslashes can make referenced objects unresolvable.
    (stage / ".git/objects/info/alternates").write_bytes(
        object_path.resolve().as_posix().encode("utf-8") + b"\n")
    for side in ("base", "head"):
        git(stage, ["update-ref", f"refs/heads/cohort-{side}", pins[side + "_sha"]],
            out, "stage_ref_" + side)
    git(stage, ["symbolic-ref", "HEAD", "refs/heads/cohort-base"], out, "stage_head")
    git(stage, ["remote", "add", "origin", row["repository"]], out, "stage_origin")
    # Full object history preserves exact source/config/conftest bytes for custody.
    git(stage, ["bundle", "create", str(out / "source.bundle"),
                "refs/heads/cohort-base", "refs/heads/cohort-head"], out, "source_bundle")
    pins["source_bundle_sha256"] = sha256((out / "source.bundle").read_bytes())
    save_json(out / "pins.json", pins)
    candidate = stage / row["test"]
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(data)
    return pins


def run_cohort(manifest_path: Path, repo_root: Path, output: Path, *,
               python: str = sys.executable, row_timeout: int = 900,
               test_timeout: int = 60, reruns: int = 2) -> dict:
    manifest, raw = load_manifest(manifest_path)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Declaration and ALL selected rows exist before material reads/execution.
    (output / "preregistered_manifest.json").write_bytes(raw)
    (output / "harness.py").write_bytes(Path(__file__).read_bytes())
    cli_env = private_cli_env()
    save_json(output / "runtime_request.json", {
        "python": python, "row_timeout": row_timeout, "test_timeout": test_timeout,
        "reruns": reruns, "environment_variable_names": sorted(cli_env),
        "signer_scope": "ephemeral harness key, not independent human endorsement",
    })
    summary = {"cohort": manifest["cohort_name"], "manifest_sha256": sha256(raw),
               "sampling_frame_sha256": manifest["sampling_frame_sha256"],
               "entrypoint": "python -m jittest verify --sandbox-mode required",
               "independent_human_review": "pending_external_custody",
               "human_labels": None, "recall": None, "false_positive_rate": None,
               "provider_cost_usd": None, "rows": []}
    for row in manifest["rows"]:
        summary["rows"].append({"row_id": row["row_id"], "status": "selected_not_attempted"})
    save_json(output / "census.json", summary)
    with tempfile.TemporaryDirectory(prefix="default-cohort-") as tmp:
        scratch = Path(tmp)
        signing_key = scratch / "signing.pem"  # Never export private material.
        expected_signer = None
        signer_error = None
        try:
            # This trusted authority helper runs BEFORE candidate execution, using
            # the requested installed interpreter. Identity is not read from a receipt.
            keygen = command([python, "-c",
                "import sys; from jittest.receipt import get_or_create_signing_key; "
                "from jittest._ed25519 import secret_to_public; "
                "print(secret_to_public(get_or_create_signing_key(sys.argv[1])).hex())",
                str(signing_key)], output, "signing_identity", env=cli_env, timeout=60)
            expected_signer = keygen.stdout.decode().strip()
            if keygen.returncode or not re.fullmatch(r"[0-9a-f]{64}", expected_signer):
                raise ValueError("preexecution signing authority unavailable")
            save_json(output / "expected_signer.json", {
                "verifying_key": expected_signer,
                "source": "trusted installed signing authority, declared before execution",
                "scope": "harness authority only; independent human custody pending",
            })
        except Exception as exc:
            signer_error = exc
            save_json(output / "signing_error.json", {"error_type": type(exc).__name__, "error": str(exc)})
        for row, outcome in zip(manifest["rows"], summary["rows"], strict=True):
            out = output / row["row_id"]
            out.mkdir()
            outcome["status"] = "attempt_started"
            save_json(output / "census.json", summary)
            try:
                repo = (repo_root / row["repo_name"]).resolve()
                stage = scratch / row["row_id"]
                pins = freeze(row, repo, stage, out)
                outcome["pins"] = pins
                if signer_error is not None:
                    raise signer_error
                argv = [python, "-m", "jittest", "verify", "--repo", str(stage),
                        "--base", pins["base_sha"], "--head", pins["head_sha"],
                        "--test", row["test"], "--sandbox-mode", "required",
                        "--timeout", str(test_timeout), "--reruns", str(reruns),
                        "--output", str(out / "receipt.json"), "--signing-key",
                        str(signing_key), "--json"]
                result = command(argv, out, "verify", env=cli_env, timeout=row_timeout)
                outcome.update(cli_exit_code=result.returncode, status="cli_finished")
                receipt = out / "receipt.json"
                if receipt.exists():
                    payload = json.loads(receipt.read_bytes())
                    outcome.update(disposition=payload.get("disposition"),
                                   refusal=payload.get("refusal"), sandbox=payload.get("sandbox"))
                    checks = [python, "-m", "jittest", "verify-receipt", str(receipt),
                              "--expected-base", pins["base_sha"], "--expected-head", pins["head_sha"],
                              "--expected-test-sha256", pins["test_file_sha256"],
                              "--expected-repo", row["repository"], "--expected-signer",
                              expected_signer, "--strict-signer", "--json"]
                    signed = command(checks, out, "receipt_check", env=cli_env, timeout=60)
                    confined = command(checks + ["--require-confined"], out,
                                       "confinement_check", env=cli_env, timeout=60)
                    outcome.update(receipt_check_exit_code=signed.returncode,
                                   confinement_check_exit_code=confined.returncode,
                                   receipt_sha256=sha256(receipt.read_bytes()))
                    # Refusals remain refusals, never counted as confined success.
                    outcome["status"] = ("receipt_valid_confined" if signed.returncode == 0
                                         and confined.returncode == 0 and not payload.get("refusal")
                                         and result.returncode in (0, 1) else "receipt_or_refusal_retained")
                else:
                    outcome["status"] = "cli_no_receipt_retained"
            except KeyboardInterrupt:
                outcome.update(status="interrupted_retained", error_type="KeyboardInterrupt")
                save_json(out / "error.json", outcome)
                save_json(output / "census.json", summary)
                break
            except Exception as exc:
                outcome.update(status="error_retained", error_type=type(exc).__name__, error=str(exc))
                save_json(out / "error.json", outcome)
            save_json(output / "census.json", summary)
    # Hash all exported raw bytes, including every outcome and error, for handoff.
    inventory = {p.relative_to(output).as_posix(): sha256(p.read_bytes())
                 for p in sorted(output.rglob("*")) if p.is_file()}
    save_json(output / "artifact_inventory.json", inventory)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "eval/default_product_cohort.json")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--row-timeout", type=int, default=900)
    parser.add_argument("--test-timeout", type=int, default=60)
    parser.add_argument("--reruns", type=int, default=2)
    args = parser.parse_args()
    result = run_cohort(args.manifest, args.repo_root, args.output, python=args.python,
                        row_timeout=args.row_timeout, test_timeout=args.test_timeout, reruns=args.reruns)
    print(json.dumps({"rows": len(result["rows"]), "output": str(args.output),
                      "statuses": [r["status"] for r in result["rows"]]}))
    return 0 if all(r["status"] == "receipt_valid_confined" for r in result["rows"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
