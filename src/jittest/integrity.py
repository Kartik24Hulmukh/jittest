"""Receipt integrity records (handoff P0-5).

Canonical, versioned integrity record binding source, image,
dependencies, policy, command, exit code and output hashes together,
plus the refusal reason and explicit incomplete / non-reproducible
states. Nothing here ever claims MORE than the measured evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "integrity-1.0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class IntegrityRecord:
    schema_version: str
    source_sha256: str
    image_digest: str
    dependencies_sha256: str
    policy_sha256: str
    command_sha256: str
    exit_code: int
    output_sha256: str
    refusal_reason: str = ""
    incomplete: bool = False
    non_reproducible: bool = False
    reproducibility_note: str = ""
    extras: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_sha256": self.source_sha256,
            "image_digest": self.image_digest,
            "dependencies_sha256": self.dependencies_sha256,
            "policy_sha256": self.policy_sha256,
            "command_sha256": self.command_sha256,
            "exit_code": self.exit_code,
            "output_sha256": self.output_sha256,
            "refusal_reason": self.refusal_reason,
            "incomplete": self.incomplete,
            "non_reproducible": self.non_reproducible,
            "reproducibility_note": self.reproducibility_note,
        }

    def digest(self) -> str:
        return sha256_bytes(canonical_json(self.to_dict()).encode("utf-8"))


def build_integrity_record(
    source_bytes: bytes,
    image_digest: str,
    dependencies_text: str,
    policy_text: str,
    command: Sequence[str],
    exit_code: int,
    output_bytes: bytes,
    refusal_reason: str = "",
    incomplete: bool = False,
    non_reproducible: bool = False,
    reproducibility_note: str = "",
) -> IntegrityRecord:
    if incomplete and not reproducibility_note:
        reproducibility_note = "run terminated before all phases completed"
    if non_reproducible and not reproducibility_note:
        reproducibility_note = "repeated identical runs did not agree"
    return IntegrityRecord(
        schema_version=SCHEMA_VERSION,
        source_sha256=sha256_bytes(source_bytes),
        image_digest=image_digest,
        dependencies_sha256=sha256_bytes(dependencies_text.encode("utf-8")),
        policy_sha256=sha256_bytes(policy_text.encode("utf-8")),
        command_sha256=sha256_bytes(canonical_json(list(command)).encode("utf-8")),
        exit_code=exit_code,
        output_sha256=sha256_bytes(output_bytes),
        refusal_reason=refusal_reason,
        incomplete=incomplete,
        non_reproducible=non_reproducible,
        reproducibility_note=reproducibility_note,
    )


def compare_runs(first: IntegrityRecord, second: IntegrityRecord) -> dict[str, Any]:
    """Reproducibility comparison for repeated identical runs."""
    same = first.digest() == second.digest()
    return {
        "reproducible": same,
        "first_digest": first.digest(),
        "second_digest": second.digest(),
        "differences": sorted(
            key for key in first.to_dict() if first.to_dict()[key] != second.to_dict()[key]
        ),
    }
