"""Manifest validator for Phase C R2B real-bug packet (Zero Spend & Non-Fabrication Enforcement)."""

import re
import subprocess
from pathlib import Path

# Pattern detecting synthetic / placeholder SHAs (repeated nibbles like 1111..., 1212..., 0a0a..., 0000...)
REPEATED_NIBBLE_SHA_PATTERN = re.compile(
    r"^(?:(.)\1{39}|([0-9a-f]{2})\2{19}|([0-9a-f]{4})\3{9}|0{40}|1212121212121212121212121212121212121212)$",
    re.IGNORECASE,
)

PLACEHOLDER_REVISIONS = {
    "1212121212121212121212121212121212121212",
    "1111111111111111111111111111111111111111",
    "1010101010101010101010101010101010101010",
    "0000000000000000000000000000000000000000",
}


def is_repeated_nibble_sha(sha: str) -> bool:
    """Return True if SHA matches synthetic repeated-nibble or low-entropy pattern."""
    if not sha or len(sha) != 40:
        return False
    if REPEATED_NIBBLE_SHA_PATTERN.match(sha):
        return True
    if len(set(sha.lower())) <= 2:
        return True
    return False


def validate_manifest(manifest: dict, repo_dir_map: dict[str, Path] | None = None) -> list[str]:
    """Validate manifest object against all non-fabrication integrity constraints.

    Returns a list of error strings. An empty list means the manifest is VALID.
    """
    errors = []

    # 1. Check schema properties
    if manifest.get("schema_version") != "1.0":
        errors.append("Invalid schema_version")

    # 2. Check source_snapshots for placeholders
    for snap in manifest.get("source_snapshots", []):
        rev = snap.get("revision", "")
        if rev in PLACEHOLDER_REVISIONS or is_repeated_nibble_sha(rev):
            errors.append(f"Source snapshot {snap.get('name')} contains placeholder revision {rev!r}")
        byte_count = snap.get("byte_count", 0)
        if byte_count > 0 and byte_count % (1024 * 1024) == 0:
            errors.append(f"Source snapshot {snap.get('name')} contains fabricated exact MiB byte count {byte_count}")

    rows = manifest.get("rows", [])
    if len(rows) < 20:
        errors.append(f"Insufficient eligible row count: {len(rows)} < 20")

    started_at_set = set()
    stdout_sha_set = set()

    for idx, row in enumerate(rows):
        row_id = row.get("row_id", f"row_{idx}")

        # Check SHAs in row
        for field_name in ("real_buggy_sha", "real_fixed_sha", "derived_base_sha", "derived_head_sha"):
            sha_val = row.get(field_name, "")
            if is_repeated_nibble_sha(sha_val):
                errors.append(f"Row {row_id} field {field_name} has synthetic SHA {sha_val!r}")

        # Check timestamp uniqueness
        trigger_buggy = row.get("trigger_on_buggy", {})
        trigger_fixed = row.get("trigger_on_fixed", {})

        for tr_name, tr in [("trigger_on_buggy", trigger_buggy), ("trigger_on_fixed", trigger_fixed)]:
            st = tr.get("started_at")
            if st:
                if st in started_at_set:
                    errors.append(f"Row {row_id} {tr_name} has duplicate started_at timestamp {st!r}")
                started_at_set.add(st)

            so_sha = tr.get("stdout_sha256")
            if so_sha:
                if so_sha in stdout_sha_set:
                    errors.append(f"Row {row_id} {tr_name} has duplicate stdout_sha256 {so_sha!r}")
                stdout_sha_set.add(so_sha)

        # Check real git commit existence if repo_dir_map provided
        repo_url = row.get("repository", "")
        if repo_dir_map and repo_url in repo_dir_map:
            repo_path = repo_dir_map[repo_url]
            if repo_path.exists():
                for sha_field in ("real_buggy_sha", "real_fixed_sha"):
                    sha_val = row.get(sha_field, "")
                    res = subprocess.run(
                        ["git", "cat-file", "-e", sha_val],
                        cwd=repo_path,
                        capture_output=True,
                    )
                    if res.returncode != 0:
                        errors.append(f"Row {row_id} {sha_field} {sha_val!r} does not exist in real clone {repo_path}")

    return errors
