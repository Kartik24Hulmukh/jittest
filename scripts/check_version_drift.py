#!/usr/bin/env python3
"""Assert the version string agrees in every place it is declared.

Checked: pyproject.toml, src/jittest/__init__.py, CHANGELOG.md heading,
CITATION.cff (if it declares a version). Exit 1 with a table on any drift.
This is what turned 0.3.4/0.3.5 skew from a recurring surprise into a CI failure.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def collect() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    with (ROOT / "pyproject.toml").open("rb") as fh:
        found["pyproject.toml"] = tomllib.load(fh)["project"]["version"]
    init = (ROOT / "src/jittest/__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    found["src/jittest/__init__.py"] = m.group(1) if m else None
    chlog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[?(\d+\.\d+\.\d+)\]?", chlog, re.M)
    found["CHANGELOG.md (first numbered heading)"] = m.group(1) if m else None
    cff = ROOT / "CITATION.cff"
    if cff.exists():
        m = re.search(r"^version:\s*[\"']?(\d+\.\d+\.\d+)", cff.read_text(encoding="utf-8"), re.M)
        if m:
            found["CITATION.cff"] = m.group(1)
    return found


def main() -> int:
    found = collect()
    versions = {v for v in found.values() if v}
    for k, v in found.items():
        print(f"  {k:45s} {v}")
    if len(versions) != 1 or None in found.values():
        print(f"FAIL: version drift, saw {sorted(versions)}")
        return 1
    print(f"ok: version {versions.pop()} agrees in {len(found)} places")
    return 0


if __name__ == "__main__":
    sys.exit(main())
