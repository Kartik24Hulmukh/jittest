"""Scope hygiene and tracked file verification test for Jittest R2A Engineering Checkpoint."""

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


def get_tracked_files():
    res = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [f.strip() for f in res.stdout.strip().split("\n") if f.strip()]


def test_prohibited_files_absent_from_git_ls_files():
    tracked = get_tracked_files()
    for bad in PROHIBITED_FILES:
        assert bad not in tracked, f"Prohibited file {bad} found in git ls-files!"


def test_no_machine_specific_paths_in_tracked_files():
    tracked = get_tracked_files()
    # Matches C:\Users\<name>, C:/Users/<name>, /Users/<name>, /home/<name> (excluding runner mock)
    pattern = re.compile(
        r"(?:[a-zA-Z]:[/\\][uU]sers[/\\](?!runner\b)[a-zA-Z0-9_-]+|/[uU]sers/(?!runner\b)[a-zA-Z0-9_-]+|/home/(?!runner\b)[a-zA-Z0-9_-]+)"
    )

    for rel_path in tracked:
        if rel_path == "tests/test_scope_clean.py":
            continue
        p = Path(rel_path)
        if p.exists() and p.suffix in (".py", ".json", ".md"):
            content = p.read_text(encoding="utf-8", errors="ignore")
            matches = pattern.findall(content)
            assert not matches, (
                f"Forbidden machine-specific path {matches[0]} found in tracked file {rel_path}"
            )


def test_prohibited_pattern_mutations_fail_scope_test():
    """Mutation tests proving test_no_machine_specific_paths_in_tracked_files fails when prohibited patterns are inserted."""
    pattern = re.compile(
        r"(?:[a-zA-Z]:[/\\][uU]sers[/\\](?!runner\b)[a-zA-Z0-9_-]+|/[uU]sers/(?!runner\b)[a-zA-Z0-9_-]+|/home/(?!runner\b)[a-zA-Z0-9_-]+)"
    )

    win_path = "C:\\Users\\praja\\repo"
    mac_path = "/Users/praja/repo"
    linux_path = "/home/praja/repo"

    assert pattern.search(win_path) is not None, "Failed to match Windows drive-user path mutation!"
    assert pattern.search(mac_path) is not None, "Failed to match macOS user path mutation!"
    assert pattern.search(linux_path) is not None, "Failed to match Linux home path mutation!"
