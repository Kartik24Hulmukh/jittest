"""Manifest validator for Phase C R2C control candidates (Zero Spend & Non-Fabrication Enforcement)."""

import re
import subprocess
from pathlib import Path

REPEATED_NIBBLE_SHA_PATTERN = re.compile(
    r"^(?:(.)\1{39}|([0-9a-f]{2})\2{19}|([0-9a-f]{4})\3{9}|1212121212121212121212121212121212121212)$",
    re.IGNORECASE,
)

PLACEHOLDER_REVISIONS = {
    "1212121212121212121212121212121212121212",
    "1111111111111111111111111111111111111111",
    "1010101010101010101010101010101010101010",
    "0" * 40,
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


def validate_r2c_manifest(
    manifest: dict,
    repo_dir_map: dict[str, Path] | None = None,
    allow_adjudicated: bool = False,
) -> list[str]:
    """Validate control candidates manifest object against all integrity constraints.

    Returns a list of error strings. An empty list means the manifest is VALID.
    """
    errors = []

    # 1. Schema check
    if manifest.get("schema_version") != "1.0":
        errors.append("Invalid schema_version")

    candidates = manifest.get("candidates", [])
    if len(candidates) < 80:
        errors.append(f"Insufficient control candidates count: {len(candidates)} < 80")

    cand_id_set = set()
    diff_hash_set = set()
    pr_num_repo_set = set()

    is_adjudicated_manifest = allow_adjudicated or manifest.get("founder_adjudication_status") == "adjudicated"

    for idx, cand in enumerate(candidates):
        cid = cand.get("candidate_id", f"candidate_{idx}")

        # Check candidate ID uniqueness
        if cid in cand_id_set:
            errors.append(f"Duplicate candidate_id {cid!r}")
        cand_id_set.add(cid)

        # Check human adjudication fields
        if not is_adjudicated_manifest:
            for field in ("human_decision", "human_reason", "human_reviewer", "human_adjudicated_at"):
                if cand.get(field) is not None:
                    errors.append(
                        f"Candidate {cid} field {field} is prefilled ({cand.get(field)!r}); MUST BE NULL by design for unadjudicated manifest"
                    )
        else:
            dec = cand.get("human_decision")
            if dec is not None:
                if dec not in ("eligible", "ineligible", "indeterminate"):
                    errors.append(f"Candidate {cid} invalid human_decision {dec!r}")
                if not cand.get("human_reason"):
                    errors.append(f"Candidate {cid} has decision {dec!r} but missing human_reason")
                if not cand.get("human_reviewer"):
                    errors.append(f"Candidate {cid} has decision {dec!r} but missing human_reviewer")
                if not cand.get("human_adjudicated_at"):
                    errors.append(f"Candidate {cid} has decision {dec!r} but missing human_adjudicated_at")

        # Check SHAs for synthetic patterns
        for sha_field in ("real_base_sha", "real_head_sha", "merge_commit_sha"):
            sha_val = cand.get(sha_field, "")
            if is_repeated_nibble_sha(sha_val) or sha_val in PLACEHOLDER_REVISIONS:
                errors.append(f"Candidate {cid} field {sha_field} has synthetic/placeholder SHA {sha_val!r}")

        # Check base != head
        if cand.get("real_base_sha") == cand.get("real_head_sha"):
            errors.append(f"Candidate {cid} has identical base and head SHA")

        # Check diff sha256 uniqueness
        d_sha = cand.get("diff_sha256")
        if d_sha:
            if d_sha in diff_hash_set:
                errors.append(f"Candidate {cid} has duplicate diff_sha256 {d_sha!r}")
            diff_hash_set.add(d_sha)

        # Check repo + PR number uniqueness
        repo = cand.get("repository", "")
        pr_num = cand.get("pr_number")
        if repo and pr_num is not None:
            repo_pr_key = (repo, pr_num)
            if repo_pr_key in pr_num_repo_set:
                errors.append(f"Candidate {cid} has duplicate repo+PR {repo_pr_key}")
            pr_num_repo_set.add(repo_pr_key)

        # Check observation window
        obs_days = cand.get("observation_window_days", 0)
        if obs_days < 90:
            errors.append(f"Candidate {cid} observation_window_days ({obs_days}) < 90 days required threshold")

        # Check git commit existence if repo_dir_map provided
        if repo_dir_map and repo in repo_dir_map:
            repo_path = repo_dir_map[repo]
            if repo_path.exists():
                for sha_field in ("real_base_sha", "real_head_sha"):
                    sha_val = cand.get(sha_field, "")
                    res = subprocess.run(
                        ["git", "cat-file", "-e", sha_val],
                        cwd=repo_path,
                        capture_output=True,
                    )
                    if res.returncode != 0:
                        errors.append(f"Candidate {cid} {sha_field} {sha_val!r} does not exist in real clone {repo_path}")

    return errors
