"""Authoritative registry RepoDigests verification (handoff P0-2).

The only trustworthy answer to "is this the image I pinned?" is the engine's
RepoDigests array after a pull by digest. A local ``.Id`` can be spoofed by
retagging; tags mutate. Every failure mode fails closed.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence

REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]*@sha256:[0-9a-f]{64}$")

Inspector = Callable[[str, str, int], "tuple[list[str], str, str]"]


def validate_image_ref(ref: str) -> tuple[bool, str]:
    if not ref or not REF_RE.match(ref):
        return False, "unpinned_image_ref: image reference must be name@sha256:<64 hex>"
    return True, ""


def inspect_image_repo_digests(
    backend: str, image: str, timeout: int = 30
) -> tuple[list[str], str, str]:
    """Return (RepoDigests, Id, error). Never raises: errors fail closed."""
    if backend not in ("docker", "podman"):
        return [], "", "unsupported_backend: " + str(backend)
    try:
        proc = subprocess.run(
            [backend, "image", "inspect", image],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], "", f"inspect_failed: {exc}"
    if proc.returncode != 0:
        return [], "", "inspect_failed: " + proc.stderr.strip()[:200]
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return [], "", "inspect_unparsable"
    entry = data[0] if isinstance(data, list) and data else {}
    if not isinstance(entry, dict):
        return [], "", "inspect_unparsable"
    digests = entry.get("RepoDigests") or []
    if not isinstance(digests, list):
        return [], str(entry.get("Id") or ""), "inspect_unparsable"
    return [d for d in digests if isinstance(d, str)], str(entry.get("Id") or ""), ""


def verify_image_digest(
    backend: str,
    image_ref: str,
    mirror_policy: dict[str, Sequence[str]] | None = None,
    inspector: Inspector | None = None,
    timeout: int = 30,
) -> tuple[bool, str, str]:
    """Return (ok, reason, digest). The local image Id is never treated as proof."""
    ok, reason = validate_image_ref(image_ref)
    if not ok:
        return False, reason, ""
    name, _, digest = image_ref.partition("@")
    probe = inspector or inspect_image_repo_digests
    digests, _image_id, err = probe(backend, image_ref, timeout)
    if err:
        return False, err, ""
    if not digests:
        return False, "missing_repo_digests: engine returned no authoritative RepoDigests", ""
    hits = [e for e in digests if e.partition("@")[2] == digest]
    if not hits:
        return False, "repo_digest_mismatch: authoritative RepoDigests lack the pinned digest", ""
    if mirror_policy is not None:
        allowed = set(mirror_policy.get(name, ()))
        if allowed:
            hosts = {h.partition("@")[0].split("/")[0] for h in hits}
            if not hosts & allowed:
                return False, "unauthorized_mirror: no RepoDigests entry from an authorized registry", ""
    return True, "", digest
