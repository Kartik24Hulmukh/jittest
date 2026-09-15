#!/usr/bin/env python3
"""Assert user-facing docs claim exactly the published release recorded in
docs/release-artifacts.json (issue #199).

Offline. Checks: mapping is well-formed; README badge, README release notice,
QUICKSTART notice and every ``uses: Kartik24Hulmukh/jittest@vX.Y.Z`` pin agree
with the mapping; every SHA-256 is 64 hex chars; the unreleased-main note is
present so nobody mistakes main for the published wheel. Exit 1 with a table on
any drift. Docs may not claim a version that has no release record.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPPING = ROOT / "docs" / "release-artifacts.json"
DOCS = [ROOT / "README.md", ROOT / "docs" / "QUICKSTART.md"]
SEMVER = r"\d+\.\d+\.\d+"


def load_mapping() -> dict:
    return json.loads(MAPPING.read_text(encoding="utf-8"))


def collect(mapping: dict) -> list[tuple[str, str, str, bool]]:
    pub = mapping["published"]
    want = pub["version"]
    rows: list[tuple[str, str, str, bool]] = []
    rows.append(("mapping.tag", f"v{want}", pub["tag"], pub["tag"] == f"v{want}"))
    rows.append(
        (
            "mapping.source_sha",
            "40 hex",
            pub["source_sha"],
            bool(re.fullmatch(r"[0-9a-f]{40}", pub["source_sha"])),
        )
    )
    for art in pub["artifacts"]:
        ok = bool(re.fullmatch(r"[0-9a-f]{64}", art["sha256"])) and want in art["filename"]
        rows.append((f"mapping.artifact[{art['kind']}]", want, art["filename"], ok))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"PyPI-v(" + SEMVER + r")-blue", readme)
    rows.append(
        ("README badge", want, m.group(1) if m else "missing", bool(m and m.group(1) == want))
    )
    m = re.search(r"published package on PyPI is `(" + SEMVER + r")`", readme)
    rows.append(
        (
            "README release notice",
            want,
            m.group(1) if m else "missing",
            bool(m and m.group(1) == want),
        )
    )
    rows.append(
        (
            "README links RELEASE-ARTIFACTS",
            "yes",
            "yes" if "RELEASE-ARTIFACTS.md" in readme else "no",
            "RELEASE-ARTIFACTS.md" in readme,
        )
    )
    quick = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    m = re.search(r"immutable Action tag are `(" + SEMVER + r")`", quick)
    rows.append(
        ("QUICKSTART notice", want, m.group(1) if m else "missing", bool(m and m.group(1) == want))
    )
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        for pin in re.findall(r"Kartik24Hulmukh/jittest@v(" + SEMVER + r")", text):
            rows.append((f"{doc.relative_to(ROOT)} Action pin", want, pin, pin == want))
    rows.append(
        (
            "mapping.unreleased_main.note",
            "present",
            "present" if mapping.get("unreleased_main", {}).get("note") else "missing",
            bool(mapping.get("unreleased_main", {}).get("note")),
        )
    )
    return rows


def main() -> int:
    rows = collect(load_mapping())
    bad = 0
    for where, want, got, ok in rows:
        print(f"  {'ok ' if ok else 'BAD'} {where:40s} want={want!s:10s} got={got}")
        bad += 0 if ok else 1
    if bad:
        print(f"FAIL: {bad} release-mapping drift(s)")
        return 1
    print(f"ok: {len(rows)} release-mapping checks agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
