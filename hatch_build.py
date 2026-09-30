"""Archive source identity for installed verifiers without a Git checkout."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        archived = root / "src/jittest/_build_provenance.json"
        if (root / ".git").exists():
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                          text=True).strip()
            diff = subprocess.check_output(["git", "diff", "HEAD"], cwd=root)
            provenance = {"source_sha": sha, "working_diff_sha256": hashlib.sha256(diff).hexdigest()}
        elif archived.exists():
            provenance = json.loads(archived.read_text())
        else:
            raise ValueError("build requires Git source identity or archived build provenance")
        if not re.fullmatch(r"[0-9a-f]{40}", provenance.get("source_sha", "")):
            raise ValueError("invalid archived source SHA")
        if not re.fullmatch(r"[0-9a-f]{64}", provenance.get("working_diff_sha256", "")):
            raise ValueError("invalid archived diff SHA256")
        # Keep generated files outside source; build must not dirty the checkout.
        self._temp = tempfile.TemporaryDirectory(prefix="jittest-build-")
        path = Path(self._temp.name) / "_build_provenance.json"
        path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
        destination = ("src/jittest/_build_provenance.json" if self.target_name == "sdist"
                       else "jittest/_build_provenance.json")
        build_data.setdefault("force_include", {})[str(path)] = destination

    def finalize(self, version, build_data, artifact_path):
        self._temp.cleanup()