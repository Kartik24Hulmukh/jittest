"""Fail-closed, portable path checks before host-side candidate preparation.

These checks require a quiescent checkout. They are not an OS sandbox and
cannot protect against a separate process racing directory replacement.
"""
from __future__ import annotations

from pathlib import Path, PureWindowsPath


def _refuse() -> None:
    # Local import: verify imports execute, which uses these helpers.
    from .verify import RefusalReason, VerifyRefusalError

    raise VerifyRefusalError(RefusalReason(
        code="unsafe_execution_path",
        message="execution paths must remain within the selected checkout without symlinks",
        phase="prepare",
    ))


def relative_execution_path(value: str | Path) -> Path:
    """Reject traversal and absolute/drive paths on every host platform."""
    text = str(value)
    win = PureWindowsPath(text)
    if not text or "\x00" in text or win.drive or win.root:
        _refuse()
    path = Path(text.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        _refuse()
    return path


def contained_execution_path(root: Path, relative: str | Path, *, directory: bool = False) -> Path:
    """Check every existing component before creating any candidate directory."""
    rel = relative_execution_path(relative)
    root = root.resolve()
    target = root / rel
    current = root
    try:
        for part in rel.parts:
            current = current / part
            if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
                _refuse()
        if not target.resolve().is_relative_to(root):
            _refuse()
        if directory and not target.is_dir():
            _refuse()
    except (OSError, RuntimeError):
        _refuse()
    return target
