"""Docs must claim exactly the published artifact recorded in docs/release-artifacts.json (#199)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_release_mapping", ROOT / "scripts" / "check_release_mapping.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_release_mapping_agrees_with_docs() -> None:
    mod = _load_checker()
    rows = mod.collect(mod.load_mapping())
    bad = [r for r in rows if not r[3]]
    assert not bad, f"release mapping drift: {bad}"
    assert len(rows) >= 8


def test_release_mapping_is_canonical_json_with_explicit_gaps() -> None:
    raw = (ROOT / "docs" / "release-artifacts.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert raw == json.dumps(data, indent=2, sort_keys=True) + "\n", (
        "mapping must be canonical (indent=2, sorted keys)"
    )
    pub = data["published"]
    kinds = {a["kind"] for a in pub["artifacts"]}
    assert kinds == {"bdist_wheel", "sdist"}
    assert pub["source_to_wheel_check"]["mismatched"] == 0
    assert pub["source_to_wheel_check"]["missing"] == 0
    assert pub["not_included"], "must state what the published wheel does not contain"
    assert "0.4.0" in data["yanked"]


def test_drift_is_detected(tmp_path, monkeypatch) -> None:
    mod = _load_checker()
    mapping = mod.load_mapping()
    mapping["published"]["version"] = "9.9.9"
    rows = mod.collect(mapping)
    assert any(not r[3] for r in rows), "a wrong published version must be flagged"
