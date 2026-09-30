"""Fail closed unless PyPI hosts the exact built wheel and sdist.

Read-only check, no upload, credential access, version bump or tag mutation.
Registry lag deliberately fails this gate; rerun it after availability rather
than advance a floating tag to an unavailable or different distributable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def check(dist: Path) -> list[str]:
    manifest = json.loads((dist / "candidate-manifest.json").read_text())
    version = manifest["version"]
    request = urllib.request.Request(
        f"https://pypi.org/pypi/jittest/{version}/json",
        headers={"User-Agent": "jittest-release-byte-verifier"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        catalogue = json.load(response)
    rows = {row["filename"]: row for row in catalogue["urls"]}
    checked = []
    for filename, expected in manifest["artifacts"].items():
        local = dist / filename
        if hashlib.sha256(local.read_bytes()).hexdigest() != expected:
            raise ValueError(f"local artifact changed: {filename}")
        row = rows.get(filename)
        if not row or row["digests"]["sha256"] != expected or row.get("yanked"):
            raise ValueError(f"registry metadata mismatch or yanked: {filename}")
        url = row["url"]
        if not url.startswith("https://files.pythonhosted.org/"):
            raise ValueError("unexpected registry artifact host")
        with urllib.request.urlopen(url, timeout=30) as response:
            digest = hashlib.sha256()
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"registry bytes differ: {filename}")
        checked.append(filename)
    if len(checked) != 2:
        raise ValueError("exact wheel and sdist required")
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    try:
        print(json.dumps({"verified": check(args.dist)}))
    except Exception as exc:
        print(json.dumps({"verified": False, "error_type": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())