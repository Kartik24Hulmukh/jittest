"""Two-phase sandbox provisioning (handoff P0-1).

Phase 1 (fetch): wheels are built/fetched inside a tightly scoped,
network-enabled container that is destroyed immediately afterwards.
Phase 2 (run): install and execution happen in a fresh network=none
container from the frozen wheelhouse manifest. There is no host
fallback: any engine, digest or policy failure refuses fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .verify import VerifyRefusalError

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN_REQ_RE = re.compile(
    r"(^|\s)(-e\s|--editable\s)|(git|hg|svn|bzr)\+|file://|^\s*\.|^\s*/",
    re.IGNORECASE,
)


class ProvisioningRefusal(VerifyRefusalError):
    """Fail-closed refusal for any provisioning policy violation."""


@dataclass(frozen=True)
class ArtifactPin:
    name: str
    version: str
    sha256: str
    filename: str


@dataclass(frozen=True)
class ProvisionManifest:
    image: str
    image_digest: str
    python: str
    requirements_hash: str
    artifacts: tuple
    network_policy: Literal["fetch", "none"]

    def to_dict(self) -> dict:
        return {
            "image": self.image,
            "image_digest": self.image_digest,
            "python": self.python,
            "requirements_hash": self.requirements_hash,
            "artifacts": [a.__dict__ for a in self.artifacts],
            "network_policy": self.network_policy,
        }


@dataclass(frozen=True)
class EngineAdapter:
    """Injectable container-engine seam (docker/podman in CI, fakes in tests)."""

    name: str
    inspect_digest: Callable[[str], str]
    create: Callable[[dict], str]
    destroy: Callable[[str], None]


def validate_digest(digest: str) -> None:
    if not DIGEST_RE.match(digest or ""):
        raise ProvisioningRefusal("image_digest_required: pinned sha256 digest is mandatory")


def hash_requirements(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_requirements(lines: Sequence[str]) -> None:
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if FORBIDDEN_REQ_RE.search(line):
            raise ProvisioningRefusal(
                "unapproved_dependency: editable/VCS/local-path requirement refused: " + line
            )


def freeze_wheelhouse(wheelhouse: Path) -> tuple:
    wheels = sorted(Path(wheelhouse).glob("*.whl"))
    if not wheels:
        raise ProvisioningRefusal("wheelhouse_empty: phase-1 produced no frozen artifacts")
    pins = []
    for wheel in wheels:
        parts = wheel.name.split("-")
        if len(parts) < 2:
            raise ProvisioningRefusal("wheelhouse_malformed: " + wheel.name)
        pins.append(
            ArtifactPin(
                name=parts[0],
                version=parts[1],
                sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
                filename=wheel.name,
            )
        )
    return tuple(pins)


def build_manifest(
    image: str,
    image_digest: str,
    python_version: str,
    requirements_text: str,
    artifacts: tuple,
    network_policy: Literal["fetch", "none"] = "fetch",
) -> ProvisionManifest:
    validate_digest(image_digest)
    return ProvisionManifest(
        image=image,
        image_digest=image_digest,
        python=python_version,
        requirements_hash=hash_requirements(requirements_text),
        artifacts=tuple(artifacts),
        network_policy=network_policy,
    )


def provision_in_sandbox(repo: Path, plan: Mapping, engine: EngineAdapter, wheelhouse: Path) -> ProvisionManifest:
    """Run the two-phase provisioning contract; never falls back to the host."""
    image = plan["image"]
    expected = plan["image_digest"]
    validate_digest(expected)
    authoritative = engine.inspect_digest(image)
    if authoritative != expected:
        raise ProvisioningRefusal("digest_mismatch: authoritative RepoDigests differ from pin")
    req_path = Path(repo) / plan.get("requirements", "requirements.txt")
    req_text = req_path.read_text(encoding="utf-8")
    check_requirements(req_text.splitlines())
    phase1: str | None = None
    try:
        phase1 = engine.create(
            {"image": image, "digest": expected, "network": "fetch", "phase": "fetch"}
        )
        pins = freeze_wheelhouse(wheelhouse)
    except ProvisioningRefusal:
        raise
    except Exception as exc:  # engine failure: refuse, never retry unconfined
        raise ProvisioningRefusal("engine_failure_phase1: " + str(exc)) from exc
    finally:
        if phase1 is not None:
            engine.destroy(phase1)
    manifest = build_manifest(
        image, expected, plan.get("python", "3.12"), req_text, pins, "none"
    )
    manifest_hash = hashlib.sha256(
        json.dumps(manifest.to_dict(), sort_keys=True).encode("utf-8")
    ).hexdigest()
    phase2: str | None = None
    try:
        again = engine.inspect_digest(image)
        if again != expected:
            raise ProvisioningRefusal("digest_drift_between_phases")
        phase2 = engine.create(
            {
                "image": image,
                "digest": expected,
                "network": "none",
                "read_only_rootfs": True,
                "no_new_privileges": True,
                "cap_drop": "ALL",
                "phase": "run",
                "manifest_hash": manifest_hash,
            }
        )
    except ProvisioningRefusal:
        raise
    except Exception as exc:
        raise ProvisioningRefusal("engine_failure_phase2: " + str(exc)) from exc
    finally:
        if phase2 is not None:
            engine.destroy(phase2)
    return manifest
