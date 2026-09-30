"""Archive source identity for installed verifiers without a Git checkout."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        spec = importlib.util.spec_from_file_location("jittest_build_identity", root / "build_identity.py")
        if spec is None or spec.loader is None:
            raise ValueError("build identity helper unavailable")
        identity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(identity)
        if version == "editable":
            # PEP 660 points at live source, not copied immutable runtime bytes.
            # Never let an archived resource override live Git identity later.
            if not (root / ".git").exists() or (root / "src/jittest/_build_provenance.json").exists():
                raise ValueError("editable builds require own Git source without archived provenance")
            provenance = identity.git_provenance(root)
        else:
            provenance = identity.build_provenance(root)
        self._identity = identity
        self._provenance = provenance
        self._temp = None
        if version == "editable":
            return
        # Keep generated files outside source; build must not dirty the checkout.
        self._temp = tempfile.TemporaryDirectory(prefix="jittest-build-")
        path = Path(self._temp.name) / "_build_provenance.json"
        path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
        destination = ("src/jittest/_build_provenance.json" if self.target_name == "sdist"
                       else "jittest/_build_provenance.json")
        build_data.setdefault("force_include", {})[str(path)] = destination

    def finalize(self, version, build_data, artifact_path):
        try:
            if self._identity.source_manifest(Path(self.root)) != self._provenance["build_inputs"]:
                raise ValueError("build inputs changed during build")
            if version == "editable":
                self._identity.validate_editable_artifact(Path(artifact_path), Path(self.root))
            else:
                self._identity.validate_artifact(Path(artifact_path), self.target_name, self._provenance)
        finally:
            if self._temp is not None:
                self._temp.cleanup()