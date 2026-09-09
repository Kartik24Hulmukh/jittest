#!/usr/bin/env python3
"""Option C proof: run a dependency-bearing candidate inside a pinned trusted image.

Closes defect D9 only when it actually RUNS on a real daemon. Without a daemon it
prints a NOT_RUN record and exits 0 only if --allow-not-run is given, so CI
cannot silently turn absence of proof into proof.

Usage:
  python scripts/prove_option_c.py --image jittest-pilot-requests:local [--allow-not-run]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jittest.sandbox import detect_backend, plan, wrap  # noqa: E402

CANDIDATE = """import requests, flask
from flask import Flask


def test_flask_and_requests_import_and_run():
    app = Flask(\"pilot\")

    @app.get(\"/ping\")
    def ping():
        return {\"ok\": True}

    client = app.test_client()
    assert client.get(\"/ping\").get_json() == {\"ok\": True}
    assert requests.__version__


def test_network_is_denied():
    import socket
    try:
        socket.create_connection((\"1.1.1.1\", 53), timeout=3)
    except OSError:
        return
    raise AssertionError(\"network reachable inside sandbox\")
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=os.environ.get("JITTEST_SANDBOX_IMAGE", "jittest-pilot-requests:local"))
    ap.add_argument("--allow-not-run", action="store_true")
    ap.add_argument("--out", default="option-c-proof.json")
    args = ap.parse_args()

    backend = detect_backend(os.environ.get("JITTEST_SANDBOX_BACKEND", ""))
    record = {"proof": "option_c", "defect": "D9", "image": args.image, "backend": backend, "status": "NOT_RUN"}
    if backend not in ("docker", "podman"):
        record["reason"] = "no container daemon usable; dependency-bearing candidate was not executed"
        Path(args.out).write_text(json.dumps(record, indent=2))
        print(json.dumps(record, indent=2))
        return 0 if args.allow_not_run else 1

    sbx = plan("required", preferred=backend, image=args.image)
    work = Path(tempfile.mkdtemp(prefix="jt-optc-"))
    (work / "test_pilot_candidate.py").write_text(CANDIDATE, encoding="utf-8")
    argv, env = wrap([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(work / "test_pilot_candidate.py")], work, {}, sbx)
    t0 = time.monotonic()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    record.update({
        "status": "RUN", "rc": proc.returncode, "passed": proc.returncode == 0,
        "wall_clock_s": round(time.monotonic() - t0, 2), "stdout_tail": proc.stdout[-1500:], "stderr_tail": proc.stderr[-800:],
    })
    Path(args.out).write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
