"""Output trust boundary enforcement (handoff P0-4).

Evidence output is confined to a bounded writable directory. Source,
metadata and host mounts must stay untouched. Symlinks, hard links,
device files, traversal, oversized output and undeclared writes are
refused fail-closed.
"""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .verify import VerifyRefusalError


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_FILES = 1000


class OutputTrustRefusal(VerifyRefusalError):
    """Fail-closed refusal for output boundary violations."""


@dataclass(frozen=True)
class OutputLimits:
    max_bytes: int = DEFAULT_MAX_BYTES
    max_files: int = DEFAULT_MAX_FILES


@dataclass
class OutputScan:
    ok: bool
    violations: list[str] = field(default_factory=list)
    total_bytes: int = 0
    files: int = 0

    def raise_if_bad(self) -> None:
        if not self.ok:
            raise OutputTrustRefusal("output_boundary_violation: " + "; ".join(self.violations))


def _is_special(mode: int) -> str:
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISBLK(mode):
        return "block_device"
    if stat.S_ISCHR(mode):
        return "char_device"
    return ""


def scan_output_tree(
    evidence_dir: Path | str,
    limits: OutputLimits | None = None,
    declared: tuple[str, ...] | None = None,
) -> OutputScan:
    """Scan a writable evidence tree; refuse every unsafe entry."""
    lim = limits or OutputLimits()
    root = Path(evidence_dir).resolve()
    scan = OutputScan(ok=True)
    seen_norm: dict[str, str] = {}
    if not root.is_dir():
        scan.ok = False
        scan.violations.append("evidence_dir_missing")
        return scan
    for current, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames) + sorted(filenames):
            path = Path(current) / name
            entry = path.lstat()
            rel = path.relative_to(root).as_posix()
            kind = _is_special(entry.st_mode)
            if kind:
                scan.ok = False
                scan.violations.append(f"{kind}:{rel}")
                continue
            resolved = path.resolve()
            if not str(resolved).startswith(str(root) + os.sep):
                scan.ok = False
                scan.violations.append(f"traversal:{rel}")
                continue
            if entry.st_nlink > 1:
                scan.ok = False
                scan.violations.append(f"hardlink:{rel}")
            norm = unicodedata.normalize("NFC", rel)
            if norm in seen_norm and seen_norm[norm] != rel:
                scan.ok = False
                scan.violations.append(f"unicode_collision:{rel}")
            seen_norm[norm] = rel
            if declared is not None and rel not in declared:
                scan.ok = False
                scan.violations.append(f"undeclared_write:{rel}")
            if path.is_file():
                scan.files += 1
                scan.total_bytes += entry.st_size
                if scan.total_bytes > lim.max_bytes:
                    scan.ok = False
                    scan.violations.append(f"oversized_output:{rel}")
    if scan.files > lim.max_files:
        scan.ok = False
        scan.violations.append("too_many_files")
    return scan


def snapshot_tree(root: Path | str) -> dict[str, tuple[int, str]]:
    """Record relpath -> (size, mode) for a protected read-only tree."""
    base = Path(root).resolve()
    out: dict[str, tuple[int, str]] = {}
    if not base.is_dir():
        return out
    for current, _dirs, files in os.walk(base):
        for name in files:
            path = Path(current) / name
            entry = path.lstat()
            out[path.relative_to(base).as_posix()] = (entry.st_size, _sha(path))
    return out


def assert_unchanged(root: Path | str, snapshot: dict[str, tuple[int, str]]) -> None:
    now = snapshot_tree(root)
    if now != snapshot:
        changed = sorted(set(now) ^ set(snapshot)) or sorted(
            k for k in set(now) & set(snapshot) if now[k] != snapshot[k]
        )
        raise OutputTrustRefusal("protected_tree_modified: " + ",".join(changed[:8]))
