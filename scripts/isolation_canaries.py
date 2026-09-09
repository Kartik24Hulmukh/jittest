#!/usr/bin/env python3
"""Isolation canaries: prove the sandbox boundary is real, not theatre.

Run in CI with ``JITTEST_SANDBOX_BACKEND=<backend>``. The script FAILS (exit 1)
when no backend is usable; it never skips, because a skipped canary is exactly
the "green but unconfined" state this project refuses to report.

Canaries (each executed *inside* the planned sandbox):
  1. network   - opening a TCP socket to 1.1.1.1:53 must fail.
  2. escape    - writing outside the workspace (the host HOME) must fail.
  3. control   - a trivial script inside the workspace must succeed, so that
                 canaries 1-2 failed because of the boundary, not a broken image.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jittest.sandbox import detect_backend, plan, wrap  # noqa: E402

NET = "import socket,sys\ntry:\n socket.create_connection(('1.1.1.1',53),timeout=4)\nexcept Exception as e:\n print('denied',type(e).__name__); sys.exit(3)\nprint('REACHED'); sys.exit(0)\n"
ESC = "import os,sys\np=os.path.join(os.path.expanduser('~'),'jittest-escape-canary')\nfor c in (p,'/etc/jittest-escape','/usr/jittest-escape'):\n try:\n  open(c,'w').write('x'); print('ESCAPED',c); sys.exit(0)\n except Exception as e:\n  print('blocked',c,type(e).__name__)\nsys.exit(3)\n"
CTL = "print('control-ok')\n"


def run_canary(name: str, body: str, work: Path, sbx, want_rc_nonzero: bool) -> dict:
    script = work / f"{name}.py"
    script.write_text(body, encoding="utf-8")
    argv, env = wrap([sys.executable, str(script)], work, {"PYTHONDONTWRITEBYTECODE": "1"}, sbx)
    t0 = time.monotonic()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300, env={**os.environ, **env} if env else None)
    out = (proc.stdout + proc.stderr).strip()
    passed = (proc.returncode != 0) if want_rc_nonzero else (proc.returncode == 0)
    if name == "network" and "REACHED" in out:
        passed = False
    if name == "escape" and "ESCAPED" in out:
        passed = False
    return {"canary": name, "passed": passed, "rc": proc.returncode, "seconds": round(time.monotonic() - t0, 2), "output": out[-400:]}


def main() -> int:
    preferred = os.environ.get("JITTEST_SANDBOX_BACKEND", "").strip().lower()
    backend = detect_backend(preferred)
    if backend == "none":
        print(json.dumps({"backend": "none", "passed": False, "reason": f"no usable sandbox backend (preferred={preferred or 'any'}); canaries refuse to skip"}))
        return 1
    sbx = plan("required", preferred=backend)
    work = Path(tempfile.mkdtemp(prefix="jt-canary-"))
    results = [
        run_canary("control", CTL, work, sbx, want_rc_nonzero=False),
        run_canary("network", NET, work, sbx, want_rc_nonzero=True),
        run_canary("escape", ESC, work, sbx, want_rc_nonzero=True),
    ]
    ok = all(r["passed"] for r in results)
    print(json.dumps({"backend": sbx.backend, "image": sbx.image if sbx.backend in ("docker", "podman") else None, "passed": ok, "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
