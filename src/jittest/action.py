"""GitHub Action Entrypoint & PR Verification Orchestrator.

Extracts changed test files from PR diffs, executes paired base/head verification
with fork-aware sandboxing (required for untrusted fork PRs or unknown context),
upserts a single PR summary comment, and sets the workflow conclusion according
to the declared policy.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .diff import git_env
from .github import fetch_pr_base_head, upsert_pr_comment
from .receipt import get_repo_canonical, verify_receipt
from .sandbox import SandboxPlan, SandboxUnavailable, load_runtime_image, validate_image_ref
from .sandbox import plan as plan_sandbox
from .verify import RefusalReason, VerdictClass, make_refusal_receipt, verify_test

logger = logging.getLogger("jittest.action")

TEST_FILE_PATTERNS = ("test_", "_test.py")

REFUSAL_DISPOSITIONS = {
    "base_uncollectable",
    "head_uncollectable",
    "head_uncollectable_base_passed",
    "ENV_SETUP_FAILED",
    "SANDBOX_UNAVAILABLE",
    "TIMEOUT",
    "file_not_found",
    "base_reproduction_failed",
}


def is_test_file(path_str: str) -> bool:
    p = Path(path_str)
    if p.suffix != ".py":
        return False
    name = p.name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests/" in path_str
        or "tests\\" in path_str
    )


def get_changed_files(repo_path: Path, base_sha: str, head_sha: str) -> list[str]:
    # A failed comparison is not a successful empty diff.
    res = subprocess.run(
        ["git", "-C", str(repo_path), "diff", "--name-only", "-z", f"{base_sha}..{head_sha}"],
        capture_output=True, check=True, env=git_env(),
    )
    # Git's text format C-quotes Unicode/control characters; splitlines can
    # fabricate a zero-test denominator. NUL fields are raw path bytes. Reject
    # undecodable paths rather than replacing bytes or silently losing tests.
    return [name.decode("utf-8", errors="strict") for name in res.stdout.split(b"\0") if name]


def _resolve_commit(repo: Path, ref: str) -> str:
    """Resolve locally available commit objects without executing checkout code."""
    res = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        capture_output=True, text=True, errors="replace", check=True, env=git_env(),
    )
    sha = res.stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise ValueError("comparison revision did not resolve to a commit SHA")
    return sha


def _event_payload() -> dict[str, Any]:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
        return {}
    with open(event_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError("GitHub event must be an object")
    return payload


def get_trust_context() -> str:
    """Return 'fork', 'internal', or 'unknown' based on GitHub Actions event payload."""
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            pr = payload.get("pull_request")
            if pr:
                head_repo = pr.get("head", {}).get("repo", {}).get("full_name")
                base_repo = pr.get("base", {}).get("repo", {}).get("full_name")
                if head_repo and base_repo:
                    return "fork" if head_repo != base_repo else "internal"
        except Exception as exc:
            logger.warning("Could not read GITHUB_EVENT_PATH: %s", exc)
    # Non pull_request trigger events (push, workflow_dispatch, schedule, release)
    # execute code that is already present in the trusted repository checkout;
    # unlike pull_request/pull_request_target, they cannot smuggle in untrusted
    # fork content, so they are treated as internal rather than unknown. This
    # keeps the fork-safety contract intact (any pull_request event is always
    # resolved above by comparing head/base repo) while letting maintainers'
    # own trusted push/dispatch/schedule pipelines honor an explicit non-required
    # sandbox-mode instead of being force-upgraded to 'required'.
    event_name = os.getenv("GITHUB_EVENT_NAME", "").strip().lower()
    if event_name in ("push", "workflow_dispatch", "schedule", "release"):
        return "internal"
    return "unknown"


def _report_summary(body: str, *, pr_number: str | None = None) -> str:
    """Always retain a bounded runner summary, even when commenting is denied."""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(body[:65536] + "\n")
        except OSError as exc:
            logger.warning("Could not write GitHub step summary: %s", exc)
    try:
        return upsert_pr_comment(body, pr_number=pr_number)
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.warning("Could not publish PR comment: %s", exc)
        return "comment unavailable; verification policy unchanged"


def run_action(
    repo_path: Path | str = ".",
    pr_number: int | str | None = None,
    sandbox_override: str | None = None,
    policy: str | None = None,
    output_dir: Path | str = "jittest-evidence",
) -> int:
    repo = Path(repo_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve policy
    policy_str = (
        policy or os.getenv("JITTEST_POLICY") or "advisory"
    ).strip().lower()
    if policy_str not in ("advisory", "strict", "block-on-refusal"):
        logger.warning("Unknown policy '%s'; falling back to 'advisory'", policy_str)
        policy_str = "advisory"

    def comparison_refusal(exc: Exception) -> int:
        logger.error("Comparison refused: %s", exc)
        msg = (
            "<!-- jittest-report -->\n"
            "### 🛡️ `jittest verify` PR Check\n\n"
            "**REFUSED: comparison unavailable**. Base/head resolution or Git diff failed; "
            "the changed-test denominator is unknown. No test execution or catch was declared.\n"
        )
        # Do not publish raw Git diagnostics (which may contain private paths).
        (out_dir / "comparison-refusal.json").write_text(json.dumps({
            "verdict": "inconclusive", "disposition": "refused_comparison_unavailable",
            "proven_catch": False, "denominator_known": False,
        }, indent=2) + "\n", encoding="utf-8")
        _report_summary(msg, pr_number=str(pr_number) if pr_number else None)
        annotation = "warning" if policy_str == "advisory" else "error"
        print(f"::{annotation}::jittest verify: comparison refused; no test-free diff established", file=sys.stderr)
        return 0 if policy_str == "advisory" else 1

    try:
        payload = _event_payload()
        pr = payload.get("pull_request")
        if pr is not None and not isinstance(pr, dict):
            raise ValueError("pull_request event must be an object")
        # Composite inputs export an empty string by default. Treat it as absent.
        pr_number = str(pr_number or os.getenv("JITTEST_PR_NUMBER") or "").strip() or None
        if pr_number is None:
            match = re.fullmatch(r"refs/pull/(\d+)/(?:head|merge)", os.getenv("GITHUB_REF", ""))
            event_number = (pr or {}).get("number") or payload.get("number")
            pr_number = str(event_number) if pr and event_number else (match.group(1) if match else None)
        if pr_number is not None and not re.fullmatch(r"[1-9][0-9]*", pr_number):
            raise ValueError("invalid PR number")

        base_sha = os.getenv("JITTEST_BASE") or os.getenv("GITHUB_BASE_SHA")
        head_sha = os.getenv("JITTEST_HEAD") or os.getenv("GITHUB_HEAD_SHA")
        pr_context = bool(pr_number or pr is not None or os.getenv("GITHUB_EVENT_NAME", "").startswith("pull_request"))
        if pr is not None and (not base_sha or not head_sha):
            for side in ("base", "head"):
                obj = pr.get(side)
                if not isinstance(obj, dict) or not isinstance(obj.get("sha"), str) or not re.fullmatch(r"[0-9a-fA-F]{40}", obj["sha"]):
                    raise ValueError("PR event must contain exact base/head commit SHAs")
            base_sha = base_sha or pr["base"]["sha"]
            head_sha = head_sha or pr["head"]["sha"]
        if pr_context and (not base_sha or not head_sha):
            identity = os.getenv("GITHUB_REPOSITORY", "")
            if not pr_number or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", identity):
                raise ValueError("PR comparison requires exact SHAs or a canonical GitHub repository identity")
            remote_base, remote_head = fetch_pr_base_head(identity, pr_number)
            if not all(isinstance(x, str) and re.fullmatch(r"[0-9a-fA-F]{40}", x) for x in (remote_base, remote_head)):
                raise ValueError("PR resolver did not return exact commit SHAs")
            base_sha = base_sha or remote_base
            head_sha = head_sha or remote_head
        if not pr_context:
            head_sha = head_sha or _resolve_commit(repo, "HEAD")
            if not base_sha:
                for candidate_ref in ("origin/main", "origin/master", "main", "master"):
                    try:
                        base_sha = subprocess.check_output(
                            ["git", "-C", str(repo), "merge-base", candidate_ref, head_sha],
                            text=True, errors="replace", env=git_env(), stderr=subprocess.DEVNULL,
                        ).strip()
                        if base_sha:
                            break
                    except subprocess.CalledProcessError:
                        continue
                base_sha = base_sha or f"{head_sha}~1"
        # Exact local objects must exist. Never replace an unavailable PR head
        # with the checkout's synthetic merge commit or silently fetch code.
        if not base_sha or not head_sha:
            raise ValueError("both comparison revisions are required")
        base_sha = _resolve_commit(repo, base_sha)
        head_sha = _resolve_commit(repo, head_sha)
        all_changed = get_changed_files(repo, base_sha, head_sha)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, RuntimeError) as exc:
        return comparison_refusal(exc)
    changed_tests = [f for f in all_changed if is_test_file(f)]

    if not changed_tests:
        msg = (
            "<!-- jittest-report -->\n"
            "### 🛡️ `jittest verify` PR Check\n\n"
            "**Zero test files modified** in PR diff. Verification skipped.\n"
        )
        status = _report_summary(msg, pr_number=str(pr_number) if pr_number else None)
        print(f"jittest action: {status}")
        return 0

    # Determine Sandbox Mode:
    # Fork safety contract: untrusted fork PRs or unknown context MUST run with 'required'.
    # When sandbox-mode is 'auto', 'default', or unset:
    #   - 'fork' or 'unknown' context -> 'required'
    #   - 'internal' context -> 'auto'
    # Any explicit non-required mode (e.g. 'off') is disallowed for untrusted contexts.
    trust = get_trust_context()
    sbx_override = sandbox_override if sandbox_override is not None else os.getenv("JITTEST_SANDBOX_MODE")
    if sbx_override and sbx_override.strip() and sbx_override.strip().lower() not in ("auto", "default", ""):
        sbx_mode = sbx_override.strip().lower()
        if trust in ("fork", "unknown") and sbx_mode != "required":
            logger.warning(
                "Untrusted %s context cannot downgrade sandbox-mode '%s'; enforcing 'required'",
                trust,
                sbx_mode,
            )
            sbx_mode = "required"
    else:
        sbx_mode = "required" if trust in ("fork", "unknown") else "auto"

    runtime_image, runtime_notes = load_runtime_image(repo, base_sha)
    for note in runtime_notes:
        logger.warning("%s", note)
    if runtime_image and not validate_image_ref(runtime_image)[0]:
        # This preliminary availability check never executes a candidate.
        # verify_test independently refuses the invalid BASE pin per test,
        # preserving refusal reporting and the selected Action policy.
        # Generic Action refusals currently do not emit a signed artifact.
        runtime_image = ""
    try:
        sbx_plan = plan_sandbox(mode=sbx_mode, probe=False,
                               runtime_image=runtime_image)
    except SandboxUnavailable:
        sbx_plan = SandboxPlan(backend="none", mode=sbx_mode)

    if trust in ("fork", "unknown") and getattr(sbx_plan, "backend", "none") == "none":
        print(
            f"::error::jittest verify: sandbox backend unavailable for untrusted {trust} PR context; refused execution",
            file=sys.stderr,
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        for test_rel in changed_tests:
            test_path = repo / test_rel
            posix_rel = Path(test_rel).as_posix()
            path_digest = hashlib.sha256(posix_rel.encode("utf-8")).hexdigest()[:12]
            out_artifact = out_dir / f"evidence-{test_path.stem}-{path_digest}.json"
            ref_obj = RefusalReason(
                code="sandbox_unavailable",
                message=f"isolation required for untrusted {trust} context but no backend is available",
                phase="plan",
            )
            with contextlib.suppress(Exception):
                make_refusal_receipt(
                    repo_path=repo,
                    base_ref=base_sha,
                    head_ref=head_sha,
                    test_file_path=test_path,
                    refusal=ref_obj,
                    sbx_plan=sbx_plan,
                    output_path=out_artifact,
                )
            results.append({
                "file": test_rel,
                "verdict": VerdictClass.INCONCLUSIVE,
                "disposition": "refused_sandbox_unavailable",
                "proven_catch": False,
                "wall_clock_s": 0.0,
                "artifact": str(out_artifact),
            })

        table_lines = [
            "<!-- jittest-report -->",
            "### 🛡️ `jittest verify` PR Verdict Summary",
            "",
            "**REFUSED: Isolation Required but Unavailable**",
            "",
            f"Untrusted `{trust}` PR execution requires an isolation backend (docker, podman, or bubblewrap). None was available on this runner.",
            "",
            "| Changed Test File | Base SHA | Head SHA | Verdict | Disposition | Duration | Artifact |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for r in results:
            table_lines.append(
                f"| `{r['file']}` | `{base_sha[:8]}` | `{head_sha[:8]}` | `{r['verdict']}` | `{r['disposition']}` | {r['wall_clock_s']:.1f}s | `{Path(r['artifact']).name}` |"
            )
        table_lines.append("")
        table_lines.append(
            f"**Total Changed Tests Evaluated**: {len(results)} | **Proven Catches**: 0 | **Policy**: `{policy_str}`"
        )
        comment_body = "\n".join(table_lines)
        _report_summary(comment_body, pr_number=str(pr_number) if pr_number else None)

        if policy_str in ("strict", "block-on-refusal"):
            return 1
        return 0  # advisory

    def _verify_one(test_rel: str) -> dict[str, Any]:
        test_path = repo / test_rel
        if not test_path.exists():
            return {
                "file": test_rel,
                "verdict": VerdictClass.INCONCLUSIVE,
                "disposition": "file_not_found",
                "proven_catch": False,
                "wall_clock_s": 0.0,
                "artifact": "",
            }

        posix_rel = Path(test_rel).as_posix()
        path_digest = hashlib.sha256(posix_rel.encode("utf-8")).hexdigest()[:12]
        out_artifact = out_dir / f"evidence-{test_path.stem}-{path_digest}.json"
        print(f"\n[jittest action] Verifying {test_rel} (base={base_sha[:8]}, head={head_sha[:8]}, sandbox={sbx_mode})...")

        try:
            evidence, exit_code = verify_test(
                repo_path=repo,
                base_ref=base_sha,
                head_ref=head_sha,
                test_file_path=test_path,
                output_path=out_artifact,
                sandbox_mode=sbx_mode,
            )
            # The producer's boolean is not a consumer proof. Check the signed
            # receipt independently and bind it to this exact pair and candidate.
            accepted = verify_receipt(
                evidence, expected_base=base_sha, expected_head=head_sha,
                expected_test_sha256=hashlib.sha256(test_path.read_bytes()).hexdigest(),
                expected_repo=get_repo_canonical(repo),
            )
            if evidence.get("schema_version") != "2.1" or not accepted.valid:
                logger.error("Producer receipt rejected by independent consumer verification for %s", test_rel)
                return {
                    "file": test_rel, "verdict": VerdictClass.INCONCLUSIVE,
                    "disposition": "refused_invalid_receipt", "proven_catch": False,
                    "wall_clock_s": evidence.get("wall_clock_s", 0.0),
                    "artifact": str(out_artifact),
                }
            return {
                "file": test_rel,
                "verdict": evidence["verdict"],
                "disposition": evidence["disposition"],
                "proven_catch": evidence.get("proven_catch", False),
                "wall_clock_s": evidence.get("wall_clock_s", 0.0),
                "artifact": str(out_artifact),
            }
        except SandboxUnavailable as exc:
            logger.error("Sandbox isolation required but unavailable: %s", exc)
            return {
                "file": test_rel,
                "verdict": VerdictClass.INCONCLUSIVE,
                "disposition": "SANDBOX_UNAVAILABLE",
                "proven_catch": False,
                "wall_clock_s": 0.0,
                "artifact": "",
            }
        except Exception as exc:
            logger.error("Failed verification for %s: %s", test_rel, exc)
            return {
                "file": test_rel,
                "verdict": VerdictClass.INCONCLUSIVE,
                "disposition": "ENV_SETUP_FAILED",
                "proven_catch": False,
                "wall_clock_s": 0.0,
                "artifact": "",
            }

    results = [_verify_one(t) for t in changed_tests]

    refusal_tests: list[dict[str, Any]] = [
        r for r in results if r["disposition"] in REFUSAL_DISPOSITIONS or r["verdict"] == VerdictClass.INCONCLUSIVE
    ]
    pc_count = sum(1 for r in results if r["proven_catch"])

    # Build Summary Comment Table
    table_lines = [
        "<!-- jittest-report -->",
        "### 🛡️ `jittest verify` PR Verdict Summary",
        "",
        "| Changed Test File | Base SHA | Head SHA | Verdict | Disposition | Duration | Artifact |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in results:
        v_str = f"**`{r['verdict']}`**" if r["proven_catch"] else f"`{r['verdict']}`"
        art_str = f"`{Path(r['artifact']).name}`" if r.get("artifact") else "-"
        table_lines.append(
            f"| `{r['file']}` | `{base_sha[:8]}` | `{head_sha[:8]}` | {v_str} | `{r['disposition']}` | {r['wall_clock_s']:.1f}s | {art_str} |"
        )

    table_lines.append("")
    table_lines.append(
        f"**Total Changed Tests Evaluated**: {len(results)} | **Proven Catches**: {pc_count} | **Policy**: `{policy_str}`"
    )

    if refusal_tests:
        table_lines.append("")
        table_lines.append(
            f"⚠️ **Execution / Setup Note**: {len(refusal_tests)} test(s) experienced setup, sandbox, or collection refusals. These refusals were not counted as positive regression catches."
        )

    comment_body = "\n".join(table_lines)
    comment_status = _report_summary(comment_body, pr_number=str(pr_number) if pr_number else None)
    print(f"\njittest action PR Comment: {comment_status}")

    # Honest policy exit codes:
    # 1. 'advisory': exit 0, emit visible warning annotations on refusals.
    # 2. 'strict': exit 0 only if pc_count >= 1 or zero tests changed; exit 1 otherwise.
    # 3. 'block-on-refusal': exit 1 if any refusal occurred; exit 0 otherwise.
    if policy_str == "strict":
        if not refusal_tests and (len(results) == 0 or pc_count >= 1):
            return 0
        print("::error::jittest verify: strict policy failed — refusals or zero proven catches found", file=sys.stderr)
        return 1

    if policy_str == "block-on-refusal":
        if refusal_tests:
            print(
                f"::error::jittest verify: block-on-refusal failed — {len(refusal_tests)} test(s) encountered refusals",
                file=sys.stderr,
            )
            return 1
        return 0

    # policy == 'advisory'
    if refusal_tests:
        print(
            f"::warning::jittest verify: {len(refusal_tests)} test(s) encountered refusals/errors",
            file=sys.stderr,
        )
    return 0


def main():
    repo = os.getenv("JITTEST_REPO_PATH", ".")
    pr = os.getenv("JITTEST_PR_NUMBER")
    sbx = os.getenv("JITTEST_SANDBOX_MODE")
    policy = os.getenv("JITTEST_POLICY")
    out_dir = os.getenv("JITTEST_OUTPUT_DIR") or "jittest-evidence"
    code = run_action(
        repo_path=repo,
        pr_number=pr,
        sandbox_override=sbx,
        policy=policy,
        output_dir=out_dir,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()

