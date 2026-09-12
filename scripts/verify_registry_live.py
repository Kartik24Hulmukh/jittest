#!/usr/bin/env python3
"""Live P0-2 proof: resolve a platform pin from the registry, pull by digest,
then verify the engine's authoritative RepoDigests on a REAL daemon.

This is the gate the 2026-09-12 handoff could not execute locally (no container
engine in the workspace). It runs on CI ubuntu-latest where a daemon exists.
Fail-closed everywhere: no daemon, no network, unparsable manifest, empty
RepoDigests or a digest mismatch all exit non-zero with a JSON record.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jittest import registry  # noqa: E402

HUB_TOKEN = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
HUB_MANIFEST = "https://registry-1.docker.io/v2/{repo}/manifests/{tag}"
ACCEPT = ", ".join([
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
])


def resolve_platform_digest(repo: str, tag: str, arch: str, timeout: int = 30) -> tuple[str, str]:
    """Return (pinned digest, reason). Never raises; failures fail closed."""
    try:
        with urllib.request.urlopen(HUB_TOKEN.format(repo=repo), timeout=timeout) as fh:
            token = json.load(fh)["token"]
        req = urllib.request.Request(
            HUB_MANIFEST.format(repo=repo, tag=tag),
            headers={"Accept": ACCEPT, "Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            index = json.load(fh)
    except Exception as exc:  # network/registry outage: fail closed
        return "", f"registry_unreachable: {exc}"
    manifests = index.get("manifests") or []
    if not manifests:
        return "", "registry_unparsable: manifest index has no platform entries"
    for entry in manifests:
        plat = entry.get("platform") or {}
        if plat.get("architecture") == arch and plat.get("os") == "linux" and not plat.get("variant"):
            return entry.get("digest") or "", ""
    return "", f"registry_unparsable: no linux/{arch} entry in manifest index"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="library/python")
    ap.add_argument("--tag", default="3.12-slim")
    ap.add_argument("--backend", default="docker")
    ap.add_argument("--out", default="registry-live-proof.json")
    args = ap.parse_args()

    record = {"proof": "p0-2-registry-live", "repo": args.repo, "tag": args.tag,
              "backend": args.backend, "status": "NOT_RUN"}

    def finish(code: int) -> int:
        Path(args.out).write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2))
        return code

    arch = "arm64" if platform.machine() in ("aarch64", "arm64") else "amd64"
    digest, reason = resolve_platform_digest(args.repo, args.tag, arch)
    if not digest:
        record.update({"status": "NOT_RUN", "reason": reason, "arch": arch})
        return finish(1)
    ref = f"docker.io/{args.repo}@{digest}"
    record.update({"arch": arch, "pinned_ref": ref})

    try:
        pull = subprocess.run([args.backend, "pull", ref], capture_output=True,
                              text=True, errors="replace", timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        record.update({"status": "NOT_RUN", "reason": f"pull_failed: {exc}"})
        return finish(1)
    if pull.returncode != 0:
        record.update({"status": "NOT_RUN", "reason": "pull_failed: " + pull.stderr.strip()[:300]})
        return finish(1)

    ok, reason2, verified = registry.verify_image_digest(args.backend, ref)
    record.update({"status": "RUN", "verified": ok, "reason": reason2, "digest": verified})
    return finish(0 if ok else 1)


if __name__ == "__main__":
    raise SystemExit(main())