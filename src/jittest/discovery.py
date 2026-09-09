"""Non-executing manifest discovery for candidate worktrees (Task J1-1).

Enforces:
1. Zero candidate code execution or module import.
2. File read limit capped at 1 MiB.
3. Path containment (symlink escapes outside worktree).
4. Manifest parsing for pyproject.toml, setup.cfg, requirements*.txt,
   Pipfile, poetry.lock, uv.lock, and static setup.py text scanning.
5. Detection of execution-bearing hooks (*.pth, sitecustomize.py, pytest.py, conftest.py).
"""

from __future__ import annotations

import ast
import configparser
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_MANIFEST_FILE_SIZE = 1024 * 1024  # 1 MiB


@dataclass
class ManifestReport:
    packaging_kind: str = "unknown"
    declared_dependencies: list[str] = field(default_factory=list)
    build_backend: str | None = None
    has_setup_py: bool = False
    has_pth_files: bool = False
    has_sitecustomize: bool = False
    has_shadowed_pytest: bool = False
    has_conftest: bool = False
    symlink_escapes: list[Path] = field(default_factory=list)
    ambiguous: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packaging_kind": self.packaging_kind,
            "declared_dependencies": list(self.declared_dependencies),
            "build_backend": self.build_backend,
            "has_setup_py": self.has_setup_py,
            "has_pth_files": self.has_pth_files,
            "has_sitecustomize": self.has_sitecustomize,
            "has_shadowed_pytest": self.has_shadowed_pytest,
            "has_conftest": self.has_conftest,
            "symlink_escapes": [str(p) for p in self.symlink_escapes],
            "ambiguous": self.ambiguous,
            "reasons": list(self.reasons),
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def _safe_read_text(path: Path, max_bytes: int = MAX_MANIFEST_FILE_SIZE) -> tuple[str | None, str | None]:
    """Read a file up to max_bytes without executing or importing anything.

    Returns (content, error_reason).
    """
    try:
        stat_res = path.stat()
        if stat_res.st_size > max_bytes:
            return None, f"file_size_exceeded: {path.name} ({stat_res.st_size} bytes > {max_bytes} bytes)"
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes), None
    except Exception as exc:
        return None, f"read_error: {path.name}: {exc}"


def _check_symlink_escape(path: Path, worktree: Path) -> bool:
    """Check if a symlink escapes the worktree boundary."""
    try:
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(worktree)
                return False
            except ValueError:
                return True
    except Exception:
        return True
    return False


def _scan_setup_py_ast(content: str) -> tuple[list[str], bool, str | None]:
    """Statically parse setup.py using AST to find install_requires without execution."""
    deps: list[str] = []
    ambiguous = False
    reason: str | None = None

    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return [], True, f"setup_py_syntax_error: {exc}"

    setup_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name in ("setup", "setup_package"):
                setup_calls.append(node)

    for call in setup_calls:
        for kw in call.keywords:
            if kw.arg in ("install_requires", "requires"):
                if isinstance(kw.value, (ast.List, ast.Tuple)):
                    for elt in kw.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            deps.append(elt.value.strip())
                        else:
                            ambiguous = True
                            reason = "dynamic_setup_py: non-constant dependency element in install_requires"
                else:
                    ambiguous = True
                    reason = f"dynamic_setup_py: {kw.arg} is not a static list/tuple ({type(kw.value).__name__})"

    if not setup_calls and "setup(" in content:
        ambiguous = True
        reason = "dynamic_setup_py: setup() call not recognized via simple AST"

    return deps, ambiguous, reason


def discover_manifest(worktree: Path | str) -> ManifestReport:
    """Discover packaging and dependencies statically from worktree without candidate execution.

    Never imports candidate modules and strictly confines path traversal to worktree.
    """
    wt = Path(worktree).resolve()
    report = ManifestReport()
    deps_set: set[str] = set()

    # 1. Scan for symlink escapes and candidate execution hooks across top-level and direct children
    try:
        for root, dirs, files in os.walk(wt):
            root_path = Path(root)
            # Prevent scanning inside .git
            if ".git" in dirs:
                dirs.remove(".git")
            if ".venv" in dirs:
                dirs.remove(".venv")

            # Check symlinks in dirs
            for d in list(dirs):
                d_path = root_path / d
                if d_path.is_symlink():
                    if _check_symlink_escape(d_path, wt):
                        report.symlink_escapes.append(d_path)
                        report.ambiguous = True
                        report.reasons.append(f"symlink_escape: directory {d_path.relative_to(wt)}")
                    dirs.remove(d)  # Do not traverse into symlinked directory

            for f in files:
                f_path = root_path / f
                if f_path.is_symlink() and _check_symlink_escape(f_path, wt):
                    report.symlink_escapes.append(f_path)
                    report.ambiguous = True
                    report.reasons.append(f"symlink_escape: file {f_path.relative_to(wt)}")

                # Check execution hooks
                lower_f = f.lower()
                if lower_f.endswith(".pth"):
                    report.has_pth_files = True
                elif lower_f in ("sitecustomize.py", "usercustomize.py"):
                    report.has_sitecustomize = True
                elif lower_f == "pytest.py":
                    report.has_shadowed_pytest = True
                elif lower_f == "conftest.py":
                    report.has_conftest = True

            # Check shadowed pytest directory
            if (root_path / "pytest").is_dir():
                report.has_shadowed_pytest = True

    except Exception as exc:
        report.ambiguous = True
        report.reasons.append(f"tree_scan_error: {exc}")

    # 2. pyproject.toml discovery
    pyproject_file = wt / "pyproject.toml"
    if pyproject_file.is_file():
        content, err = _safe_read_text(pyproject_file)
        if err:
            report.ambiguous = True
            report.reasons.append(err)
        elif content is not None:
            try:
                data = tomllib.loads(content)
                report.packaging_kind = "pyproject"

                # Build backend
                bs = data.get("build-system", {})
                if isinstance(bs, dict):
                    report.build_backend = bs.get("build-backend")
                    for r in bs.get("requires", []):
                        if isinstance(r, str) and r.strip():
                            deps_set.add(r.strip())

                # PEP 621 dependencies
                proj = data.get("project", {})
                if isinstance(proj, dict):
                    p_deps = proj.get("dependencies", [])
                    if isinstance(p_deps, list):
                        for r in p_deps:
                            if isinstance(r, str) and r.strip():
                                deps_set.add(r.strip())

                    opt = proj.get("optional-dependencies", {})
                    if isinstance(opt, dict):
                        for req_list in opt.values():
                            if isinstance(req_list, list):
                                for r in req_list:
                                    if isinstance(r, str) and r.strip():
                                        deps_set.add(r.strip())

                # Poetry
                poetry = data.get("tool", {}).get("poetry", {})
                if isinstance(poetry, dict):
                    for table_name in ("dependencies", "dev-dependencies"):
                        tbl = poetry.get(table_name, {})
                        if isinstance(tbl, dict):
                            for pkg in tbl:
                                if isinstance(pkg, str) and pkg.lower() != "python":
                                    deps_set.add(pkg.strip())
                    for grp in poetry.get("group", {}).values():
                        if isinstance(grp, dict):
                            for pkg in grp.get("dependencies", {}):
                                if isinstance(pkg, str) and pkg.lower() != "python":
                                    deps_set.add(pkg.strip())

                # Flit
                flit_meta = data.get("tool", {}).get("flit", {}).get("metadata", {})
                if isinstance(flit_meta, dict):
                    for r in flit_meta.get("requires", []):
                        if isinstance(r, str) and r.strip():
                            deps_set.add(r.strip())
                    for req_list in flit_meta.get("requires-extra", {}).values():
                        if isinstance(req_list, list):
                            for r in req_list:
                                if isinstance(r, str) and r.strip():
                                    deps_set.add(r.strip())

            except Exception as exc:
                report.ambiguous = True
                report.reasons.append(f"pyproject_toml_syntax_error: {exc}")

    # 3. setup.cfg discovery
    setup_cfg_file = wt / "setup.cfg"
    if setup_cfg_file.is_file():
        if report.packaging_kind == "unknown":
            report.packaging_kind = "setup_cfg"
        content, err = _safe_read_text(setup_cfg_file)
        if err:
            report.ambiguous = True
            report.reasons.append(err)
        elif content is not None:
            try:
                cfg = configparser.ConfigParser()
                cfg.read_string(content)
                if cfg.has_section("options") and cfg.has_option("options", "install_requires"):
                    for line in cfg.get("options", "install_requires").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            deps_set.add(line)
                if cfg.has_section("options.extras_require"):
                    for _, v in cfg.items("options.extras_require"):
                        for line in v.splitlines():
                            line = line.strip()
                            if line and not line.startswith("#"):
                                deps_set.add(line)
            except Exception as exc:
                report.ambiguous = True
                report.reasons.append(f"setup_cfg_parse_error: {exc}")

    # 4. setup.py discovery (STATIC AST / TEXT SCAN ONLY)
    setup_py_file = wt / "setup.py"
    if setup_py_file.is_file():
        report.has_setup_py = True
        if report.packaging_kind == "unknown":
            report.packaging_kind = "setup_py"
        content, err = _safe_read_text(setup_py_file)
        if err:
            report.ambiguous = True
            report.reasons.append(err)
        elif content is not None:
            s_deps, s_ambiguous, s_reason = _scan_setup_py_ast(content)
            for d in s_deps:
                deps_set.add(d)
            if s_ambiguous:
                report.ambiguous = True
                if s_reason:
                    report.reasons.append(s_reason)

    # 5. requirements*.txt files
    req_candidates = list(wt.glob("requirements*.txt")) + list(wt.glob("*-requirements.txt"))
    req_dir = wt / "requirements"
    if req_dir.is_dir():
        req_candidates.extend(req_dir.glob("*.txt"))

    for rf in sorted(set(req_candidates)):
        if rf.is_file():
            if report.packaging_kind == "unknown":
                report.packaging_kind = "requirements"
            content, err = _safe_read_text(rf)
            if err:
                report.ambiguous = True
                report.reasons.append(err)
            elif content is not None:
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    deps_set.add(line)

    # 6. Pipfile discovery
    pipfile = wt / "Pipfile"
    if pipfile.is_file():
        content, err = _safe_read_text(pipfile)
        if err:
            report.ambiguous = True
            report.reasons.append(err)
        elif content is not None:
            try:
                p_data = tomllib.loads(content)
                for sec in ("packages", "dev-packages"):
                    tbl = p_data.get(sec, {})
                    if isinstance(tbl, dict):
                        for pkg in tbl:
                            if isinstance(pkg, str) and pkg.lower() != "python":
                                deps_set.add(pkg.strip())
            except Exception as exc:
                report.ambiguous = True
                report.reasons.append(f"pipfile_parse_error: {exc}")

    # 7. poetry.lock / uv.lock presence
    for lock_name in ("poetry.lock", "uv.lock"):
        lf = wt / lock_name
        if lf.is_file():
            stat_lf = lf.stat()
            if stat_lf.st_size > MAX_MANIFEST_FILE_SIZE:
                report.ambiguous = True
                report.reasons.append(f"oversized_lockfile: {lock_name}")

    report.declared_dependencies = sorted(deps_set)
    return report
