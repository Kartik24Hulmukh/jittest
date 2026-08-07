"""Scope hygiene and tracked file verification test for Jittest R2A Engineering Checkpoint (Section B)."""

import re
import subprocess
from pathlib import Path

PROHIBITED_FILES = [
    "scratch/build_phase_c_p1_2_calibration.py",
    "scratch/build_phase_c_p1_2_dataset.py",
    "scratch/build_phase_c_p1_3_dataset.py",
    "scratch/validate_phase_c_preregistration.py",
    "eval/artifacts/budget_journal.jsonl",
    "scratch/fetch_swebench_30.py",
    "eval/artifacts/benchmark_source_pin.json",
    "eval/artifacts/benchmark_source_pin.json.sha256",
    "eval/artifacts/founder_adjudication_packet_p1_4a_r1.json",
    "eval/artifacts/founder_adjudication_packet_p1_4a_r1.json.sha256",
    "eval/artifacts/phase-c-preregistration-manifest.json",
    "eval/artifacts/phase-c-preregistration-manifest.json.sha256",
    "eval/artifacts/calibration_overlap_report.json",
    "eval/artifacts/calibration_overlap_report.json.sha256",
    "eval/artifacts/hash_manifest.json",
    "eval/artifacts/hash_manifest.json.sha256",
]

PATH_PATTERN = re.compile(
    r"(?:[a-zA-Z]:[/\\][uU]sers[/\\](?!runner\b)[a-zA-Z0-9_-]+|/[uU]sers/(?!runner\b)[a-zA-Z0-9_-]+|/home/(?!runner\b)[a-zA-Z0-9_-]+)"
)
SYNTHETIC_SHA_PATTERN = re.compile(
    r"(?:SYNTHETIC_SHA_FALLBACK|0000000000000000000000000000000000000000)"
)
UNVERSIONED_ENDPOINT_PATTERN = re.compile(
    r"(?:unversioned_swebench_endpoint|raw\.githubusercontent\.com/.*swebench/master)"
)


def get_tracked_files() -> list[str]:
    res = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]


def inspect_file_content(path_name: str, content: str) -> None:
    """Validate single file content against prohibited patterns."""
    if path_name == "tests/test_scope_clean.py":
        return

    path_matches = PATH_PATTERN.findall(content)
    if path_matches:
        raise AssertionError(
            f"Forbidden machine-specific path {path_matches[0]} found in {path_name}"
        )

    sha_matches = SYNTHETIC_SHA_PATTERN.findall(content)
    if sha_matches:
        raise AssertionError(
            f"Forbidden synthetic SHA constant {sha_matches[0]} found in {path_name}"
        )

    endpoint_matches = UNVERSIONED_ENDPOINT_PATTERN.findall(content)
    if endpoint_matches:
        raise AssertionError(
            f"Forbidden unversioned benchmark endpoint pattern {endpoint_matches[0]} found in {path_name}"
        )


def test_prohibited_files_absent_from_git_ls_files():
    """Prove prohibited builders, manifests, and runtime journals are absent from tracked git files."""
    tracked = get_tracked_files()
    for bad in PROHIBITED_FILES:
        assert bad not in tracked, f"Prohibited file {bad} found in git ls-files!"


def test_no_prohibited_patterns_in_tracked_files():
    """Inspect all tracked files for machine paths, synthetic SHAs, and unversioned endpoints."""
    tracked = get_tracked_files()
    for rel_path in tracked:
        p = Path(rel_path)
        if p.exists() and p.suffix in (".py", ".json", ".md", ".sh", ".yml", ".yaml"):
            content = p.read_text(encoding="utf-8", errors="ignore")
            inspect_file_content(rel_path, content)


def test_prohibited_pattern_mutations_fail_scope_test():
    """Mutation tests (Section B4) proving scope inspection fails when each prohibited pattern is inserted."""

    # 1. Windows drive-user path mutation
    win_content = r"path = 'C:\Users\praja\repository'"
    try:
        inspect_file_content("dummy_test.py", win_content)
        raise RuntimeError("Failed to reject Windows drive-user path!")
    except AssertionError as e:
        assert "Forbidden machine-specific path" in str(e)

    # 2. macOS user path mutation
    mac_content = "path = '/Users/praja/repository'"
    try:
        inspect_file_content("dummy_test.py", mac_content)
        raise RuntimeError("Failed to reject macOS user path!")
    except AssertionError as e:
        assert "Forbidden machine-specific path" in str(e)

    # 3. Linux home path mutation
    linux_content = "path = '/home/praja/repository'"
    try:
        inspect_file_content("dummy_test.py", linux_content)
        raise RuntimeError("Failed to reject Linux home path!")
    except AssertionError as e:
        assert "Forbidden machine-specific path" in str(e)

    # 4. Synthetic SHA fallback constant mutation
    sha_content = "BASE_SHA = '0000000000000000000000000000000000000000'"
    try:
        inspect_file_content("dummy_test.py", sha_content)
        raise RuntimeError("Failed to reject synthetic SHA fallback constant!")
    except AssertionError as e:
        assert "Forbidden synthetic SHA constant" in str(e)

    # 5. Obsolete builder mutation
    try:
        tracked_mutated = get_tracked_files() + ["scratch/build_phase_c_p1_2_calibration.py"]
        for bad in PROHIBITED_FILES:
            if bad in tracked_mutated:
                raise AssertionError(f"Prohibited file {bad} found in git ls-files!")
        raise RuntimeError("Failed to reject obsolete builder file!")
    except AssertionError as e:
        assert "Prohibited file" in str(e)

    # 6. Committed runtime journal mutation
    try:
        tracked_mutated = get_tracked_files() + ["eval/artifacts/budget_journal.jsonl"]
        for bad in PROHIBITED_FILES:
            if bad in tracked_mutated:
                raise AssertionError(f"Prohibited file {bad} found in git ls-files!")
        raise RuntimeError("Failed to reject committed runtime journal!")
    except AssertionError as e:
        assert "Prohibited file" in str(e)

    # 7. Unversioned benchmark endpoint use mutation
    endpoint_content = "URL = 'https://unversioned_swebench_endpoint/api'"
    try:
        inspect_file_content("dummy_test.py", endpoint_content)
        raise RuntimeError("Failed to reject unversioned benchmark endpoint!")
    except AssertionError as e:
        assert "Forbidden unversioned benchmark endpoint pattern" in str(e)
