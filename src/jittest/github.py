"""Minimal GitHub client over urllib. No PyGithub, no gh CLI required.

One job: upsert a single PR comment so the bot never spams a thread. If no
token is present we say so and exit cleanly - a tool that hard fails when it
cannot comment is a tool that breaks other people's CI.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request

from .report import MARKER

__all__ = ["upsert_pr_comment", "detect_pr_number", "detect_repo", "pr_context"]

API = os.getenv("GITHUB_API_URL", "https://api.github.com")


def _token() -> str | None:
    return os.getenv("JITTEST_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")


def _request(method: str, path: str, payload: dict | None = None):
    token = _token()
    if not token:
        raise RuntimeError("no GITHUB_TOKEN in environment")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={
            "authorization": f"Bearer {token}",
            "accept": "application/vnd.github+json",
            "content-type": "application/json",
            "user-agent": "jittest",
            "x-github-api-version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


def detect_repo() -> str | None:
    return os.getenv("GITHUB_REPOSITORY")


def detect_pr_number() -> str | None:
    if os.getenv("JITTEST_PR_NUMBER"):
        return os.environ["JITTEST_PR_NUMBER"]
    parts = os.getenv("GITHUB_REF", "").split("/")   # refs/pull/123/merge
    if len(parts) > 2 and parts[1] == "pull":
        return parts[2]
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, encoding="utf-8") as fh:
                number = json.load(fh).get("pull_request", {}).get("number")
            return str(number) if number else None
        except (OSError, ValueError):
            return None
    return None


def pr_context() -> tuple[str, str]:
    """Title and body of the current PR, from the Actions event payload."""
    title = os.getenv("JITTEST_PR_TITLE", "")
    body = os.getenv("JITTEST_PR_BODY", "")
    if title or body:
        return title, body
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, encoding="utf-8") as fh:
                pr = json.load(fh).get("pull_request", {})
            return pr.get("title") or "", pr.get("body") or ""
        except (OSError, ValueError):
            pass
    return "", ""


def _gh_cli_fallback(body: str) -> bool:
    number = detect_pr_number()
    if not number:
        return False
    for extra in (["--edit-last"], []):
        res = subprocess.run(["gh", "pr", "comment", number, *extra, "--body", body],
                            capture_output=True, text=True, errors="replace")
        if res.returncode == 0:
            return True
    return False


def upsert_pr_comment(body: str, repo: str | None = None,
                      pr_number: str | None = None) -> str:
    """Create or edit the single jittest comment. Returns a status string."""
    if not body.strip():
        return "skipped: nothing proven, so nothing said"

    repo = repo or detect_repo()
    pr_number = pr_number or detect_pr_number()
    if not repo or not pr_number:
        return "skipped: not running on a pull request"

    if not _token():
        if _gh_cli_fallback(body):
            return "posted via gh CLI"
        return "skipped: no GITHUB_TOKEN and gh CLI unavailable"

    try:
        comments = _request(
            "GET", f"/repos/{repo}/issues/{pr_number}/comments?per_page=100")
        existing = None
        if isinstance(comments, list):
            for c in comments:
                if MARKER in (c.get("body") or ""):
                    existing = c["id"]
                    break
        if existing:
            _request("PATCH", f"/repos/{repo}/issues/comments/{existing}", {"body": body})
            return f"updated comment {existing}"
        _request("POST", f"/repos/{repo}/issues/{pr_number}/comments", {"body": body})
        return "posted new comment"
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        if _gh_cli_fallback(body):
            return "posted via gh CLI after API error"
        return f"failed to comment: {exc}"
