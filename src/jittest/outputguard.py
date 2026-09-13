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


def _sha(path: Path, expected: os.stat_result) -> str:
    """Stream only a regular, single-link file and detect replacement/mutation.

    The writer must already be stopped. O_NOFOLLOW/O_NONBLOCK add POSIX
    defense in depth; this is not a portable live-writer confinement primitive.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        with os.fdopen(fd, "rb") as handle:
            fd = -1  # the handle owns it now
            before = os.fstat(handle.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or _file_identity(before) != _file_identity(expected)):
                raise OutputTrustRefusal("protected_tree_changed_during_scan")
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
            after = os.fstat(handle.fileno())
            if (_identity(before) != _identity(after)
                    or _identity(expected) != _identity(path.lstat())):
                raise OutputTrustRefusal("protected_tree_changed_during_scan")
            return digest
    finally:
        if fd != -1:
            os.close(fd)


def _file_identity(entry: os.stat_result) -> tuple[int, ...]:
    # Compare identity across stat APIs; timestamps are compared within each
    # API below. Windows path stat and descriptor stat can represent timestamps
    # differently, so cross-API timestamp equality produces false refusals.
    return (entry.st_dev, entry.st_ino, entry.st_mode, entry.st_nlink, entry.st_size)


def _identity(entry: os.stat_result) -> tuple[int, ...]:
    return (entry.st_dev, entry.st_ino, entry.st_mode, entry.st_nlink,
            entry.st_size, entry.st_mtime_ns, entry.st_ctime_ns)


def _root(path: Path | str) -> Path:
    root = Path(path)
    entry = root.lstat()  # do not resolve away a symlink at the boundary
    if not stat.S_ISDIR(entry.st_mode):
        raise OutputTrustRefusal("evidence_root_not_directory_or_symlink")
    return root.resolve(strict=True)


DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_FILES = 1000


class OutputTrustRefusal(VerifyRefusalError):
    """Fail-closed refusal for output boundary violations."""


@dataclass(frozen=True)
class OutputLimits:
    max_bytes: int = DEFAULT_MAX_BYTES
    max_files: int = DEFAULT_MAX_FILES
    max_entries: int = 10000

    def __post_init__(self) -> None:
        for name in ("max_bytes", "max_files", "max_entries"):
            value = getattr(self, name)
            if type(value) is not int or value < (1 if name == "max_entries" else 0):
                raise ValueError(f"{name} must be a valid nonnegative integer (entries > 0)")


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
    """Inspect a quiescent evidence tree, failing closed on incomplete scans.

    Call only after candidate execution and all descendants have stopped, with
    trusted ancestors and no concurrent writers. This detects unsafe output;
    it does not itself enforce filesystem isolation or prevent TOCTOU attacks.
    ``declared`` lists directories as well as files. Entry limits bound scan
    work/results, not os.walk's allocation for a single enormous directory.
    """
    lim = limits or OutputLimits()
    scan = OutputScan(ok=True)
    seen_norm: dict[str, str] = {}

    def reject(reason: str) -> None:
        scan.ok = False
        scan.violations.append(reason)

    def walk_error(exc: OSError) -> None:
        reject(f"evidence_unreadable:{type(exc).__name__}")

    try:
        root = _root(evidence_dir)
        entries = 0
        for current, dirnames, filenames in os.walk(root, followlinks=False, onerror=walk_error):
            for name in sorted(dirnames) + sorted(filenames):
                entries += 1
                if entries > lim.max_entries:
                    reject("too_many_entries")
                    return scan
                path = Path(current) / name
                entry = path.lstat()
                rel = path.relative_to(root).as_posix()
                kind = _is_special(entry.st_mode)
                if kind:
                    reject(f"{kind}:{rel}")
                    if name in dirnames:
                        dirnames.remove(name)
                    continue
                if not (stat.S_ISDIR(entry.st_mode) or stat.S_ISREG(entry.st_mode)):
                    reject(f"unknown_file_type:{rel}")
                    continue
                if not path.resolve(strict=True).is_relative_to(root):
                    reject(f"traversal:{rel}")
                    return scan
                # Directory link counts normally include '.' and child '..'.
                if stat.S_ISREG(entry.st_mode) and entry.st_nlink != 1:
                    reject(f"hardlink:{rel}")
                norm = unicodedata.normalize("NFC", rel)
                if norm in seen_norm and seen_norm[norm] != rel:
                    reject(f"unicode_collision:{rel}")
                seen_norm[norm] = rel
                if declared is not None and rel not in declared:
                    reject(f"undeclared_write:{rel}")
                if stat.S_ISREG(entry.st_mode):
                    scan.files += 1
                    scan.total_bytes += entry.st_size
                    if scan.files > lim.max_files:
                        reject("too_many_files")
                        return scan
                    if scan.total_bytes > lim.max_bytes:
                        reject(f"oversized_output:{rel}")
                        return scan
    except (OSError, ValueError, OutputTrustRefusal) as exc:
        reject(f"evidence_unreadable:{type(exc).__name__}")
    return scan


def snapshot_tree(root: Path | str) -> dict[str, tuple[int, str]]:
    """Snapshot a quiescent protected tree, including modes and directories.

    Values are (size, mode-prefixed SHA-256), or (0, directory mode marker).
    Snapshots are opaque process-local values, not a persisted receipt schema.
    Missing/unreadable roots and special nodes refuse instead of looking empty.
    """
    out: dict[str, tuple[int, str]] = {}

    def walk_error(exc: OSError) -> None:
        raise exc

    try:
        base = _root(root)
        out["."] = (0, f"dir:{base.lstat().st_mode}")
        for current, dirs, files in os.walk(base, followlinks=False, onerror=walk_error):
            for name in sorted(dirs) + sorted(files):
                path = Path(current) / name
                entry = path.lstat()
                rel = path.relative_to(base).as_posix()
                if stat.S_ISDIR(entry.st_mode):
                    out[rel] = (0, f"dir:{entry.st_mode}")
                elif stat.S_ISREG(entry.st_mode) and entry.st_nlink == 1:
                    out[rel] = (entry.st_size, f"file:{entry.st_mode}:{_sha(path, entry)}")
                else:
                    raise OutputTrustRefusal(f"protected_tree_unsafe_entry:{rel}")
    except (OSError, ValueError) as exc:
        raise OutputTrustRefusal(f"protected_tree_unreadable:{type(exc).__name__}") from exc
    return out


def assert_unchanged(root: Path | str, snapshot: dict[str, tuple[int, str]]) -> None:
    now = snapshot_tree(root)
    if now != snapshot:
        changed = sorted(set(now) ^ set(snapshot)) or sorted(
            k for k in set(now) & set(snapshot) if now[k] != snapshot[k]
        )
        raise OutputTrustRefusal("protected_tree_modified: " + ",".join(changed[:8]))
